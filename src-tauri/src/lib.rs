pub mod sidecar;

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use sidecar::ServerInfo;

pub fn repo_root() -> PathBuf {
    // Dev-only: the crate sits at <repo>/src-tauri, so the repo is its parent.
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri has a parent")
        .to_path_buf()
}

pub fn spawn_sidecar(repo_root: &Path, token: &str, data_dir: &Path) -> std::io::Result<(Child, ServerInfo)> {
    let py = sidecar::python_path(repo_root, sidecar::Os::current());
    let mut cmd = Command::new(py);
    cmd.arg("-m").arg("core");
    for (k, v) in sidecar::sidecar_env(repo_root, token, data_dir) {
        cmd.env(k, v);
    }
    // Force unbuffered stdout: CPython block-buffers stdout when it is a pipe
    // (not a TTY), so the sidecar's one-line JSON handshake would otherwise sit
    // in the buffer forever while it serves, and the `read_line` below would
    // hang. PYTHONUNBUFFERED flushes it immediately.
    cmd.env("PYTHONUNBUFFERED", "1");
    // Parent-death watchdog: pipe stdin and tell the sidecar to exit when it hits
    // EOF. When this app process dies for ANY reason (Ctrl+C, crash, or graceful
    // quit), the OS closes the write end and the sidecar self-terminates — so it
    // never orphans and keeps holding its port. Opt-in via the env var so direct
    // / e2e launches (which don't set it) are unaffected. We keep child.stdin
    // open (never take() it) so the write end stays held until this process ends.
    cmd.env("KAIROS_SIDECAR_STDIN_WATCH", "1");
    cmd.current_dir(repo_root);
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    let mut child = cmd.spawn()?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::Other, "no stdout"))?;
    // Read the one-line JSON handshake with a deadline. A child that starts but
    // stalls before printing (import hang, port-bind retry) would otherwise block
    // startup forever; on timeout or a garbage line we reap the child so it can't
    // orphan (killing it closes stdout, which also unblocks the reader thread).
    let handshake = read_first_line_timeout(stdout, Duration::from_secs(15)).and_then(|line| {
        sidecar::parse_server_info(&line).ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("bad server info line: {line:?}"),
            )
        })
    });
    match handshake {
        Ok(info) => Ok((child, info)),
        Err(e) => {
            let _ = child.kill();
            let _ = child.wait();
            Err(e)
        }
    }
}

/// Read the first line from `reader`, giving up after `timeout`. The blocking
/// read runs on a helper thread so a stalled sidecar cannot hang the caller.
fn read_first_line_timeout<R: Read + Send + 'static>(
    reader: R,
    timeout: Duration,
) -> std::io::Result<String> {
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut r = BufReader::new(reader);
        let mut line = String::new();
        let res = r.read_line(&mut line).map(|_| line);
        let _ = tx.send(res);
    });
    match rx.recv_timeout(timeout) {
        Ok(res) => res,
        Err(_) => Err(std::io::Error::new(
            std::io::ErrorKind::TimedOut,
            "sidecar handshake timed out",
        )),
    }
}

pub fn wait_for_health(port: u16, attempts: u32, delay_ms: u64) -> bool {
    for _ in 0..attempts {
        if check_health_once(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(delay_ms));
    }
    false
}

fn check_health_once(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    let Ok(mut stream) = TcpStream::connect(&addr) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let req = format!("GET /health HTTP/1.0\r\nHost: {addr}\r\n\r\n");
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = Vec::new();
    let mut chunk = [0u8; 512];
    // read a little; the status line is all we need
    if let Ok(n) = stream.read(&mut chunk) {
        buf.extend_from_slice(&chunk[..n]);
    }
    sidecar::response_is_ok(&buf)
}

struct SidecarState(Mutex<Option<Child>>);

pub fn run() {
    let token = generate_token();
    let root = repo_root();

    let app = tauri::Builder::default()
        .manage(SidecarState(Mutex::new(None)))
        .setup(move |app| {
            use tauri::Manager;
            let data_dir = app.path().app_data_dir().expect("app data dir");
            let (mut child, info) = spawn_sidecar(&root, &token, &data_dir)
                .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

            if !wait_for_health(info.port, 100, 100) {
                // No window exists yet, so no Destroyed/Exit event will fire to
                // clean up — reap here or the sidecar orphans and holds its port.
                kill_child(&mut child);
                return Err(format!("sidecar unhealthy on port {}", info.port).into());
            }
            app.state::<SidecarState>().0.lock().unwrap().replace(child);

            let url = format!("http://127.0.0.1:{}/", info.port);
            tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::External(url.parse().unwrap()),
            )
            .title("Kairos Studio")
            .inner_size(1100.0, 760.0)
            .build()?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                use tauri::Manager;
                reap_sidecar(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // Reap on final app exit too (Cmd+Q / programmatic quit), so a quit that
    // doesn't route through a window Destroyed still stops the sidecar. Both
    // paths take() from the same Mutex, so whichever runs second is a no-op.
    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            reap_sidecar(app_handle);
        }
    });
}

fn reap_sidecar(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Some(mut child) = app.state::<SidecarState>().0.lock().unwrap().take() {
        kill_child(&mut child);
    }
}

fn kill_child(child: &mut Child) {
    let pid = child.id();
    let (prog, args) = sidecar::kill_command(pid, sidecar::Os::current());
    // Send the platform signal (TERM on unix, taskkill on windows), then give a
    // brief grace window for a clean shutdown before forcing + reaping.
    let _ = Command::new(prog).args(args).status();
    for _ in 0..20 {
        match child.try_wait() {
            Ok(Some(_)) => return, // exited on the graceful signal, already reaped
            Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            Err(_) => break,
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn generate_token() -> String {
    // Dependency-free but non-guessable: RandomState's hasher is SipHash keyed
    // with OS-provided randomness per process, so hashing pid+nanos through two
    // independently-keyed RandomStates yields two hard-to-predict u64s. Not a
    // CSPRNG, but the sidecar only trusts same-origin localhost anyway; this is
    // meant to keep the token from being trivially guessable, not cryptographic.
    use std::collections::hash_map::RandomState;
    use std::hash::{BuildHasher, Hash, Hasher};
    use std::time::{SystemTime, UNIX_EPOCH};

    let pid = std::process::id();
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);

    let mut h1 = RandomState::new().build_hasher();
    (pid, nanos).hash(&mut h1);
    let mut h2 = RandomState::new().build_hasher();
    (nanos, pid).hash(&mut h2);

    format!("kairos-dev-{:016x}{:016x}", h1.finish(), h2.finish())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn read_first_line_timeout_returns_first_line() {
        let r = Cursor::new(b"{\"port\":1}\ntrailing".to_vec());
        let line = read_first_line_timeout(r, Duration::from_secs(5)).unwrap();
        assert_eq!(line, "{\"port\":1}\n");
    }

    #[test]
    fn read_first_line_timeout_errors_on_stall() {
        // a reader that never yields the line must surface a TimedOut error
        // rather than blocking the caller forever
        struct Stall;
        impl Read for Stall {
            fn read(&mut self, _b: &mut [u8]) -> std::io::Result<usize> {
                std::thread::sleep(Duration::from_secs(30));
                Ok(0)
            }
        }
        let err = read_first_line_timeout(Stall, Duration::from_millis(150)).unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::TimedOut);
    }
}
