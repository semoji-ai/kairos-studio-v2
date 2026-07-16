import sys
from pathlib import Path
import json as _json

FAKE = Path(__file__).parent / "fakes" / "fake_claude.py"
FAKE_ARGV = Path(__file__).parent / "fakes" / "fake_argv_dump.py"


def _events(monkeypatch, prompt, session_ref=None, cfg=None):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE}")
    from core.providers import claude
    return list(claude.chat(prompt, session_ref=session_ref, cfg=cfg))


def test_streams_deltas_then_done(monkeypatch):
    ev = _events(monkeypatch, "인사해줘")
    assert [e["text"] for e in ev if e["type"] == "delta"] == ["안녕", "하세요"]
    done = ev[-1]
    assert done["type"] == "done"
    assert done["text"] == "안녕하세요"
    assert done["session_ref"] == "sess-abc"
    assert done["model"] == "claude-fable-5"


def test_resume_passes_session_ref(monkeypatch):
    ev = _events(monkeypatch, "이어서", session_ref="sess-abc")
    assert ev[-1]["text"].startswith("[resumed]")


def test_missing_cli_yields_error(monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", "/nonexistent/claude-xyz")
    from core.providers import claude
    ev = list(claude.chat("hi"))
    assert ev[-1]["type"] == "error"


def test_permission_mode_from_cfg(monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE_ARGV}")
    from core.providers import claude
    done = list(claude.chat("hi", cfg={"claude_permission_mode": "acceptEdits"}))[-1]
    argv = _json.loads(done["text"])
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits"


def test_permission_mode_default_without_cfg(monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE_ARGV}")
    from core.providers import claude
    done = list(claude.chat("hi"))[-1]
    argv = _json.loads(done["text"])
    assert argv[argv.index("--permission-mode") + 1] == "default"
