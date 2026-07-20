"""Codex app-server provider with real agent-message delta streaming."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

MODEL = "gpt-5.5"
REASONING_EFFORT = "medium"


def _base_cmd() -> list[str] | None:
    override = os.environ.get("KAIROS_CODEX_CMD")
    if override:
        return override.split()
    exe = shutil.which("codex")
    return [exe] if exe else None


def _send(proc: subprocess.Popen, message: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def chat(prompt: str, session_ref: str | None = None,
         cfg: dict | None = None) -> Iterator[dict]:
    base = _base_cmd()
    if base is None:
        yield {"type": "error", "error": "codex CLI not found in PATH"}
        return

    config = cfg or {}
    sandbox = config.get("codex_sandbox", "read-only")
    ws = config.get("workspace_dir")
    cwd = str(Path(ws).expanduser().resolve()) if ws else str(Path.cwd().resolve())
    cmd = base + ["app-server"]
    popen_kwargs = {
        "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE, "encoding": "utf-8",
        "errors": "replace", "cwd": cwd,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        yield {"type": "error", "error": f"spawn failed: {exc}"}
        return

    final_parts: list[str] = []
    log_parts: list[str] = []
    phase_by_item: dict[str, str] = {}
    streamed_items: set[str] = set()
    thread_id: str | None = None
    turn_id: str | None = None
    turn_started = False
    try:
        _send(proc, {"method": "initialize", "id": 0, "params": {
            "clientInfo": {"name": "kairos_studio", "title": "Kairos Studio",
                           "version": "0.1.0"}}})
        _send(proc, {"method": "initialized", "params": {}})
        thread_method = "thread/resume" if session_ref else "thread/start"
        thread_params = {"model": MODEL, "cwd": cwd, "sandbox": sandbox,
                         "approvalPolicy": "never"}
        if session_ref:
            thread_params["threadId"] = session_ref
        _send(proc, {"method": thread_method, "id": 1, "params": thread_params})

        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 1:
                if msg.get("error"):
                    yield {"type": "error", "error": f"codex thread failed: {msg['error']}"}
                    return
                thread_id = ((msg.get("result") or {}).get("thread") or {}).get("id") or session_ref
                if not thread_id:
                    yield {"type": "error", "error": "codex returned no thread id"}
                    return
                _send(proc, {"method": "turn/start", "id": 2, "params": {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
                    "model": MODEL, "effort": REASONING_EFFORT, "cwd": cwd}})
                turn_started = True
                continue
            if msg.get("id") == 2:
                if msg.get("error"):
                    yield {"type": "error", "error": f"codex turn failed: {msg['error']}"}
                    return
                turn_id = ((msg.get("result") or {}).get("turn") or {}).get("id")
                continue

            method = msg.get("method")
            params = msg.get("params") or {}
            event_thread_id = params.get("threadId")
            event_turn_id = params.get("turnId") or (params.get("turn") or {}).get("id")
            # app-server multiplexes parent and subagent notifications on the same
            # stdout stream. Only the root turn belongs in this chat response.
            if event_thread_id and event_thread_id != thread_id:
                continue
            if turn_id and event_turn_id and event_turn_id != turn_id:
                continue
            if method == "item/started":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("id"):
                    phase_by_item[item["id"]] = item.get("phase") or "commentary"
            elif method == "item/agentMessage/delta":
                delta = params.get("delta")
                if delta:
                    item_id = params.get("itemId") or ""
                    streamed_items.add(item_id)
                    if phase_by_item.get(item_id) == "final_answer":
                        final_parts.append(delta)
                        yield {"type": "delta", "text": delta}
                    else:
                        log_parts.append(delta)
                        yield {"type": "progress", "text": delta}
            elif method == "item/completed":
                item = params.get("item") or {}
                item_id = item.get("id") or ""
                if item.get("type") == "agentMessage":
                    phase = item.get("phase") or phase_by_item.get(item_id) or "commentary"
                    phase_by_item[item_id] = phase
                    item_text = item.get("text") or ""
                    if item_text and item_id not in streamed_items:
                        if phase == "final_answer":
                            final_parts.append(item_text)
                            yield {"type": "delta", "text": item_text}
                        else:
                            log_parts.append(item_text)
                            yield {"type": "progress", "text": item_text}
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if turn.get("status") != "completed":
                    yield {"type": "error",
                           "error": f"codex turn ended: {turn.get('error') or turn.get('status')}"}
                    return
                break

        if not turn_started:
            err = (proc.stderr.read() if proc.stderr else "").strip()
            yield {"type": "error", "error": f"codex app-server ended before turn: {err[:500]}"}
        elif not final_parts:
            err = (proc.stderr.read() if proc.stderr else "").strip()
            yield {"type": "error", "error": f"codex ended without final answer: {err[:500]}"}
        else:
            yield {"type": "done", "text": "".join(final_parts),
                   "log": "".join(log_parts),
                   "session_ref": thread_id, "model": MODEL}
    except (BrokenPipeError, OSError) as exc:
        yield {"type": "error", "error": f"codex app-server failed: {exc}"}
    finally:
        _stop(proc)
