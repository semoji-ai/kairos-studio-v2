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


def load() -> dict:
    merged = dict(DEFAULTS)
    p = config_path()
    if p.is_file():
        try:
            merged.update(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass  # 깨진 파일이면 기본값으로 동작 (기록은 다음 save가 복구)
    return merged


def save(patch: dict) -> dict:
    _validate(patch)
    merged = load()
    merged.update(patch)
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return merged
