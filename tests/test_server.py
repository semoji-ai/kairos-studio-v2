import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core.server import make_server
from core.store import Store

FAKES = Path(__file__).parent / "fakes"
TOKEN = "test-token"


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKES/'fake_claude.py'}")
    monkeypatch.setenv("KAIROS_CODEX_CMD", f"{sys.executable} {FAKES/'fake_codex.py'}")
    store = Store(tmp_path / "t.db")
    server = make_server("127.0.0.1", 0, TOKEN, store)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", store
    server.shutdown()


def _req(url, path, body=None, token=TOKEN):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url + path, data=data, method="POST" if data else "GET")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(r)


def _sse_events(resp):
    events = []
    for raw in resp:
        line = raw.decode("utf-8").strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_health_needs_no_auth(srv):
    url, _ = srv
    assert json.load(_req(url, "/health", token=None))["ok"] is True


def test_auth_required_elsewhere(srv):
    url, _ = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/sessions", token=None)
    assert e.value.code == 401


def test_chat_streams_and_persists(srv):
    url, store = srv
    resp = _req(url, "/chat", {"text": "안녕"})
    assert resp.headers["Content-Type"].startswith("text/event-stream")
    ev = _sse_events(resp)
    deltas = [e["text"] for e in ev if e["type"] == "delta"]
    done = ev[-1]
    assert deltas == ["안녕", "하세요"]
    assert done["type"] == "done" and done["provider"] == "claude"
    msgs = store.list_messages(done["session_id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"][0] == {"type": "text", "text": "안녕하세요"}


def test_chat_routes_code_to_codex(srv):
    url, _ = srv
    ev = _sse_events(_req(url, "/chat", {"text": "core/server.py 고쳐줘"}))
    assert ev[-1]["provider"] == "codex"


def test_chat_resumes_same_provider(srv):
    url, store = srv
    first = _sse_events(_req(url, "/chat", {"text": "안녕"}))[-1]
    second = _sse_events(_req(url, "/chat",
                              {"text": "이어서 말해줘", "session_id": first["session_id"]}))[-1]
    msgs = store.list_messages(first["session_id"])
    # fake_claude는 --resume이면 [resumed] 마커를 붙인다
    assert msgs[-1]["content"][0]["text"].startswith("[resumed]")


def test_feedback_roundtrip(srv):
    url, store = srv
    done = _sse_events(_req(url, "/chat", {"text": "안녕"}))[-1]
    r = _req(url, "/feedback", {"message_id": done["message_id"], "kind": "up"})
    assert json.load(r)["id"] > 0
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/feedback", {"message_id": done["message_id"], "kind": "meh"})
    assert e.value.code == 400


def test_sessions_and_messages_endpoints(srv):
    url, _ = srv
    done = _sse_events(_req(url, "/chat", {"text": "제목이 될 첫 문장"}))[-1]
    sessions = json.load(_req(url, "/sessions"))["sessions"]
    assert sessions[0]["id"] == done["session_id"]
    msgs = json.load(_req(url, f"/messages?session_id={done['session_id']}"))["messages"]
    assert len(msgs) == 2
