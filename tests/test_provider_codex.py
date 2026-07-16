import sys
from pathlib import Path
import json as _json

FAKE = Path(__file__).parent / "fakes" / "fake_codex.py"
FAKE_ARGV = Path(__file__).parent / "fakes" / "fake_argv_dump.py"


def _events(monkeypatch, prompt, session_ref=None, cfg=None):
    monkeypatch.setenv("KAIROS_CODEX_CMD", f"{sys.executable} {FAKE}")
    from core.providers import codex
    return list(codex.chat(prompt, session_ref=session_ref, cfg=cfg))


def test_done_carries_text_and_thread(monkeypatch):
    ev = _events(monkeypatch, "파일 봐줘")
    done = ev[-1]
    assert done["type"] == "done"
    assert done["text"] == "코드 확인 완료"
    assert done["session_ref"] == "th-123"


def test_resume(monkeypatch):
    ev = _events(monkeypatch, "이어서", session_ref="th-123")
    assert ev[-1]["text"].startswith("[resumed]")


def test_registry():
    from core import providers
    import pytest
    assert providers.get("claude").__name__.endswith("claude")
    assert providers.get("codex").__name__.endswith("codex")
    with pytest.raises(KeyError):
        providers.get("gpt")


def test_sandbox_from_cfg(monkeypatch):
    monkeypatch.setenv("KAIROS_CODEX_CMD", f"{sys.executable} {FAKE_ARGV}")
    from core.providers import codex
    done = list(codex.chat("hi", cfg={"codex_sandbox": "workspace-write"}))[-1]
    argv = _json.loads(done["text"])
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
