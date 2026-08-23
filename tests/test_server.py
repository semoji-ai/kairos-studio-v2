import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from core.server import _is_routine_disconnect, make_server
from core.store import Store

FAKES = Path(__file__).parent / "fakes"
TOKEN = "test-token"


def test_routine_browser_disconnects_are_quiet():
    assert _is_routine_disconnect(ConnectionResetError(10054, "reset"))
    assert _is_routine_disconnect(BrokenPipeError())
    assert not _is_routine_disconnect(RuntimeError("real failure"))


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


def _multipart_req(url, path, filename, content, fields=None):
    boundary = "----kairos-test-boundary"
    chunks = []
    for key, value in (fields or {}).items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n"
            f"{value}\r\n".encode()
        )
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        + content + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url + path, data=b"".join(chunks), method="POST")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    return urllib.request.urlopen(req)


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
    statuses = [e for e in ev if e["type"] == "status"]
    done = ev[-1]
    assert deltas == ["안녕", "하세요"]
    assert [event["code"] for event in statuses] == [
        "preparing", "checking_context", "planning", "generating", "saving",
    ]
    assert all(re.search(r"[가-힣]", event["label"]) for event in statuses)
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


def test_build_prompt_reports_surviving_bible_refs():
    """블록에 실제로 들어간 성경 자료만 학습 신호로 귀속돼야 한다."""
    from core.server import build_prompt
    refs = [{"reference": f"43:3:{i}", "content": "본문"} for i in range(5)]
    rec = {"snippets": [], "avoid": [], "corrections": [], "bible_refs": refs}

    prompt, _ = build_prompt("짧은 질문", rec)

    used = rec["bible_refs_used"]
    assert [r["reference"] for r in used] == ["43:3:0", "43:3:1", "43:3:2"]
    for ref in used:
        assert ref["reference"] in prompt


def test_build_prompt_reports_no_refs_when_block_empty():
    from core.server import build_prompt
    rec = {"snippets": [], "avoid": [], "corrections": [], "bible_refs": []}

    prompt, n = build_prompt("원문 그대로", rec)

    assert (prompt, n) == ("원문 그대로", 0)
    assert rec["bible_refs_used"] == []


def test_build_prompt_drops_refs_that_budget_trimmed():
    """캡 초과로 잘려나간 구절은 주입된 것으로 기록되지 않는다.

    corrections는 트림 대상이 아니라, 그것만으로 캡을 넘기면 성경 자료는 끝까지
    깎여 나간다. 이때 구절이 주입된 것으로 기록되면 학습 신호가 오염된다.
    """
    from core.server import build_prompt
    refs = [{"reference": f"43:3:{i}", "content": "본문"} for i in range(3)]
    rec = {"snippets": [], "avoid": [], "corrections": ["교" * 1600],
           "bible_refs": refs}

    prompt, _ = build_prompt("짧은 질문", rec)

    assert rec["bible_refs_used"] == []
    for ref in refs:
        assert ref["reference"] not in prompt


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


def test_workspace_file_preview_is_scoped_and_tokenized(srv, monkeypatch, tmp_path):
    url, _ = srv
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    doc = workspace / "draft.md"
    doc.write_text("# preview", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    _req(url, "/settings", {"workspace_dir": str(workspace)}, method="PUT")

    path = urllib.parse.quote(str(doc), safe="")
    response = _req(url, f"/workspace-file?path={path}&token={TOKEN}", token=None)
    assert response.headers["Content-Type"] == "text/markdown"
    assert response.read().decode("utf-8") == "# preview"

    review = workspace / "theology.review.json"
    review.write_text('{"schema":"kairos.theology-review.v1"}', encoding="utf-8")
    review_path = urllib.parse.quote(str(review), safe="")
    response = _req(
        url, f"/workspace-file?path={review_path}&token={TOKEN}", token=None)
    assert response.headers["Content-Type"] == "application/json"
    assert json.load(response)["schema"] == "kairos.theology-review.v1"

    # Markdown 렌더러가 한글 경로를 먼저 인코딩한 경우 URLSearchParams가
    # 퍼센트 기호를 다시 인코딩한다. 서버는 이중 인코딩도 정상화한다.
    encoded_once = urllib.parse.quote(str(doc), safe="")
    encoded_twice = urllib.parse.quote(encoded_once, safe="")
    response = _req(
        url, f"/workspace-file?path={encoded_twice}&token={TOKEN}", token=None)
    assert response.read().decode("utf-8") == "# preview"

    with pytest.raises(urllib.error.HTTPError) as error:
        _req(url, f"/workspace-file?path={path}", token=None)
    assert error.value.code == 401

    outside_path = urllib.parse.quote(str(outside), safe="")
    with pytest.raises(urllib.error.HTTPError) as error:
        _req(url, f"/workspace-file?path={outside_path}&token={TOKEN}", token=None)
    assert error.value.code == 404


def test_workspace_markdown_edit_versions_and_learns(srv, monkeypatch, tmp_path):
    url, store = srv
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    doc = workspace / "draft.md"
    doc.write_text("AI가 쓴 문장\n", encoding="utf-8")
    _req(url, "/settings", {
        "workspace_dir": str(workspace), "output_dir": str(output),
    }, method="PUT")
    session_id = store.create_session("설교 원고")
    message_id = store.add_message(
        session_id, "assistant", [{"type": "text", "text": f"[원고]({doc})"}])

    result = json.load(_req(url, "/workspace-file", {
        "path": str(doc),
        "content": "목사님이 다듬은 문장\n적용 문장\n",
        "message_id": message_id,
    }, method="PUT"))

    assert result["changed"] is True and result["learned"] is True
    assert result["additions"] == 2 and result["deletions"] == 1
    assert doc.read_text(encoding="utf-8") == "목사님이 다듬은 문장\n적용 문장\n"
    assert Path(result["version_path"]).read_text(encoding="utf-8") == "AI가 쓴 문장\n"
    revisions = store.list_document_revisions()
    assert len(revisions) == 1
    assert "목사님이 다듬은 문장" in revisions[0]["diff"]
    feedback = store.feedback_for_message(message_id)
    assert feedback[-1]["kind"] == "correction"
    mirrored = next(output.glob(f"session-{session_id}-*")) / "draft.md"
    assert mirrored.read_text(encoding="utf-8") == "목사님이 다듬은 문장\n적용 문장\n"
    mirrored_versions = list(
        (mirrored.parent / ".kairos-versions" / "draft").glob("*-before.md"))
    assert len(mirrored_versions) == 1
    assert mirrored_versions[0].read_text(encoding="utf-8") == "AI가 쓴 문장\n"


def test_reviews_lists_structured_review_files(srv, monkeypatch, tmp_path):
    url, _ = srv
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))
    output = tmp_path / "output"
    output.mkdir()
    valid = output / "pastor.review.json"
    valid.write_text(json.dumps({
        "schema": "kairos.theology-review.v1",
        "title": "신학 승인",
        "review_status": "in_review",
        "claims": [
            {"id": "A", "status": "approved"},
            {"id": "B", "status": "pending"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (output / "ordinary.json").write_text('{"claims":[]}', encoding="utf-8")
    _req(url, "/settings", {"output_dir": str(output)}, method="PUT")

    reviews = json.load(_req(url, "/reviews"))["reviews"]

    assert len(reviews) == 1
    assert reviews[0]["path"] == str(valid.resolve())
    assert reviews[0]["title"] == "신학 승인"
    assert reviews[0]["decided"] == 1
    assert reviews[0]["total"] == 2


def test_review_save_promotes_approved_claims(srv, monkeypatch, tmp_path):
    url, _ = srv
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    review = output / "pastor.review.json"
    review.write_text(json.dumps({
        "schema": "kairos.theology-review.v1",
        "claims": [{"id": "SOT-1", "domain": "soteriology",
                    "claim": "구원은 은혜다.", "status": "pending"}],
    }, ensure_ascii=False), encoding="utf-8")
    _req(url, "/settings", {
        "workspace_dir": str(workspace), "output_dir": str(output),
    }, method="PUT")
    updated = {
        "schema": "kairos.theology-review.v1",
        "claims": [{"id": "SOT-1", "domain": "soteriology",
                    "claim": "구원은 은혜다.", "status": "approved"}],
    }

    result = json.load(_req(url, "/workspace-file", {
        "path": str(review),
        "content": json.dumps(updated, ensure_ascii=False),
    }, method="PUT"))

    assert result["promoted"]["approved"] == 1
    profile = workspace / "authors" / "main_pastor" / "approved-sermon-rag.json"
    assert json.loads(profile.read_text(encoding="utf-8"))["approved_count"] == 1


def test_chat_injects_approved_sermon_rag(srv, monkeypatch, tmp_path):
    url, _ = srv
    monkeypatch.setenv("KAIROS_CONFIG_DIR", str(tmp_path / "cfg"))
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    (output / "pastor.review.json").write_text(json.dumps({
        "schema": "kairos.theology-review.v1",
        "claims": [{
            "id": "CHR-1", "domain": "christology",
            "claim": "설교는 예수 그리스도의 십자가와 부활로 수렴한다.",
            "status": "approved",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    corpus = output / "distilled"
    corpus.mkdir()
    (corpus / "corpus-manifest.json").write_text(json.dumps({
        "sermons": [{
            "article": "2026-resurrection",
            "date": "2026-04-05",
            "title": "부활의 승리",
            "passage": "고린도전서 15:20",
            "summary": "예수님의 부활",
            "definition_evidence": [{
                "marker": "W2", "excerpt": "구원은 부활의 생명이다.",
            }],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    _req(url, "/settings", {
        "workspace_dir": str(workspace), "output_dir": str(output),
    }, method="PUT")
    monkeypatch.setenv(
        "KAIROS_CLAUDE_CMD", f"{sys.executable} {FAKES/'fake_argv_dump.py'}")

    events = _sse_events(_req(
        url, "/chat", {"text": "@claude 부활 설교 기획해줘"}))
    done = events[-1]
    messages = json.load(_req(
        url, f"/messages?session_id={done['session_id']}"))["messages"]
    prompt = messages[-1]["content"][0]["text"]

    assert done["sermon_rag"] >= 2
    status_codes = [event["code"] for event in events if event["type"] == "status"]
    assert "searching_sermons" in status_codes
    assert "organizing_evidence" in status_codes
    assert "목사님 승인 신학" in prompt
    assert "CHR-1" in prompt
    assert "부활의 승리" in prompt


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


def test_presentation_upload_status_and_download(srv, monkeypatch):
    url, _ = srv
    monkeypatch.setenv("KAIROS_PRESENTATION_FAKE", "1")
    body = b"# Lesson\n\nImportant point\n"
    created = json.load(_multipart_req(
        url, "/presentations", "lesson.md", body,
        {"title": "테스트 강의", "provider": "codex", "slide_count": 8},
    ))
    deadline = time.time() + 5
    while time.time() < deadline:
        job = json.load(_req(url, f"/presentations/{created['id']}"))
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job
    jobs = json.load(_req(url, "/presentations"))["jobs"]
    assert jobs[0]["id"] == created["id"]
    result = _req(url, f"/presentations/{created['id']}/download")
    assert result.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    assert result.read().startswith(b"PK")
    direct = _req(
        url,
        f"/presentations/{created['id']}/download?token={TOKEN}",
        token=None,
    )
    assert direct.read().startswith(b"PK")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(url, f"/presentations/{created['id']}/download", token=None)
    assert exc.value.code == 401
    opened = []
    monkeypatch.setattr(
        "core.server._open_local_path",
        lambda path, reveal=False: opened.append((path, reveal)),
    )
    response = json.load(_req(
        url, f"/presentations/{created['id']}/open", {}, method="POST"
    ))
    assert response["ok"] is True
    assert opened[-1][1] is False
    response = json.load(_req(
        url, f"/presentations/{created['id']}/reveal", {}, method="POST"
    ))
    assert response["ok"] is True
    assert opened[-1][1] is True
