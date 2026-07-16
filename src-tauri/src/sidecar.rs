use std::path::{Path, PathBuf};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Os {
    Unix,
    Windows,
}

impl Os {
    pub fn current() -> Os {
        if cfg!(windows) {
            Os::Windows
        } else {
            Os::Unix
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServerInfo {
    pub host: String,
    pub port: u16,
    pub token: String,
}

pub fn python_path(repo_root: &Path, os: Os) -> PathBuf {
    match os {
        Os::Unix => repo_root.join(".venv").join("bin").join("python"),
        Os::Windows => repo_root.join(".venv").join("Scripts").join("python.exe"),
    }
}

pub fn sidecar_env(repo_root: &Path, token: &str, data_dir: &Path) -> Vec<(String, String)> {
    let p = |parts: &[&str]| {
        let mut d = repo_root.to_path_buf();
        for part in parts {
            d = d.join(part);
        }
        d.to_string_lossy().to_string()
    };
    vec![
        ("PORT".to_string(), "0".to_string()),
        ("TOKEN".to_string(), token.to_string()),
        ("KAIROS_STATIC_DIR".to_string(), p(&["app", "dist"])),
        ("KAIROS_DATA_DIR".to_string(), data_dir.to_string_lossy().to_string()),
    ]
}

pub fn parse_server_info(line: &str) -> Option<ServerInfo> {
    let v: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    let host = v.get("host")?.as_str()?.to_string();
    let port = v.get("port")?.as_u64()?;
    let token = v.get("token")?.as_str()?.to_string();
    if port == 0 || port > u16::MAX as u64 {
        return None;
    }
    Some(ServerInfo { host, port: port as u16, token })
}

pub fn health_url(port: u16) -> String {
    format!("http://127.0.0.1:{}/health", port)
}

pub fn response_is_ok(raw: &[u8]) -> bool {
    let head_end = raw.windows(2).position(|w| w == b"\r\n").unwrap_or(raw.len());
    let status_line = String::from_utf8_lossy(&raw[..head_end]);
    status_line.contains("200")
}

pub fn kill_command(pid: u32, os: Os) -> (String, Vec<String>) {
    match os {
        Os::Unix => ("kill".to_string(), vec!["-TERM".to_string(), pid.to_string()]),
        Os::Windows => (
            "taskkill".to_string(),
            vec!["/T".to_string(), "/F".to_string(), "/PID".to_string(), pid.to_string()],
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_path_is_platform_specific() {
        let root = Path::new("/repo");
        assert_eq!(python_path(root, Os::Unix), PathBuf::from("/repo/.venv/bin/python"));
        let win = python_path(Path::new("C:\\repo"), Os::Windows);
        assert!(win.to_string_lossy().replace('/', "\\").ends_with(".venv\\Scripts\\python.exe"));
    }

    #[test]
    fn sidecar_env_sets_required_vars() {
        let env = sidecar_env(Path::new("/repo"), "tok123", Path::new("/data"));
        let get = |k: &str| env.iter().find(|(a, _)| a == k).map(|(_, v)| v.clone());
        assert_eq!(get("PORT"), Some("0".to_string()));
        assert_eq!(get("TOKEN"), Some("tok123".to_string()));
        assert_eq!(get("KAIROS_STATIC_DIR"), Some("/repo/app/dist".to_string()));
        assert_eq!(get("KAIROS_DATA_DIR"), Some("/data".to_string()));
    }

    #[test]
    fn parse_server_info_reads_json_line() {
        let info = parse_server_info("{\"host\": \"127.0.0.1\", \"port\": 51234, \"token\": \"abc\"}").unwrap();
        assert_eq!(info.host, "127.0.0.1");
        assert_eq!(info.port, 51234);
        assert_eq!(info.token, "abc");
    }

    #[test]
    fn parse_server_info_rejects_garbage() {
        assert!(parse_server_info("not json").is_none());
        assert!(parse_server_info("{\"port\": \"nope\"}").is_none());
    }

    #[test]
    fn health_url_uses_port() {
        assert_eq!(health_url(8080), "http://127.0.0.1:8080/health");
    }

    #[test]
    fn response_is_ok_detects_200() {
        assert!(response_is_ok(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true}"));
        assert!(!response_is_ok(b"HTTP/1.0 404 Not Found\r\n\r\n"));
        assert!(!response_is_ok(b""));
    }

    #[test]
    fn kill_command_is_platform_specific() {
        assert_eq!(kill_command(42, Os::Unix), ("kill".to_string(), vec!["-TERM".to_string(), "42".to_string()]));
        assert_eq!(
            kill_command(42, Os::Windows),
            ("taskkill".to_string(), vec!["/T".to_string(), "/F".to_string(), "/PID".to_string(), "42".to_string()])
        );
    }
}
