# Kairos Studio v2

채팅이 유일한 창구인 개인 멀티모달 스튜디오. P1: 채팅 코어 + 모델 라우터.

## 실행
- 개발: `cd src-tauri && cargo tauri dev` (사전: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`, `cd app && npm install && npm run build`)
- 사이드카 단독: `PORT=8787 .venv/bin/python -m core` → http://127.0.0.1:8787
- 테스트: `.venv/bin/python -m pytest && (cd src-tauri && cargo test)`

## 구조
스펙: docs/superpowers/specs/2026-07-16-p1-chat-core-design.md

## P1 검증 로그

### 회귀 테스트 (2026-07-17)
```
.venv/bin/python -m pytest -q         → 30 passed
(cd src-tauri && cargo test -q)       → 9 passed
(cd app && npm run build)             → 빌드 성공 (dist/ 생성)
```

### 완료 기준 5개 — 2단계 검증 (2026-07-17)

GUI(`cargo tauri dev`)를 이 세션에서 직접 조작할 수 없어, 아래 두 단계로 나누어 확인했다.

**1단계 — 헤드리스 (본 세션에서 실측 완료)**

`KAIROS_DATA_DIR=/tmp/kairos-p1-acceptance PORT=8791 .venv/bin/python -m core` 로 사이드카를 직접 띄우고
`curl`로 API를 호출해 확인. 사용한 임시 데이터 디렉터리는 실제 사용자 데이터와 분리되어 있으며,
검증 후 프로세스는 모두 종료 확인(PID kill 후 `ps -p` 확인)했다.

| # | 기준 | 방법 | 결과 |
|---|------|------|------|
| 1 | 채팅 → Claude 응답 토큰 단위 스트리밍 | `POST /chat {"text":"안녕, 너는 누구야? 한 문장으로 답해줘"}` | SSE `delta` 이벤트 4건 후 `done` — `provider:"claude"` 확인 |
| 2 | codex 라벨 응답 | `POST /chat {"text":"core/server.py 파일 내용 요약해줘"}` (실제 codex CLI 호출, 최대 120초 허용) | `done` 이벤트에 `provider:"codex"` 확인 |
| 3 | `@claude` 멘션이 라우팅 규칙을 이김 | `POST /chat {"text":"@claude 그냥 인사해줘"}` | `done` 이벤트에 `provider:"claude"` 확인 (멘션 강제 라우팅 동작) |
| 4 | 앱 재시작 → 세션 목록·대화 복원 | 사이드카 프로세스 kill 후 동일 `KAIROS_DATA_DIR`로 재기동, `GET /sessions`·`GET /messages?session_id=1` 재조회 | 재시작 전 생성된 세션 3건, 메시지(user/assistant 쌍, `session_ref` 포함) 모두 그대로 조회됨 |
| 5 | 👍 클릭 → feedback 저장 | `POST /feedback {"message_id":2,"kind":"up"}` 후 `sqlite3`로 직접 `SELECT * FROM feedback` | `id=1, message_id=2, kind='up'` 행 확인 |

**2단계 — GUI (사용자 수동 확인 대기)**

`cargo tauri dev`로 연 실제 앱 창에서의 최종 확인은 이 세션에서 수행할 수 없어 보류.
사용자가 직접 앱을 열어 위 5개 기준(특히 화면상 provider 라벨 표시·토큰 스트리밍 애니메이션·창 재시작
후 UI 복원·피드백 버튼 클릭)을 눈으로 확인해야 한다. 확인 후 창을 정상 종료하면 사이드카 프로세스가
watchdog에 의해 함께 정리되는지도 같이 확인 권장.
