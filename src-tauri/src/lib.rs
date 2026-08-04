pub mod sidecar;

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::fs::{self, OpenOptions};
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

/// Resolved paths the sidecar needs, dev vs. release.
pub struct ResolvedPaths {
    /// `python -m core` interpreter.
    pub python: PathBuf,
    /// Directory containing the `core` package; `python -m core` is run with
    /// this as `current_dir` (its parent must be on `sys.path`, so we set
    /// `current_dir` to `core_dir`'s parent).
    pub core_dir: PathBuf,
    /// Built SPA assets (`KAIROS_STATIC_DIR`).
    pub static_dir: PathBuf,
    /// Directory holding `publish_agent.zip` etc. (`KAIROS_BUNDLE_DIR`).
    pub bundle_dir: PathBuf,
}

/// dev (debug build): everything relative to the repo checkout.
/// release: everything relative to Tauri's bundled `resource_dir()`.
pub fn resolve_paths(repo_root: &Path, resource_dir: Option<&Path>) -> ResolvedPaths {
    resolve_paths_for(repo_root, resource_dir, cfg!(debug_assertions))
}

/// Same as [`resolve_paths`] but with the dev/release choice passed explicitly,
/// so both branches are unit-testable regardless of how the test binary itself
/// was compiled.
pub fn resolve_paths_for(repo_root: &Path, resource_dir: Option<&Path>, dev: bool) -> ResolvedPaths {
    if dev {
        ResolvedPaths {
            python: sidecar::python_path(repo_root, sidecar::Os::current(), false),
            core_dir: repo_root.join("core"),
            static_dir: repo_root.join("app").join("dist"),
            bundle_dir: repo_root.to_path_buf(),
        }
    } else {
        let base = resource_dir.expect("resource_dir required in release builds");
        // tauri.release.conf.json maps every bundled file under
        // `resource_dir()/resources/` (core, dist, publish_agent.zip,
        // python-embed), so all release paths — including the bundle dir the
        // sidecar reads publish_agent.zip from — hang off that subdirectory.
        let res = base.join("resources");
        ResolvedPaths {
            python: sidecar::python_path(&res, sidecar::Os::current(), true),
            core_dir: res.join("core"),
            static_dir: res.join("dist"),
            bundle_dir: res,
        }
    }
}

pub fn spawn_sidecar(paths: &ResolvedPaths, token: &str, data_dir: &Path) -> std::io::Result<(Child, ServerInfo)> {
    // `python -m core` needs `core`'s *parent* directory on sys.path/cwd.
    let cwd = paths.core_dir.parent().unwrap_or(&paths.core_dir);
    let mut cmd = Command::new(&paths.python);
    cmd.arg("-m").arg("core");
    for (k, v) in sidecar::sidecar_env(&paths.static_dir, &paths.bundle_dir, token, data_dir) {
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
    cmd.current_dir(cwd);
    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // Prevent the embedded interpreter from allocating a visible console
        // while preserving the inherited handshake pipe used during startup.
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
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

/// Start the persistent PPT queue worker as a sibling of the API sidecar.
///
/// The child is deliberately excluded from `SidecarState`: closing or
/// restarting the Tauri shell reaps only the HTTP sidecar, while this worker
/// continues processing the durable queue.
pub fn spawn_presentation_worker(paths: &ResolvedPaths, data_dir: &Path) -> std::io::Result<u32> {
    let cwd = paths.core_dir.parent().unwrap_or(&paths.core_dir);
    let log_dir = data_dir.join("presentations");
    fs::create_dir_all(&log_dir)?;
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("worker.log"))?;
    let stderr = stdout.try_clone()?;

    let mut cmd = Command::new(&paths.python);
    cmd.arg("-m")
        .arg("core.presentation_worker")
        .current_dir(cwd)
        .env("KAIROS_DATA_DIR", data_dir)
        .env("KAIROS_CONFIG_DIR", data_dir)
        .env("KAIROS_BUNDLE_DIR", &paths.bundle_dir)
        .env(
            "PYTHONPATH",
            paths.bundle_dir.join("python-packages").to_string_lossy().to_string(),
        )
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }

    let mut child = cmd.spawn()?;
    let pid = child.id();
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(pid)
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
            let resource_dir = app.path().resource_dir().ok();
            let paths = resolve_paths(&root, resource_dir.as_deref());
            let (mut child, info) = spawn_sidecar(&paths, &token, &data_dir)
                .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

            if !wait_for_health(info.port, 100, 100) {
                // No window exists yet, so no Destroyed/Exit event will fire to
                // clean up — reap here or the sidecar orphans and holds its port.
                kill_child(&mut child);
                return Err(format!("sidecar unhealthy on port {}", info.port).into());
            }
            app.state::<SidecarState>().0.lock().unwrap().replace(child);
            spawn_presentation_worker(&paths, &data_dir)
                .map_err(|e| format!("failed to spawn presentation worker: {e}"))?;

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

    #[test]
    fn resolve_paths_dev_uses_repo_root() {
        let root = Path::new("/repo");
        let paths = resolve_paths_for(root, Some(Path::new("/should/be/ignored")), true);
        assert_eq!(paths.core_dir, PathBuf::from("/repo/core"));
        assert_eq!(paths.static_dir, PathBuf::from("/repo/app/dist"));
        assert_eq!(paths.bundle_dir, PathBuf::from("/repo"));
        assert!(paths.python.to_string_lossy().contains(".venv"));
    }

    #[test]
    fn resolve_paths_release_uses_resource_dir() {
        let root = Path::new("/repo");
        let resource_dir = Path::new("/Applications/Kairos.app/Contents/Resources");
        let paths = resolve_paths_for(root, Some(resource_dir), false);
        assert_eq!(paths.core_dir, resource_dir.join("resources").join("core"));
        assert_eq!(paths.static_dir, resource_dir.join("resources").join("dist"));
        // publish_agent.zip is bundled under resources/, so the bundle dir the
        // sidecar receives must point there too.
        assert_eq!(paths.bundle_dir, resource_dir.join("resources"));
        // python comes from Os::current(): bundled python-embed on Windows,
        // system python3 elsewhere.
        #[cfg(windows)]
        assert_eq!(
            paths.python,
            resource_dir.join("resources").join("python-embed").join("python.exe")
        );
        #[cfg(not(windows))]
        assert_eq!(paths.python, PathBuf::from("/usr/bin/python3"));
    }

    #[test]
    #[should_panic(expected = "resource_dir required")]
    fn resolve_paths_release_without_resource_dir_panics() {
        resolve_paths_for(Path::new("/repo"), None, false);
    }
}
