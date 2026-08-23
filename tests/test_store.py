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


def test_record_injected_refs_dedups(store):
    sid = store.create_session("s")
    mid = store.add_message(sid, "assistant", [{"type": "text", "text": "답변"}])

    n = store.record_injected_refs(mid, ["43:3:16", "43:3:16", "45:8:1", ""])

    assert n == 2  # 중복과 빈 문자열은 버린다
    assert store.reference_feedback_weights() == {}  # 평가가 없으면 가중도 없다


def test_reference_feedback_weights_counts_up_and_down(store):
    sid = store.create_session("s")
    liked = store.add_message(sid, "assistant", [{"type": "text", "text": "좋은 답변"}])
    disliked = store.add_message(sid, "assistant", [{"type": "text", "text": "나쁜 답변"}])
    store.record_injected_refs(liked, ["49:2:8", "45:3:24"])
    store.record_injected_refs(disliked, ["45:3:24"])
    store.add_feedback(liked, "up")
    store.add_feedback(disliked, "down")
    store.add_feedback(disliked, "correction", "이렇게 고쳐")  # 집계 대상 아님

    weights = store.reference_feedback_weights()

    assert weights["49:2:8"] == {"up": 1, "down": 0}
    # 같은 구절이 양쪽에 주입됐으면 둘 다 센다
    assert weights["45:3:24"] == {"up": 1, "down": 1}


def test_reference_feedback_weights_ignores_unrated(store):
    sid = store.create_session("s")
    rated = store.add_message(sid, "assistant", [{"type": "text", "text": "a"}])
    unrated = store.add_message(sid, "assistant", [{"type": "text", "text": "b"}])
    store.record_injected_refs(rated, ["1:1:1"])
    store.record_injected_refs(unrated, ["2:2:2"])
    store.add_feedback(rated, "up")

    assert set(store.reference_feedback_weights()) == {"1:1:1"}


def test_delete_session_clears_injected_refs(store):
    sid = store.create_session("s")
    mid = store.add_message(sid, "assistant", [{"type": "text", "text": "답변"}])
    store.record_injected_refs(mid, ["43:3:16"])
    store.add_feedback(mid, "up")

    assert store.delete_session(sid) is True

    assert store.reference_feedback_weights() == {}
    orphans = store._conn().execute(
        "SELECT COUNT(*) AS n FROM injected_refs").fetchone()["n"]
    assert orphans == 0
