"""Persistent Kairos presentation worker.

This process is launched independently from the Tauri API sidecar. It owns the
PPT queue, survives UI/API restarts, and recovers interrupted jobs after a
worker or machine restart.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
import hashlib
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

from core import settings
from core.presentations import PresentationManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SingletonLock(AbstractContextManager):
    def __init__(self, path: Path):
        self.path = path
        self.mutex = None
        if os.name == "nt":
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b" ")
            self.file.flush()
        self.file.seek(0)

    def __enter__(self):
        if os.name == "nt":
            import ctypes

            name_hash = hashlib.sha256(
                str(self.path.resolve()).casefold().encode("utf-8")
            ).hexdigest()
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            mutex = kernel32.CreateMutexW(None, False, f"Local\\KairosPptWorker-{name_hash}")
            if not mutex:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(mutex)
                raise BlockingIOError("another presentation worker is already running")
            self.mutex = mutex
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def __exit__(self, exc_type, exc, tb):
        if os.name == "nt":
            if self.mutex:
                import ctypes

                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self.mutex)
                self.mutex = None
            return False
        try:
            self.file.seek(0)
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
        return False


def _write_worker_state(root: Path, **patch):
    path = root / "worker.json"
    current = {}
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    current.update(patch)
    current["pid"] = os.getpid()
    current["heartbeat"] = _now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_worker(data_dir: Path, bundle_dir: Path | None, poll_seconds: float = 1.0):
    manager = PresentationManager(data_dir, bundle_dir, external_worker=True)
    stop = False

    def request_stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, request_stop)

    with SingletonLock(manager.root / "worker.lock"):
        _write_worker_state(manager.root, state="idle", started_at=_now())
        recovered_ids = {
            job["id"] for job in manager.list()
            if job.get("status") == "running"
        }
        for job_id in recovered_ids:
            manager._write_status(
                job_id, status="queued", stage="백그라운드 워커 재개 대기",
                error=None,
            )

        while not stop:
            queued = [
                job for job in reversed(manager.list())
                if job.get("status") == "queued"
            ]
            if queued:
                job_id = queued[0]["id"]
                _write_worker_state(manager.root, state="working", job_id=job_id)
                manager.run_job(job_id, recovered=job_id in recovered_ids)
                recovered_ids.discard(job_id)
                _write_worker_state(manager.root, state="idle", job_id=None)
            else:
                _write_worker_state(manager.root, state="idle", job_id=None)
                time.sleep(poll_seconds)
        _write_worker_state(manager.root, state="stopped", job_id=None)


def main() -> int:
    data_dir = Path(os.environ["KAIROS_DATA_DIR"]).expanduser()
    if "data_dir" in settings.explicit_keys():
        configured = settings.load().get("data_dir")
        if configured:
            data_dir = Path(configured).expanduser()
    bundle = os.environ.get("KAIROS_BUNDLE_DIR")
    try:
        run_worker(data_dir, Path(bundle) if bundle else None)
    except (BlockingIOError, OSError) as exc:
        # Another healthy singleton already owns the queue.
        if getattr(exc, "winerror", None) in {33, 36} or isinstance(exc, BlockingIOError):
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
