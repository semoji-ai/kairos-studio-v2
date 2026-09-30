"""settings.json 로드/저장. 화이트리스트 검증 — 위험 권한 모드는 여기 없음(스펙)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "data_dir": str(Path.home() / ".kairos-studio"),
    "default_provider": "claude",
    "routing_rules_enabled": True,
    "codex_sandbox": "read-only",
    "claude_permission_mode": "default",
    "workspace_dir": None,
    "output_dir": None,
    "learning_recall_enabled": True,
    "font_body": "system",
    "font_heading": "system",
}

_ALLOWED = {
    "default_provider": {"claude", "codex"},
    "codex_sandbox": {"read-only", "workspace-write"},
    "claude_permission_mode": {"default", "acceptEdits"},
    # 앱에 번들된 글꼴 id — app/src/fonts.ts 의 목록과 같아야 한다
    "font_body": {"system", "pretendard", "suit", "ibm-plex-sans-kr", "nanum-gothic"},
    "font_heading": {"system", "maruburi", "gowun-batang",
                     "noto-serif-kr", "nanum-myeongjo", "hahmlet"},
}


OUTPUT_DIRNAME = "KS_output"
WORKSPACE_DIRNAME = "publish-agent"


def _windows_documents() -> str | None:
    """윈도우 '문서' 폴더의 실제 위치 — 원드라이브로 옮겨진 경우도 따라간다."""
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            value, _ = winreg.QueryValueEx(key, "Personal")
        return os.path.expandvars(value)
    except (ImportError, OSError):
        return None


def documents_dir() -> Path:
    """기본 폴더를 둘 곳: 문서 폴더, 없으면 홈 폴더 (맥·윈도우 공통)."""
    override = os.environ.get("KAIROS_DOCUMENTS_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        found = _windows_documents()
        if found and Path(found).is_dir():
            return Path(found)
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


def _folder_defaults(raw: dict) -> dict:
    """설정 파일에 값이 아예 없을 때만 채운다 — 목사님이 일부러 비운 값은 그대로 둔다."""
    out = {}
    base = documents_dir()
    if "output_dir" not in raw:
        out["output_dir"] = str(base / OUTPUT_DIRNAME)
    if "workspace_dir" not in raw and (base / WORKSPACE_DIRNAME).is_dir():
        out["workspace_dir"] = str(base / WORKSPACE_DIRNAME)
    return out


def config_path() -> Path:
    d = os.environ.get("KAIROS_CONFIG_DIR")
    base = Path(d).expanduser() if d else Path.home() / ".kairos-studio"
    return base / "settings.json"


def _validate(patch: dict) -> None:
    for key, allowed in _ALLOWED.items():
        if key in patch and patch[key] not in allowed:
            raise ValueError(f"invalid {key}: {patch[key]!r}")
    if "routing_rules_enabled" in patch and not isinstance(
            patch["routing_rules_enabled"], bool):
        raise ValueError("routing_rules_enabled must be bool")
    if "data_dir" in patch and not isinstance(patch["data_dir"], str):
        raise ValueError("data_dir must be str")
    if "learning_recall_enabled" in patch and not isinstance(
            patch["learning_recall_enabled"], bool):
        raise ValueError("learning_recall_enabled must be bool")
    if "workspace_dir" in patch:
        v = patch["workspace_dir"]
        if v is not None:
            if not isinstance(v, str):
                raise ValueError("workspace_dir must be str or None")
            if not Path(v).expanduser().is_dir():
                raise ValueError("workspace_dir does not exist")
    if "output_dir" in patch:
        v = patch["output_dir"]
        if v is not None and not isinstance(v, str):
            raise ValueError("output_dir must be str or None")


def _load_raw() -> dict:
    """settings.json 파일 내용 그대로 (기본값 미적용). 파일 없음/손상 시 {}."""
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}  # 깨진 파일이면 기본값으로 동작 (기록은 다음 save가 복구)
    return data if isinstance(data, dict) else {}


def restore_raw(raw: dict) -> None:
    """settings.json 파일을 raw로 그대로 덮어씀 (기본값 병합 없음). 롤백용."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def load() -> dict:
    raw = _load_raw()
    merged = dict(DEFAULTS)
    merged.update(_folder_defaults(raw))
    merged.update(raw)
    # 글꼴은 목록에서 빠질 수 있으니(버전 변경·수동 편집) 모르는 값은 기본값으로
    for key in ("font_body", "font_heading"):
        if merged[key] not in _ALLOWED[key]:
            merged[key] = DEFAULTS[key]
    return merged


def explicit_keys() -> set[str]:
    """settings.json 파일에 실제로 기록된 키 집합 (파일 없음/손상 시 빈 집합)."""
    return set(_load_raw().keys())


def save(patch: dict) -> dict:
    _validate(patch)
    raw = _load_raw()
    raw.update(patch)
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    merged = dict(DEFAULTS)
    merged.update(_folder_defaults(raw))
    merged.update(raw)
    return merged
