import sys
from pathlib import Path
import json as _json
import io
import subprocess

FAKE = Path(__file__).parent / "fakes" / "fake_claude.py"
FAKE_ARGV = Path(__file__).parent / "fakes" / "fake_argv_dump.py"
FAKE_CWD = Path(__file__).parent / "fakes" / "fake_cwd_dump.py"


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


def test_model_is_opus_5_5_at_high_effort(monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE_ARGV}")
    from core.providers import claude
    done = list(claude.chat("hi"))[-1]
    argv = _json.loads(done["text"])
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[argv.index("--effort") + 1] == "high"


def test_windows_subprocess_has_no_console_window(monkeypatch):
    from core.providers import claude
    captured = {}

    class FakeProc:
        stdout = io.StringIO(
            '{"type":"result","subtype":"success","result":"ok","session_id":"s"}\n')
        stderr = io.StringIO("")

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(claude, "_base_cmd", lambda: ["claude"])
    monkeypatch.setattr(claude.subprocess, "Popen", fake_popen)
    assert list(claude.chat("hi"))[-1]["type"] == "done"
    if claude.os.name == "nt":
        assert captured["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_workspace_dir_sets_cwd(monkeypatch, tmp_path):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE_CWD}")
    from core.providers import claude
    done = list(claude.chat("hi", cfg={"workspace_dir": str(tmp_path)}))[-1]
    assert Path(done["text"]).resolve() == tmp_path.resolve()


def test_no_workspace_dir_keeps_default_cwd(monkeypatch, tmp_path):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE_CWD}")
    from core.providers import claude
    done = list(claude.chat("hi"))[-1]
    assert Path(done["text"]).resolve() != tmp_path.resolve()


def test_scoped_workflow_allowed_tools_from_cfg(monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE_ARGV}")
    from core.providers import claude
    spec = "Bash(C:/Python/python.exe D:/ppt-master/scripts/*:*)"
    done = list(claude.chat("hi", cfg={"claude_allowed_tools": [spec]}))[-1]
    argv = _json.loads(done["text"])
    pairs = list(zip(argv, argv[1:]))
    assert ("--allowedTools", spec) in pairs
