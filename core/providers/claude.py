"""claude CLI subprocess provider. API 직접 호출 금지 — 구독 자원만 (스펙)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator


# 워크스페이스의 읽기 전용 준비 스크립트만 사전 허용한다. 와일드카드는 인자에만
# 걸리므로 목록 밖 명령(rm, git push 등)은 여전히 권한 프롬프트/거부 대상이다.
_ALLOWED_TOOLS = [
    "Bash(py -3 tools/bible_lookup.py:*)",
    "Bash(python tools/bible_lookup.py:*)",
    "Bash(py -3 skills/shared/scripts/verify_sermon.py:*)",
    "Bash(python skills/shared/scripts/verify_sermon.py:*)",
    "Bash(py -3 skills/shared/scripts/sermon_fingerprint.py:*)",
    "Bash(python skills/shared/scripts/sermon_fingerprint.py:*)",
]


def _base_cmd() -> list[str] | None:
    override = os.environ.get("KAIROS_CLAUDE_CMD")
    if override:
        return override.split()
    exe = shutil.which("claude")  # Windows에서는 claude.cmd도 해석됨
    return [exe] if exe else None


def chat(prompt: str, session_ref: str | None = None,
         cfg: dict | None = None) -> Iterator[dict]:
    base = _base_cmd()
    if base is None:
        yield {"type": "error", "error": "claude CLI not found in PATH"}
        return
    mode = (cfg or {}).get("claude_permission_mode", "default")
    cmd = base + [
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--model", "claude-opus-4-8",
        "--include-partial-messages",
        "--permission-mode", mode,  # 안전: 비대화 모드에서 위험 툴 거부
    ]
    # 헤드리스에서는 권한 프롬프트에 답할 수 없어 워크스페이스 도구 실행이
    # 막힌다. 설교 준비에 필요한 읽기 전용 스크립트만 사전 허용한다
    # (임의 셸 명령은 여전히 거부 — 목록에 있는 스크립트로 한정).
    for spec in _ALLOWED_TOOLS:
        cmd += ["--allowedTools", spec]
    if session_ref:
        cmd += ["--resume", session_ref]
    ws = (cfg or {}).get("workspace_dir")
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,  # 사이드카 watchdog stdin 파이프 상속 차단
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "encoding": "utf-8",
        "errors": "replace",  # Windows cp949 함정 방지
    }
    if ws:
        popen_kwargs["cwd"] = str(Path(ws).expanduser())
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
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
            # result가 최종 이벤트다. Windows 실측: CLI가 result 후에도
            # 종료하지 않고 머무는 경우가 있어 EOF를 기다리면 영구 행 —
            # 즉시 루프를 끊고 아래에서 프로세스를 정리한다.
            break
    if not got_result:
        code = proc.wait()
        err = (proc.stderr.read() if proc.stderr else "").strip()
        yield {"type": "error",
               "error": f"claude exited {code} without result: {err[:500]}"}
        return
    try:
        proc.wait(timeout=3)  # 자연 종료 유예
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    yield {"type": "done", "text": final_text,
           "session_ref": session_id, "model": model}
