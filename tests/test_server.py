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


def _req(url, path, body=None, token=TOKEN, method=None):
    data = json.dumps(body).encode() if body is not None else None
    m = method or ("POST" if data else "GET")
    r = urllib.request.Request(url + path, data=data, method=m)
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


def test_bad_host_header_rejected(srv):
    url, _ = srv
    r = urllib.request.Request(url + "/health", method="GET")
    r.add_header("Host", "evil.example")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(r)
    assert e.value.code == 403


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


def test_codex_progress_is_collapsible_log_not_answer(srv):
    url, store = srv
    ev = _sse_events(_req(url, "/chat", {"text": "@codex 테스트"}))
    progress = [e["text"] for e in ev if e["type"] == "progress"]
    deltas = [e["text"] for e in ev if e["type"] == "delta"]
    done = ev[-1]
    assert progress == ["checking sources"]
    msgs = store.list_messages(done["session_id"])
    content = msgs[-1]["content"]
    assert next(p["text"] for p in content if p["type"] == "text") == "".join(deltas)
    assert next(p["text"] for p in content if p["type"] == "log") == "".join(progress)


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


def test_static_serves_index_with_token(srv, tmp_path, monkeypatch):
    url, _ = srv
    # KAIROS_STATIC_DIR을 가짜 dist로
    (tmp_path / "index.html").write_text("<html><head></head><body>hi</body></html>")
    monkeypatch.setenv("KAIROS_STATIC_DIR", str(tmp_path))
    html = urllib.request.urlopen(url + "/").read().decode()
    assert "window.__KAIROS__" in html and TOKEN in html


@pytest.fixture(autouse=True)
def _cfg_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))


def test_settings_roundtrip(srv):
    url, _ = srv
    s = json.load(_req(url, "/settings"))
    assert s["default_provider"] == "claude"
    body = {"default_provider": "codex", "routing_rules_enabled": False}
    s2 = json.load(_req(url, "/settings", body, method="PUT"))
    assert s2["default_provider"] == "codex"
    # 설정이 라우팅에 반영: 일반 텍스트가 codex로
    ev = _sse_events(_req(url, "/chat", {"text": "안녕 잘 지냈어?"}))
    assert ev[-1]["provider"] == "codex"


def test_settings_reject_bad_value(srv):
    url, _ = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/settings", {"codex_sandbox": "danger-full-access"}, method="PUT")
    assert e.value.code == 400
    assert json.load(_req(url, "/settings"))["codex_sandbox"] == "read-only"


def test_settings_combined_invalid_patch_has_no_side_effects(srv, tmp_path):
    url, _ = srv
    target = tmp_path / "should_not_exist"
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/settings",
             {"data_dir": str(target), "codex_sandbox": "danger-full-access"},
             method="PUT")
    assert e.value.code == 400
    assert not target.exists()          # mkdir/copy가 실행되지 않았어야 한다
    assert json.load(_req(url, "/settings"))["codex_sandbox"] == "read-only"


def test_data_dir_change_copies_db_and_reopens(srv, tmp_path):
    url, store = srv
    done = _sse_events(_req(url, "/chat", {"text": "첫 대화"}))[-1]
    new_dir = tmp_path / "moved"
    json.load(_req(url, "/settings", {"data_dir": str(new_dir)}, method="PUT"))
    assert (new_dir / "kairos.db").exists()          # 복사됨
    msgs = json.load(_req(url, f"/messages?session_id={done['session_id']}"))["messages"]
    assert len(msgs) == 2                             # 새 store에서 과거 대화 조회됨


def test_storage_info(srv):
    url, _ = srv
    info = json.load(_req(url, "/storage"))
    assert "data_dir" in info and info["db_bytes"] >= 0 and info["fallback"] is False


def test_cli_status_with_fakes(srv):
    url, _ = srv
    st = json.load(_req(url, "/cli/status"))
    assert st["claude"]["installed"] is True   # KAIROS_CLAUDE_CMD 세팅됨
    assert st["codex"]["installed"] is True
    assert st["claude"]["login_hint"]


def test_put_data_dir_copies_from_live_store_not_settings(srv, tmp_path, monkeypatch):
    # env KAIROS_DATA_DIR가 설정과 다른 곳을 가리키는 Tauri 시나리오:
    # 복사 원본은 설정값이 아니라 '살아있는 store'의 DB여야 한다
    url, store = srv
    done = _sse_events(_req(url, "/chat", {"text": "타우리 대화"}))[-1]
    new_dir = tmp_path / "tauri_moved"
    json.load(_req(url, "/settings", {"data_dir": str(new_dir)}, method="PUT"))
    msgs = json.load(_req(url, f"/messages?session_id={done['session_id']}"))["messages"]
    assert len(msgs) == 2  # 이관 후에도 기존 대화 보임 = 올바른 원본에서 복사됨


def test_put_data_dir_mkdir_failure_rolls_back(srv, tmp_path, monkeypatch):
    url, _ = srv
    before = json.load(_req(url, "/settings"))["data_dir"]
    # 파일을 만들어 그 '아래' 경로를 지정 → mkdir 실패 → 400
    blocker = tmp_path / "blocker"; blocker.write_text("x")
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/settings", {"data_dir": str(blocker / "sub")}, method="PUT")
    assert e.value.code == 400
    assert json.load(_req(url, "/settings"))["data_dir"] == before


def test_put_data_dir_store_open_failure_rolls_back(srv, tmp_path, monkeypatch):
    import core.settings as settings

    url, _ = srv
    before = json.load(_req(url, "/settings"))["data_dir"]
    # target dir이 이미 존재하고, 그 안의 'kairos.db'가 파일이 아니라 디렉토리라서
    # mkdir은 성공하고 copy는 건너뛰지만(target "exists") sqlite3.connect가 실패한다.
    target = tmp_path / "bad_store_target"
    (target / "kairos.db").mkdir(parents=True)
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/settings", {"data_dir": str(target)}, method="PUT")
    assert e.value.code == 400
    assert json.load(_req(url, "/settings"))["data_dir"] == before
    assert "data_dir" not in settings.explicit_keys()


def test_workspace_info_null_by_default(srv):
    url, _ = srv
    info = json.load(_req(url, "/workspace/info"))
    assert info["workspace_dir"] is None and info["skills"] == []


def test_workspace_info_lists_skills(srv, tmp_path):
    url, _ = srv
    ws = tmp_path / "ws"
    (ws / "skills" / "publish-write").mkdir(parents=True)
    (ws / "skills" / "publish-write" / "SKILL.md").write_text("x")
    (ws / ".claude" / "skills" / "local-skill").mkdir(parents=True)
    (ws / "CLAUDE.md").write_text("x")
    json.load(_req(url, "/settings", {"workspace_dir": str(ws)}, method="PUT"))
    info = json.load(_req(url, "/workspace/info"))
    assert info["exists"] is True and info["has_claude_md"] is True
    assert "publish-write" in info["skills"] and "local-skill" in info["skills"]


def test_workspace_dir_bad_path_400(srv, tmp_path):
    url, _ = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/settings", {"workspace_dir": str(tmp_path / "nope")}, method="PUT")
    assert e.value.code == 400


def test_chat_injects_recall_from_past_session(srv):
    url, store = srv
    done1 = _sse_events(_req(url, "/chat", {"text": "설교 준비를 도와줘"}))[-1]
    ev = _sse_events(_req(url, "/chat", {"text": "설교 이어서 하자"}))  # 새 세션
    done2 = ev[-1]
    assert done2["recalled"] >= 1
    # fake_claude는 받은 prompt를 그대로 알 수 없으므로 fake_argv_dump로 재검:
    # (아래 별도 테스트에서 argv 캡처로 주입 실증)


def test_injection_reaches_provider_but_not_db(srv, tmp_path, monkeypatch):
    url, store = srv
    _sse_events(_req(url, "/chat", {"text": "레오파드 렌더 방법 알려줘"}))
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_argv_dump.py'}")
    done = _sse_events(_req(url, "/chat", {"text": "@claude 레오파드 얘기 다시"}))[-1]
    msgs = json.load(_req(url, f"/messages?session_id={done['session_id']}"))["messages"]
    # DB의 user 원문에는 주입 블록 없음
    assert "[과거 대화 참고" not in msgs[0]["content"][0]["text"]
    # provider가 받은 argv(-p 값)에는 주입 블록 있음
    argv_text = msgs[1]["content"][0]["text"]
    assert "[과거 대화 참고" in argv_text and "레오파드 얘기 다시" in argv_text


def test_recall_toggle_off(srv):
    url, _ = srv
    _sse_events(_req(url, "/chat", {"text": "설교 준비를 도와줘"}))
    json.load(_req(url, "/settings", {"learning_recall_enabled": False}, method="PUT"))
    done = _sse_events(_req(url, "/chat", {"text": "설교 이어서"}))[-1]
    assert done["recalled"] == 0


def test_build_prompt_cap_ignores_user_text_length():
    from core.server import build_prompt
    rec = {"snippets": [{"q_text": "질문", "a_text": "답변", "date": "2026-07-01", "score": 1.0}],
           "avoid": [], "corrections": []}
    long_text = "가" * 3000
    prompt, n = build_prompt(long_text, rec)
    assert n == 1  # 사용자 텍스트가 길어도 스니펫이 잘리지 않는다
    assert "[과거 대화 참고" in prompt and prompt.endswith(long_text)


def test_distill_route_adds_rule(srv, monkeypatch):
    url, store = srv
    done = _sse_events(_req(url, "/chat", {"text": "안녕"}))[-1]
    _req(url, "/feedback", {"message_id": done["message_id"], "kind": "correction",
                             "payload": "가운뎃점 대신 쉼표"})
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_distill_claude.py'}")
    result = json.load(_req(url, "/distill", {}))
    assert result["added"] == ["가운뎃점 대신 쉼표를 쓴다"]
    rules = json.load(_req(url, "/rules"))["rules"]
    assert len(rules) == 1 and rules[0]["rule"] == "가운뎃점 대신 쉼표를 쓴다"


def test_chat_injects_learned_rules(srv, monkeypatch):
    url, store = srv
    done = _sse_events(_req(url, "/chat", {"text": "안녕"}))[-1]
    _req(url, "/feedback", {"message_id": done["message_id"], "kind": "correction",
                             "payload": "가운뎃점 대신 쉼표"})
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_distill_claude.py'}")
    json.load(_req(url, "/distill", {}))
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_argv_dump.py'}")
    done2 = _sse_events(_req(url, "/chat", {"text": "@claude 다시 물어봄"}))[-1]
    msgs = json.load(_req(url, f"/messages?session_id={done2['session_id']}"))["messages"]
    argv_text = msgs[-1]["content"][0]["text"]
    assert "[학습된 규칙" in argv_text


def test_rules_deactivate_excludes_from_injection(srv, monkeypatch):
    url, store = srv
    done = _sse_events(_req(url, "/chat", {"text": "안녕"}))[-1]
    _req(url, "/feedback", {"message_id": done["message_id"], "kind": "correction",
                             "payload": "가운뎃점 대신 쉼표"})
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_distill_claude.py'}")
    json.load(_req(url, "/distill", {}))
    rule_id = json.load(_req(url, "/rules"))["rules"][0]["id"]
    _req(url, "/rules", {"id": rule_id, "active": False})
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_argv_dump.py'}")
    done2 = _sse_events(_req(url, "/chat", {"text": "@claude 다시 물어봄"}))[-1]
    msgs = json.load(_req(url, f"/messages?session_id={done2['session_id']}"))["messages"]
    argv_text = msgs[-1]["content"][0]["text"]
    assert "[학습된 규칙" not in argv_text


def test_chat_auto_triggers_distill_at_threshold(srv, monkeypatch):
    import time
    import core.server as server_mod
    monkeypatch.setattr(server_mod, "DISTILL_THRESHOLD", 2)
    url, store = srv
    d1 = _sse_events(_req(url, "/chat", {"text": "안녕"}))[-1]
    _req(url, "/feedback", {"message_id": d1["message_id"], "kind": "correction",
                             "payload": "교정1"})
    d2 = _sse_events(_req(url, "/chat", {"text": "안녕2"}))[-1]
    _req(url, "/feedback", {"message_id": d2["message_id"], "kind": "correction",
                             "payload": "교정2"})
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_distill_claude.py'}")
    _sse_events(_req(url, "/chat", {"text": "트리거"}))
    deadline = time.time() + 3
    while time.time() < deadline and store.count_undistilled_feedback() > 0:
        time.sleep(0.05)
    assert store.count_undistilled_feedback() == 0


def test_build_prompt_trims_oversized_block():
    from core.server import build_prompt
    snips = [{"q_text": "질" * 400, "a_text": "답" * 400, "date": "2026-07-01", "score": 1.0}
             for _ in range(5)]
    rec = {"snippets": snips, "avoid": [], "corrections": []}
    prompt, n = build_prompt("짧은 질문", rec)
    assert n < 5  # 블록이 캡을 넘으면 스니펫이 줄어든다


def test_chat_persists_and_serves_artifact(srv, monkeypatch, tmp_path):
    url, store = srv
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\nfakebytes")
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_echo_claude.py'}")
    done = _sse_events(_req(url, "/chat", {"text": f"@claude 결과: {img}"}))[-1]
    assert done["artifacts"] == 1
    msgs = json.load(_req(url, f"/messages?session_id={done['session_id']}"))["messages"]
    parts = msgs[-1]["content"]
    image_parts = [p for p in parts if p.get("type") == "image"]
    assert len(image_parts) == 1
    artifact_path = image_parts[0]["artifact"]

    resp = _req(url, f"/artifacts/{artifact_path}", token=None)
    assert resp.status == 200
    assert resp.read() == img.read_bytes()


def test_artifact_path_escape_is_rejected(srv):
    url, _ = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _req(url, "/artifacts/../../etc/passwd", token=None)
    assert e.value.code == 404


def test_artifact_served_after_source_deleted(srv, monkeypatch, tmp_path):
    url, store = srv
    img = tmp_path / "temp.png"
    img.write_bytes(b"\x89PNGdeleteme")
    original_bytes = img.read_bytes()
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_echo_claude.py'}")
    done = _sse_events(_req(url, "/chat", {"text": f"@claude 결과: {img}"}))[-1]
    assert done["artifacts"] == 1
    msgs = json.load(_req(url, f"/messages?session_id={done['session_id']}"))["messages"]
    artifact_path = next(p for p in msgs[-1]["content"] if p.get("type") == "image")["artifact"]

    img.unlink()  # 원본 삭제

    resp = _req(url, f"/artifacts/{artifact_path}", token=None)
    assert resp.status == 200
    assert resp.read() == original_bytes


def test_setup_status_shape(srv):
    url, _ = srv
    st = json.load(_req(url, "/setup/status"))
    assert st["cli"]["claude"]["installed"] is True
    assert st["all_ready"] is True   # fake claude: installed + authed(returncode 0)
    assert "workspace_dir" in st and "workspace_ready" in st


def test_setup_install_cli_with_mock_cmd(srv, monkeypatch):
    url, _ = srv
    monkeypatch.setenv("KAIROS_CLI_INSTALL_CMD", f"{sys.executable} -c print('ok')")
    resp = json.load(_req(url, "/setup/install-cli", {}))
    assert resp["ok"] is True


def test_setup_install_workspace_extracts_zip(srv, tmp_path, monkeypatch):
    url, _ = srv
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    import zipfile
    with zipfile.ZipFile(bundle / "publish_agent.zip", "w") as zf:
        zf.writestr("skills/publish-write/SKILL.md", "# skill")
    monkeypatch.setenv("KAIROS_BUNDLE_DIR", str(bundle))
    docs = tmp_path / "home" / "Documents"
    docs.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    resp = json.load(_req(url, "/setup/install-workspace", {}))
    assert resp["workspace_dir"] == str(docs / "publish-agent")
    assert resp["skills"] >= 1
