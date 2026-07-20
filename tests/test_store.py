import pytest

from core.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "kairos.db")


def test_session_roundtrip(store):
    sid = store.create_session("첫 세션")
    sessions = store.list_sessions()
    assert sessions[0]["id"] == sid
    assert sessions[0]["title"] == "첫 세션"


def test_message_roundtrip_preserves_content_json(store):
    sid = store.create_session("s")
    mid = store.add_message(sid, "user", [{"type": "text", "text": "안녕"}])
    store.add_message(sid, "assistant", [{"type": "text", "text": "네!"}],
                      provider="claude", model="claude-opus")
    msgs = store.list_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["id"] == mid
    assert msgs[0]["content"] == [{"type": "text", "text": "안녕"}]
    assert msgs[1]["provider"] == "claude"


def test_feedback_kinds(store):
    sid = store.create_session("s")
    mid = store.add_message(sid, "assistant", [{"type": "text", "text": "x"}])
    store.add_feedback(mid, "up")
    store.add_feedback(mid, "correction", "이렇게 고쳐")
    with pytest.raises(ValueError):
        store.add_feedback(mid, "meh")


def test_sessions_isolated(store):
    a = store.create_session("a")
    b = store.create_session("b")
    store.add_message(a, "user", [{"type": "text", "text": "1"}])
    assert store.list_messages(b) == []


def test_delete_session_removes_messages_feedback_fts(store):
    sid = store.create_session("삭제 대상")
    mid = store.add_message(sid, "user", [{"type": "text", "text": "안녕 세상"}])
    store.add_message(sid, "assistant", [{"type": "text", "text": "응답"}])
    store.add_feedback(mid, "up")
    keep = store.create_session("보존 세션")
    keep_mid = store.add_message(keep, "user", [{"type": "text", "text": "남는다"}])

    assert store.delete_session(sid) is True
    assert [s["id"] for s in store.list_sessions()] == [keep]
    assert store.list_messages(sid) == []
    assert store.feedback_for_message(mid) == []
    with store._conn() as c:
        rows = c.execute("SELECT session_id FROM messages_fts").fetchall()
    assert {r["session_id"] for r in rows} == {keep}
    assert store.list_messages(keep)[0]["id"] == keep_mid


def test_delete_session_missing_returns_false(store):
    assert store.delete_session(9999) is False
