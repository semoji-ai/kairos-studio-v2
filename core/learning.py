"""원고 학습 작업 — 기록된 배치를 Claude로 흡수(publish-absorb)하고
목사님 원고가 있으면 문체 프로필(publish-profile)을 갱신한다."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_RUNNING = {"absorbing", "profiling", "queued"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kill(pid) -> None:
    """앱이 꺼진 뒤에도 남아 작업 폴더를 고치던 claude 프로세스를 끝낸다."""
    if not isinstance(pid, int) or pid <= 0:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


def absorb_prompt(batch_id: str, source_ids: list[str]) -> str:
    return (f"/publish-absorb 이번 배치 {batch_id} 의 미흡수 항목({', '.join(source_ids)})을 "
            "위키에 흡수하세요. type: reference 항목은 참고자료로만 분류하고 "
            "저자(목사님)의 입장으로 쓰지 마세요. 확인 질문 없이 끝까지 진행하고, "
            "마지막에 흡수 결과를 한 문단으로 요약하세요.")


def profile_prompt(batch_id: str) -> str:
    return (f"/publish-profile 방금 흡수한 {batch_id} 의 목사님 원고(type: primary)를 반영해 "
            "문체 프로필과 설교 팩을 증분 갱신하세요. 참고자료(type: reference)는 분석에서 "
            "제외합니다. 확인 질문 없이 끝까지 진행하고 바뀐 점을 요약하세요.")


class LearningManager:
    def __init__(self, data_dir: Path, chat_fn=None, run_async: bool = True):
        self.root = Path(data_dir) / "learning"
        self.root.mkdir(parents=True, exist_ok=True)
        if chat_fn is None:
            from core import providers
            chat_fn = providers.get("claude").chat
        self.chat_fn = chat_fn
        self.run_async = run_async

    def _path(self, job_id: str) -> Path:
        return self.root / job_id / "status.json"

    def _write(self, job_id: str, **patch) -> dict:
        with _LOCK:
            path = self._path(job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            cur = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            cur.update(patch, updated_at=_now())
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            return cur

    def get(self, job_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id or ""):
            return None
        path = self._path(job_id)
        if not path.is_file():
            return None
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("status") in _RUNNING and job.get("pid") != os.getpid():
            _kill(job.get("child_pid"))
            job = self._write(job_id, status="failed", stage="중단됨",
                              error="앱이 종료되어 학습이 중단되었습니다. 다시 시도해 주세요.")
        return job

    def list(self) -> list[dict]:
        jobs = [self.get(p.parent.name) for p in self.root.glob("*/status.json")]
        return sorted([j for j in jobs if j], key=lambda j: j.get("created_at", ""), reverse=True)

    def has_running(self, workspace: str) -> bool:
        """같은 작업 폴더에서 흡수가 진행 중이면 True — 두 흡수가 위키를 동시에 고치지 않게."""
        return any(j.get("workspace") == workspace and j.get("status") in _RUNNING
                   for j in self.list())

    def create(self, workspace: str, commit: dict, cfg: dict) -> dict:
        job_id = uuid.uuid4().hex[:12]
        self._write(job_id, id=job_id, status="queued", stage="학습 대기 중",
                    batch_id=commit["batch_id"], source_ids=list(commit["source_ids"]),
                    primary=int(commit.get("primary", 0)),
                    reference=int(commit.get("reference", 0)),
                    workspace=workspace, log=[], error=None, pid=os.getpid(),
                    created_at=_now())
        self._dispatch(job_id, cfg)
        return self.get(job_id)

    def retry(self, job_id: str, cfg: dict) -> dict:
        job = self.get(job_id)
        if not job:
            raise ValueError("작업을 찾을 수 없습니다")
        if job["status"] != "failed":
            raise ValueError("실패한 작업만 다시 시도할 수 있습니다")
        if self.has_running(job.get("workspace", "")):
            raise ValueError("같은 작업 폴더에서 학습이 진행 중입니다")
        self._write(job_id, status="queued", stage="다시 시도 대기 중", error=None,
                    pid=os.getpid(), child_pid=None)
        self._dispatch(job_id, cfg)
        return self.get(job_id)

    def _dispatch(self, job_id: str, cfg: dict):
        if self.run_async:
            threading.Thread(target=self._run, args=(job_id, dict(cfg)), daemon=True).start()
        else:
            self._run(job_id, dict(cfg))

    def _log(self, job_id: str, text: str):
        job = self.get(job_id) or {}
        self._write(job_id, log=(list(job.get("log") or []) + [text[-2000:]])[-80:])

    def _step(self, job_id: str, prompt: str, cfg: dict) -> str | None:
        """한 단계 실행. 오류 메시지를 돌려주고, 성공이면 None."""
        final = None
        for ev in self.chat_fn(prompt, session_ref=None, cfg=cfg):
            if ev.get("type") == "error":
                return str(ev.get("error") or "알 수 없는 오류")
            if ev.get("type") == "done":
                final = ev.get("text") or ""
        if final is None:
            return "Claude 응답이 끝나지 않았습니다"
        self._log(job_id, final)
        return None

    def _run(self, job_id: str, cfg: dict):
        try:
            self._run_steps(job_id, cfg)
        except Exception as exc:  # 스레드가 죽어 '흡수 중'에 영원히 멈추지 않게
            self._write(job_id, status="failed", stage="실패", error=f"학습 중 오류: {exc}")

    def _run_steps(self, job_id: str, cfg: dict):
        job = self.get(job_id)
        run_cfg = dict(cfg)
        run_cfg["claude_permission_mode"] = "acceptEdits"
        run_cfg["workspace_dir"] = job["workspace"]
        run_cfg["on_spawn"] = lambda pid: self._write(job_id, child_pid=pid)
        self._write(job_id, status="absorbing", stage="위키에 흡수하는 중", pid=os.getpid())
        err = self._step(job_id, absorb_prompt(job["batch_id"], job["source_ids"]), run_cfg)
        if err is None and job.get("primary"):
            self._write(job_id, status="profiling", stage="문체 프로필 갱신 중")
            err = self._step(job_id, profile_prompt(job["batch_id"]), run_cfg)
        if err:
            self._write(job_id, status="failed", stage="실패", error=err)
        else:
            self._write(job_id, status="completed", stage="학습 완료")
