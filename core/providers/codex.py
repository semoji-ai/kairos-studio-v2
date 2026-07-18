"""codex CLI subprocess provider. --sandbox read-only 강제 (스펙: 안전)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator


def _base_cmd() -> list[str] | None:
    override = os.environ.get("KAIROS_CODEX_CMD")
    if override:
        return override.split()
    exe = shutil.which("codex")
    return [exe] if exe else None


def chat(prompt: str, session_ref: str | None = None,
         cfg: dict | None = None) -> Iterator[dict]:
    base = _base_cmd()
    if base is None:
        yield {"type": "error", "error": "codex CLI not found in PATH"}
        return
    sandbox = (cfg or {}).get("codex_sandbox", "read-only")
    cmd = base + ["exec", "--json", "--sandbox", sandbox]
    if session_ref:
        cmd += ["resume", session_ref]
    cmd += [prompt]
    ws = (cfg or {}).get("workspace_dir")
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if ws:
        popen_kwargs["cwd"] = str(Path(ws).expanduser())
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        yield {"type": "error", "error": f"spawn failed: {exc}"}
        return

    text_parts, thread_id = [], None
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = msg.get("type", "")
        if t == "thread.started":
            thread_id = msg.get("thread_id")
        elif t == "item.completed":
            item = msg.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                text_parts.append(item["text"])
                yield {"type": "delta", "text": item["text"]}
    code = proc.wait()
    if not text_parts:
        err = (proc.stderr.read() if proc.stderr else "").strip()
        yield {"type": "error",
               "error": f"codex exited {code} without message: {err[:500]}"}
        return
    yield {"type": "done", "text": "\n".join(text_parts),
           "session_ref": thread_id, "model": "codex"}
