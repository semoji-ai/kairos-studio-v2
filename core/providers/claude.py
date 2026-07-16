"""claude CLI subprocess provider. API 직접 호출 금지 — 구독 자원만 (스펙)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Iterator


def _base_cmd() -> list[str] | None:
    override = os.environ.get("KAIROS_CLAUDE_CMD")
    if override:
        return override.split()
    exe = shutil.which("claude")  # Windows에서는 claude.cmd도 해석됨
    return [exe] if exe else None


def chat(prompt: str, session_ref: str | None = None) -> Iterator[dict]:
    base = _base_cmd()
    if base is None:
        yield {"type": "error", "error": "claude CLI not found in PATH"}
        return
    cmd = base + [
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--permission-mode", "default",  # 안전: 비대화 모드에서 위험 툴 거부
    ]
    if session_ref:
        cmd += ["--resume", session_ref]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",  # Windows cp949 함정 방지
        )
    except OSError as exc:
        yield {"type": "error", "error": f"spawn failed: {exc}"}
        return

    final_text, session_id, model, got_result = "", None, None, False
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # 비-JSON 로그 라인은 무시
        t = msg.get("type")
        if t == "system":
            session_id = msg.get("session_id", session_id)
            model = msg.get("model", model)
        elif t == "stream_event":
            delta = (msg.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                yield {"type": "delta", "text": delta["text"]}
        elif t == "result":
            final_text = msg.get("result") or final_text
            session_id = msg.get("session_id", session_id)
            got_result = True
    code = proc.wait()
    if not got_result:
        err = (proc.stderr.read() if proc.stderr else "").strip()
        yield {"type": "error",
               "error": f"claude exited {code} without result: {err[:500]}"}
        return
    yield {"type": "done", "text": final_text,
           "session_ref": session_id, "model": model}
