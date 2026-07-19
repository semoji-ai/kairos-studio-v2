import sys
from pathlib import Path

from core.distill import distill
from core.providers import claude as claude_provider
from core.store import Store

FAKES = Path(__file__).parent / "fakes"
FAKE = FAKES / "fake_distill_claude.py"


def _mk_store(tmp_path):
    return Store(tmp_path / "db.sqlite3")


def _seed_correction(store: Store, payload: str = "가운뎃점 대신 쉼표") -> int:
    sid = store.create_session("t")
    store.add_message(sid, "user", [{"type": "text", "text": "질문"}])
    mid = store.add_message(sid, "assistant", [{"type": "text", "text": "답변"}])
    return store.add_feedback(mid, "correction", payload)


def test_distill_adds_rule_from_corrections(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE}")
    store = _mk_store(tmp_path)
    _seed_correction(store)
    _seed_correction(store, "가운뎃점 쓰지 마세요")

    result = distill(store, claude_provider.chat)

    assert result["added"] == ["가운뎃점 대신 쉼표를 쓴다"]
    rules = store.list_rules()
    assert len(rules) == 1
    assert rules[0]["rule"] == "가운뎃점 대신 쉼표를 쓴다"
    assert store.count_undistilled_feedback() == 0


def test_distill_no_feedback_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE}")
    store = _mk_store(tmp_path)

    result = distill(store, claude_provider.chat)

    assert result == {"added": [], "skipped": "no new feedback"}
    assert store.list_rules() == []


def test_distill_parse_failure_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("FAKE_BAD", "1")
    store = _mk_store(tmp_path)
    _seed_correction(store)

    before = store.count_undistilled_feedback()
    result = distill(store, claude_provider.chat)

    assert result["added"] == []
    assert result.get("error") == "parse"
    assert store.list_rules() == []
    assert store.count_undistilled_feedback() == before


def test_set_rule_active_excludes_from_active_only_list(tmp_path):
    store = _mk_store(tmp_path)
    rid = store.add_rule("규칙 A", [1])

    store.set_rule_active(rid, False)

    assert store.list_rules(active_only=True) == []
    all_rules = store.list_rules(active_only=False)
    assert len(all_rules) == 1
    assert all_rules[0]["active"] is False


def test_up_feedback_not_counted_as_undistilled(tmp_path):
    store = _mk_store(tmp_path)
    sid = store.create_session("t")
    mid = store.add_message(sid, "assistant", [{"type": "text", "text": "답변"}])
    store.add_feedback(mid, "up", "")

    assert store.count_undistilled_feedback() == 0
