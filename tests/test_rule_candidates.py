import json
import sqlite3

from core.distill import distill
from core.store import Store


def _user(store, text):
    sid = store.create_session("s")
    return store.add_message(sid, "user", [{"type": "text", "text": text}])


def _fake_chat(payload):
    def chat(prompt, session_ref=None, cfg=None):
        chat.prompt = prompt
        yield {"type": "done", "text": json.dumps(payload, ensure_ascii=False)}
    return chat


def test_legacy_db_gets_pending_and_last_message_columns(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE learned_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT NOT NULL,"
        " source TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')));"
        "CREATE TABLE distill_state(id INTEGER PRIMARY KEY CHECK(id=1),"
        " last_feedback_id INTEGER NOT NULL DEFAULT 0);"
        "INSERT INTO learned_rules(rule) VALUES ('기존 규칙');")
    con.commit()
    con.close()
    store = Store(db)
    rules = store.list_rules(active_only=False)
    assert rules[0]["rule"] == "기존 규칙" and rules[0]["pending"] is False
    assert store.count_undistilled_directives() == 0


def test_directive_messages_only_persistent_preferences(tmp_path):
    store = Store(tmp_path / "t.db")
    a = _user(store, "앞으로 서론은 항상 짧게 써 주세요")
    _user(store, "로마서 8장 초안 잡아줘")
    b = _user(store, "예화는 두 개 이상 넣지 말아 주세요")
    got = store.directive_messages()
    assert [m["id"] for m in got] == [a, b]
    assert store.count_undistilled_directives() == 2
    store.mark_directives_distilled(a)
    assert [m["id"] for m in store.directive_messages()] == [b]


def test_distill_saves_conversation_rules_as_pending(tmp_path):
    store = Store(tmp_path / "t.db")
    mid = _user(store, "앞으로 서론은 항상 짧게 써 주세요")
    chat = _fake_chat([{"rule": "서론은 짧게 쓴다", "source_ids": [f"m{mid}"],
                        "from": "conversation"}])
    res = distill(store, chat)
    assert res["candidates"] == ["서론은 짧게 쓴다"] and res["added"] == []
    assert "대화 지시" in chat.prompt and "서론은 항상 짧게" in chat.prompt
    rule = store.list_rules(active_only=False)[0]
    assert rule["pending"] is True and rule["active"] is False
    assert store.list_rules(active_only=True) == []
    store.set_rule_active(rule["id"], True)
    rule = store.list_rules(active_only=False)[0]
    assert rule["pending"] is False and rule["active"] is True
    assert store.count_undistilled_directives() == 0


def test_distill_feedback_rules_stay_active(tmp_path):
    store = Store(tmp_path / "t.db")
    sid = store.create_session("s")
    mid = store.add_message(sid, "assistant", [{"type": "text", "text": "답"}])
    fid = store.add_feedback(mid, "down", "너무 길다")
    res = distill(store, _fake_chat([{"rule": "짧게 답한다", "source_ids": [fid]}]))
    assert res["added"] == ["짧게 답한다"]
    assert store.list_rules(active_only=True)[0]["pending"] is False


def test_distill_nothing_new(tmp_path):
    store = Store(tmp_path / "t.db")
    assert distill(store, _fake_chat([]))["skipped"]
