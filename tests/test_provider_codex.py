import io
import json
import subprocess
import sys
from pathlib import Path

FAKE = Path(__file__).parent / "fakes" / "fake_codex.py"


def _events(monkeypatch, prompt, session_ref=None, cfg=None):
    monkeypatch.setenv("KAIROS_CODEX_CMD", f"{sys.executable} {FAKE}")
    from core.providers import codex
    return list(codex.chat(prompt, session_ref=session_ref, cfg=cfg))


def test_streams_deltas_then_done(monkeypatch):
    ev = _events(monkeypatch, "hi")
    progress = [e["text"] for e in ev if e["type"] == "progress"]
    deltas = [e["text"] for e in ev if e["type"] == "delta"]
    assert progress == ["checking sources"]
    assert len(deltas) == 2
    assert ev[-1]["type"] == "done"
    assert ev[-1]["text"] == "".join(deltas)
    assert ev[-1]["log"] == "".join(progress)
    assert ev[-1]["session_ref"] == "th-123"


def test_resume(monkeypatch):
    ev = _events(monkeypatch, "continue", session_ref="th-123")
    assert ev[-1]["text"].startswith("[resumed]")


def test_registry():
    from core import providers
    import pytest
    assert providers.get("claude").__name__.endswith("claude")
    assert providers.get("codex").__name__.endswith("codex")
    with pytest.raises(KeyError):
        providers.get("gpt")


def test_app_server_params_and_windows_hidden_window(monkeypatch):
    from core.providers import codex
    captured = {}

    class FakeProc:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(
                '{"id":0,"result":{}}\n'
                '{"id":1,"result":{"thread":{"id":"t"}}}\n'
                '{"id":2,"result":{"turn":{"id":"u"}}}\n'
                '{"method":"item/started","params":{"item":{"id":"i","type":"agentMessage","phase":"final_answer"}}}\n'
                '{"method":"item/agentMessage/delta","params":{"itemId":"i","delta":"ok"}}\n'
                '{"method":"turn/completed","params":{"turn":{"status":"completed"}}}\n')
            self.stderr = io.StringIO("")
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    proc = FakeProc()

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return proc

    monkeypatch.setattr(codex, "_base_cmd", lambda: ["codex"])
    monkeypatch.setattr(codex.subprocess, "Popen", fake_popen)
    done = list(codex.chat("hi", cfg={"codex_sandbox": "workspace-write"}))[-1]
    assert done["type"] == "done"
    assert captured["cmd"] == ["codex", "app-server"]
    assert captured["kwargs"]["stdin"] is subprocess.PIPE
    if codex.os.name == "nt":
        assert captured["kwargs"]["creationflags"] == subprocess.CREATE_NO_WINDOW

    sent = [json.loads(line) for line in proc.stdin.getvalue().splitlines()]
    thread = next(m for m in sent if m.get("id") == 1)
    turn = next(m for m in sent if m.get("id") == 2)
    assert thread["params"]["sandbox"] == "workspace-write"
    assert thread["params"]["model"] == "gpt-5.5"
    assert thread["params"]["approvalPolicy"] == "never"
    assert turn["params"]["model"] == "gpt-5.5"
    assert turn["params"]["effort"] == "medium"
