"""첫 실행 설치 마법사 헬퍼 (P4). Python stdlib only."""
from __future__ import annotations

import os
import shutil
import sys
import zipfile
from datetime import datetime
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


BACKUP_DIRNAME = ".kairos-backup"


def _is_protected(rel: str) -> bool:
    # 교회별 맞춤 파일(custom-*)은 코어 갱신이 덮어쓰지 않는다.
    return rel.rsplit("/", 1)[-1].startswith("custom-")


def _plan_update(zf: zipfile.ZipFile, workspace: Path) -> tuple[list[str], list[str]]:
    """zip 항목 중 작업 폴더와 내용이 다른 파일(changed)과 없는 파일(added)."""
    _check_members(zf)
    changed: list[str] = []
    added: list[str] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = info.filename.replace("\\", "/")
        if _is_protected(rel):
            continue
        target = workspace / rel
        if not target.is_file():
            added.append(rel)
        elif target.read_bytes() != zf.read(info):
            changed.append(rel)
    return sorted(changed), sorted(added)


def workspace_update_status(bundle_dir: Path, workspace: Path) -> dict:
    """번들 zip 대비 설치된 스킬의 갱신 필요 여부.

    zip에 있는 파일만 비교하므로 wiki/·projects/ 같은 사용자 데이터는 대상이 아니다.
    reason: "no_bundle"(zip 없음·개발 모드) | "no_workspace" | "git"(git pull로 갱신) | None
    """
    zip_path = Path(bundle_dir) / "publish_agent.zip"
    workspace = Path(workspace)
    base = {"available": False, "changed": [], "added": [], "reason": None}
    if not zip_path.is_file():
        return {**base, "reason": "no_bundle"}
    if not workspace.is_dir():
        return {**base, "reason": "no_workspace"}
    if (workspace / ".git").exists():
        return {**base, "reason": "git"}
    with zipfile.ZipFile(zip_path) as zf:
        changed, added = _plan_update(zf, workspace)
    return {**base, "available": bool(changed or added), "changed": changed, "added": added}


def update_workspace(bundle_dir: Path, workspace: Path) -> dict:
    """번들 zip으로 설치된 스킬을 갱신한다.

    바뀌는 파일은 먼저 .kairos-backup/<시각>/ 아래 같은 경로로 백업한다.
    zip에 없는 파일은 지우지 않고, custom-* 파일과 git 작업 폴더는 건드리지 않는다.
    반환: {"updated": [...], "backup_dir": 작업 폴더 기준 상대 경로 | None}
    """
    workspace = Path(workspace)
    if (workspace / ".git").exists():
        raise ValueError("git으로 관리되는 작업 폴더입니다 — git pull로 갱신하세요")
    zip_path = Path(bundle_dir) / "publish_agent.zip"
    if not zip_path.is_file():
        raise FileNotFoundError(f"publish_agent.zip not found: {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        changed, added = _plan_update(zf, workspace)
        backup_rel = None
        if changed:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_rel = f"{BACKUP_DIRNAME}/{stamp}"
            for rel in changed:
                dst = workspace / backup_rel / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace / rel, dst)
        for rel in changed + added:
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(rel))
    return {"updated": sorted(changed + added), "backup_dir": backup_rel}


def _check_members(zf: zipfile.ZipFile) -> None:
    """Reject zip-slip entries (absolute paths or ".." components)."""
    for member in zf.namelist():
        normalized = member.replace("\\", "/")
        if normalized.startswith("/") or Path(normalized).is_absolute():
            raise ValueError(f"unsafe zip entry (absolute path): {member!r}")
        if any(part == ".." for part in normalized.split("/")):
            raise ValueError(f"unsafe zip entry (path traversal): {member!r}")


def _safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract `zf` into `dest`, rejecting zip-slip entries.

    Raises ValueError if any member's name is an absolute path or contains
    ".." path components (which could otherwise write outside `dest`).
    """
    _check_members(zf)
    zf.extractall(dest)
