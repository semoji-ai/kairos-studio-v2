import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_build_binds_and_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIROS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PORT", "0")
    from core.__main__ import build
    server, info = build()
    try:
        assert info["port"] == server.server_address[1] > 0
        assert info["token"]
    finally:
        server.server_close()


def test_stdin_watchdog_exits_on_parent_death(tmp_path):
    env = dict(os.environ,
               KAIROS_DATA_DIR=str(tmp_path), PORT="0",
               KAIROS_SIDECAR_STDIN_WATCH="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "core"], cwd=REPO, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        encoding="utf-8", errors="replace")
    line = proc.stdout.readline()
    assert json.loads(line)["port"] > 0
    proc.stdin.close()          # 부모 사망 시뮬레이션 → EOF
    deadline = time.time() + 5
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    assert proc.poll() is not None, "sidecar must exit on stdin EOF"
