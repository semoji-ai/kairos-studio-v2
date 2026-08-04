"""settings.json 로드/저장. 화이트리스트 검증 — 위험 권한 모드는 여기 없음(스펙)."""
from __future__ import annotations

import json
import os
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
}

_ALLOWED = {
    "default_provider": {"claude", "codex"},
    "codex_sandbox": {"read-only", "workspace-write"},
    "claude_permission_mode": {"default", "acceptEdits"},
}


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
    merged = dict(DEFAULTS)
    merged.update(_load_raw())
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
    merged.update(raw)
    return merged
