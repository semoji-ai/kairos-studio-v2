import json

from core.learning import LearningManager


def _chat(fail_on=None):
    calls = []

    def chat(prompt, session_ref=None, cfg=None):
        calls.append({"prompt": prompt, "cfg": dict(cfg or {})})
        if fail_on and fail_on in prompt:
            yield {"type": "error", "error": "boom"}
            return
        yield {"type": "delta", "text": "진행 중"}
        yield {"type": "done", "text": "완료"}
    chat.calls = calls
    return chat


COMMIT = {"batch_id": "batch_20260930", "source_ids": ["src_20260930_001"],
          "primary": 1, "reference": 0}


def test_absorb_then_profile_with_accept_edits_only_for_job(tmp_path):
    chat = _chat()
    m = LearningManager(tmp_path, chat_fn=chat, run_async=False)
    cfg = {"claude_permission_mode": "default", "workspace_dir": "/ws"}
    job = m.create("/ws", COMMIT, cfg)
    job = m.get(job["id"])
    assert job["status"] == "completed"
    assert [c["prompt"].split()[0] for c in chat.calls] == ["/publish-absorb", "/publish-profile"]
    assert "src_20260930_001" in chat.calls[0]["prompt"]
    assert all(c["cfg"]["claude_permission_mode"] == "acceptEdits" for c in chat.calls)
    assert all(c["cfg"]["workspace_dir"] == "/ws" for c in chat.calls)
    assert cfg["claude_permission_mode"] == "default"  # 전역 설정 불변


def test_reference_only_batch_skips_profile(tmp_path):
    chat = _chat()
    m = LearningManager(tmp_path, chat_fn=chat, run_async=False)
    job = m.create("/ws", {**COMMIT, "primary": 0, "reference": 1}, {})
    assert m.get(job["id"])["status"] == "completed"
    assert len(chat.calls) == 1


def test_provider_error_marks_failed_and_retry_runs_again(tmp_path):
    m = LearningManager(tmp_path, chat_fn=_chat(fail_on="/publish-absorb"), run_async=False)
    job = m.create("/ws", COMMIT, {})
    failed = m.get(job["id"])
    assert failed["status"] == "failed" and "boom" in failed["error"]
    m.chat_fn = _chat()
    assert m.retry(job["id"], {})["status"] == "completed"


def test_interrupted_job_from_previous_process_becomes_failed(tmp_path):
    m = LearningManager(tmp_path, chat_fn=_chat(), run_async=False)
    job = m.create("/ws", COMMIT, {})
    path = tmp_path / "learning" / job["id"] / "status.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(status="absorbing", pid=-1)
    path.write_text(json.dumps(data), encoding="utf-8")
    got = m.get(job["id"])
    assert got["status"] == "failed" and "중단" in got["error"]
    assert [j["id"] for j in m.list()] == [job["id"]]


def test_unexpected_exception_marks_failed_and_retryable(tmp_path):
    def chat(prompt, session_ref=None, cfg=None):
        raise UnicodeError("bad bytes")
        yield  # pragma: no cover
    m = LearningManager(tmp_path, chat_fn=chat, run_async=False)
    job = m.create("/ws", COMMIT, {})
    got = m.get(job["id"])
    assert got["status"] == "failed" and "bad bytes" in got["error"]


def test_has_running_blocks_second_job_same_workspace(tmp_path):
    m = LearningManager(tmp_path, chat_fn=_chat(), run_async=False)
    job = m.create("/ws", COMMIT, {})
    assert m.has_running("/ws") is False
    m._write(job["id"], status="absorbing")
    assert m.has_running("/ws") is True
    assert m.has_running("/other") is False


def test_interrupted_job_kills_orphan_claude_process(tmp_path):
    import subprocess
    import sys
    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        m = LearningManager(tmp_path, chat_fn=_chat(), run_async=False)
        job = m.create("/ws", COMMIT, {})
        m._write(job["id"], status="absorbing", pid=-1, child_pid=orphan.pid)
        assert m.get(job["id"])["status"] == "failed"
        assert orphan.wait(timeout=5) is not None
    finally:
        if orphan.poll() is None:
            orphan.kill()


def test_job_records_spawned_claude_pid(tmp_path):
    def chat(prompt, session_ref=None, cfg=None):
        cfg["on_spawn"](4242)
        yield {"type": "done", "text": "ok"}
    m = LearningManager(tmp_path, chat_fn=chat, run_async=False)
    job = m.create("/ws", COMMIT, {})
    assert m.get(job["id"])["child_pid"] == 4242
