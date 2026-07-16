"""규칙 기반 라우터. LLM-판단 라우팅은 P1 범위 밖 (스펙 참조)."""
from __future__ import annotations

import re

_MENTION = re.compile(r"^\s*@(claude|codex)\b[,:]?\s*", re.IGNORECASE)

# 코드·파일·터미널 신호 → codex
_CODE_SIGNALS = [
    re.compile(r"```"),                                  # 코드펜스
    re.compile(r"\b[\w./-]+\.(py|ts|tsx|js|rs|json|toml|yml|yaml|sh|sql|css|html)\b"),
    re.compile(r"\b(git|npm|pnpm|pip|cargo|pytest|docker|grep|rsync)\b", re.IGNORECASE),
    re.compile(r"(터미널|쉘|셸|커밋|리팩터|리팩토링|디버그|스택트레이스|컴파일)"),
    re.compile(r"\b(Traceback|SyntaxError|TypeError|panic!|segfault)\b"),
]


def route(text: str, cfg: dict | None = None) -> tuple[str, str]:
    m = _MENTION.match(text)
    if m:
        return m.group(1).lower(), text[m.end():]
    default = (cfg or {}).get("default_provider", "claude")
    if cfg is not None and not cfg.get("routing_rules_enabled", True):
        return default, text
    for sig in _CODE_SIGNALS:
        if sig.search(text):
            return "codex", text
    return default, text
