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
