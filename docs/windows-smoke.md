# Windows 스모크 절차 (P1)

사전: Python 3.12+, Node 20+, Rust, claude/codex CLI 설치 및 로그인.

1. `python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt`
2. `.venv\Scripts\python -m pytest` — 전부 통과해야 함 (특히 test_main_entry의 watchdog)
3. `cd app && npm install && npm run build`
4. `cd src-tauri && cargo test && cargo tauri dev`
5. 앱에서: 채팅 1회(한국어 응답 깨짐 없어야 — UTF-8), @codex 강제 지정 1회,
   창 닫은 뒤 작업관리자에 python 잔존 없어야 함(watchdog).
