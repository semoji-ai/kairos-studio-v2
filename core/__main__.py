from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from pathlib import Path

from core.server import make_server
from core.store import Store


def _data_dir() -> Path:
    d = os.environ.get("KAIROS_DATA_DIR")
    return Path(d).expanduser() if d else Path.home() / ".kairos-studio"


def build(argv=None):
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "0"))
    token = os.environ.get("TOKEN") or secrets.token_urlsafe(24)
    store = Store(_data_dir() / "kairos.db")
    server = make_server(host, port, token, store)
    info = {"host": host, "port": server.server_address[1], "token": token}
    return server, info


def start_parent_death_watchdog() -> None:
    """부모(stdin 파이프 소유자)가 죽으면 종료. KAIROS_SIDECAR_STDIN_WATCH=1 opt-in.

    데스크톱 셸이 stdin을 파이프로 물고 이 플래그를 세팅한다. 셸이 어떤 이유로든
    죽으면(EOF) 사이드카는 스스로 종료 — 고아가 되어 포트를 잡고 있지 않는다.
    직접/e2e 실행은 플래그가 없으므로 영향 없음. (kairos-studio 검증 코드 이식)
    """
    if os.environ.get("KAIROS_SIDECAR_STDIN_WATCH") != "1":
        return

    def _watch() -> None:
        try:
            while sys.stdin.readline():
                pass
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


def main(argv=None) -> int:
    server, info = build(argv)
    print(json.dumps(info), flush=True)  # 한 줄 핸드셰이크
    start_parent_death_watchdog()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
