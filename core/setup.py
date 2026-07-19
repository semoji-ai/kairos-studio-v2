"""첫 실행 설치 마법사 헬퍼 (P4). Python stdlib only."""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path


def cli_install_command() -> list[str]:
    """Claude CLI 설치 명령. env `KAIROS_CLI_INSTALL_CMD` 우선, 기본은 OS별 공식 명령."""
    override = os.environ.get("KAIROS_CLI_INSTALL_CMD")
    if override:
        return override.split()
    if sys.platform == "win32":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-Command",
                "irm https://claude.ai/install.ps1 | iex"]
    return ["/bin/bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"]


def open_login_command() -> list[str]:
    """로그인 세션을 위한 터미널을 여는 명령. env `KAIROS_LOGIN_CMD` 우선."""
    override = os.environ.get("KAIROS_LOGIN_CMD")
    if override:
        return override.split()
    if sys.platform == "win32":
        return ["cmd", "/c", "start", "cmd", "/k", "claude"]
    # `open -a Terminal claude`는 claude를 '파일 경로'로 해석해 no-op이 된다.
    # osascript로 Terminal에서 claude를 실제 실행 + 전면으로.
    return [
        "osascript",
        "-e", 'tell application "Terminal" to do script "claude"',
        "-e", 'tell application "Terminal" to activate',
    ]


def install_workspace(bundle_dir: Path, dest_root: Path) -> dict:
    """bundle_dir/publish_agent.zip을 dest_root/publish-agent에 해제.

    이미 존재하면 해제를 건너뛰고 그대로 사용한다(덮어쓰지 않음).
    반환: {"workspace_dir": str, "existed": bool}
    """
    zip_path = Path(bundle_dir) / "publish_agent.zip"
    if not zip_path.is_file():
        raise FileNotFoundError(f"publish_agent.zip not found: {zip_path}")

    dest = Path(dest_root) / "publish-agent"
    existed = dest.is_dir()
    if not existed:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extractall(zf, dest)

    return {"workspace_dir": str(dest), "existed": existed}


def _safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract `zf` into `dest`, rejecting zip-slip entries.

    Raises ValueError if any member's name is an absolute path or contains
    ".." path components (which could otherwise write outside `dest`).
    """
    for member in zf.namelist():
        normalized = member.replace("\\", "/")
        if normalized.startswith("/") or Path(normalized).is_absolute():
            raise ValueError(f"unsafe zip entry (absolute path): {member!r}")
        if any(part == ".." for part in normalized.split("/")):
            raise ValueError(f"unsafe zip entry (path traversal): {member!r}")
    zf.extractall(dest)
