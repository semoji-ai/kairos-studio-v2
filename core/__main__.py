from __future__ import annotations

import json
import os
import secrets
import sqlite3
import sys
import threading
from pathlib import Path

from core import documents, settings
from core.server import make_server
from core.store import Store

_DEFAULT_DATA_DIR = Path.home() / ".kairos-studio"


def _default_data_dir() -> Path:
    return _DEFAULT_DATA_DIR


def _data_dir() -> Path:
    # settings.json에 명시적으로 저장된 data_dir > env KAIROS_DATA_DIR > 기본값.
    # (Tauri는 항상 env KAIROS_DATA_DIR=app_data_dir을 넘기므로, 사용자가 설정 UI에서
    # 저장한 값이 재시작 후에도 유지되려면 명시적 설정이 env보다 우선해야 한다.)
    if "data_dir" in settings.explicit_keys():
        cfg_dir = settings.load().get("data_dir")
        if cfg_dir:
            return Path(cfg_dir).expanduser()
    d = os.environ.get("KAIROS_DATA_DIR")
    if d:
        return Path(d).expanduser()
    return _default_data_dir()


def build(argv=None):
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "0"))
    token = os.environ.get("TOKEN") or secrets.token_urlsafe(24)
    data_dir = _data_dir()
    try:
        store = Store(data_dir / "kairos.db")
    except (OSError, sqlite3.Error):
        os.environ["KAIROS_STORE_FALLBACK"] = "1"
        store = Store(_default_data_dir() / "kairos.db")
    # 성경 DB는 gitignore라 git pull로 갱신되지 않는다. 코드만 새로 받았을 때
    # 낡은 관주 인덱스를 여기서 알아서 다시 짓는다 — 서버가 요청을 받기 전이라
    # 검색과 겹치지 않는다. 실패해도(읽기 전용 번들 등) 앱은 그대로 뜬다.
    try:
        documents.ensure_verse_index(documents.default_db_path())
    except Exception:
        pass

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
