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

## P1.5 검증 로그 (2026-07-17)

스펙: docs/superpowers/specs/2026-07-17-p1.5-settings-design.md (설정 화면: data_dir·provider·routing·권한 모드)

### 회귀 트리플
```
.venv/bin/python -m pytest -q         → 47 passed
(cd src-tauri && cargo test -q)       → 9 passed
(cd app && npm run build)             → 빌드 성공 (dist/ 생성, tsc -b && vite build)
```

### 완료 기준 5개 — 헤드리스 검증 (본 세션에서 실측 완료)

`KAIROS_CONFIG_DIR=/tmp/p15-acc/cfg`로 격리된 사이드카를 직접 띄우고(`PORT=8795`/`8796`, `TOKEN=t`)
`curl`+`sqlite3`로 확인. `KAIROS_DATA_DIR`는 설정을 오버라이드하는 설계이므로 기준 2 검증 시에는
설정하지 않고 `data_dir`이 설정으로만 구동되도록 했다. 검증 후 두 사이드카 PID 모두 kill 후
`ps -p` 부재로 종료 확인, `/tmp/p15-acc` 삭제 완료.

| # | 기준 | 방법 | 결과 |
|---|------|------|------|
| 1 | claude/codex 설치·로그인 상태 표시 | `GET /cli/status` | 실제 CLI 실측: `claude` installed=true, version "2.1.210 (Claude Code)", authed=true / `codex` installed=true, version "codex-cli 0.144.1", authed=true |
| 2 | data_dir 변경(존재 가능 경로) → DB 복사, 새 대화가 새 위치에 | `PUT /settings {"data_dir":"/tmp/p15-acc/moved"}` 후 `POST /chat {"text":"@claude 한 단어로 인사"}` | `kairos.db`가 base→moved로 복사됨(MD5 일치 확인), 이후 세션(`session_id=2`)·메시지(`id=3,4`, provider=`claude`)는 moved DB에만 존재, base DB는 그대로(MD5 불변) |
| 3 | 기본 provider=codex + routing_rules_enabled=false → 일반 질문이 codex로 | `PUT /settings {"default_provider":"codex","routing_rules_enabled":false}` 후 `POST /chat {"text":"오늘 날씨 어때?"}` (실제 codex CLI, 최대 120초 허용) | `done` 이벤트 `provider:"codex"` 확인 |
| 4 | 권한 모드 변경이 실제 CLI 호출 인자에 반영 | 2번째 사이드카를 `KAIROS_CLAUDE_CMD=".venv/bin/python tests/fakes/fake_argv_dump.py"`로 기동, `PUT /settings {"claude_permission_mode":"acceptEdits"}` 후 `POST /chat {"text":"hello"}`, 저장된 메시지 본문(argv 덤프) 확인 | 저장된 assistant 메시지 텍스트가 `["-p", "hello", "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--permission-mode", "acceptEdits"]` — `--permission-mode acceptEdits` 반영 확인 |
| 5 | 잘못된 값 → 400, 기존 설정 유지 | `PUT /settings {"codex_sandbox":"danger-full-access"}` → 400 `"invalid codex_sandbox: 'danger-full-access'"` / `PUT /settings {"data_dir":"/dev/null/x"}` → 400 `"cannot create data_dir: ..."` | 두 요청 모두 400, 이후 `GET /settings` 응답이 요청 전과 완전히 동일(변경 없음) 확인 |

**GUI 조작 확인: 사용자 수동 확인 대기**

`cargo tauri dev`로 연 실제 설정 화면(데이터 위치·기본 provider·라우팅 규칙 토글·권한 모드 선택 UI)에서의
조작 확인은 이 세션에서 수행할 수 없어 보류. 사용자가 직접 설정 화면을 열어 위 5개 기준을 눈으로
확인해야 한다.

## P1.6 검증 로그 (2026-07-18)

작업 폴더(workspace) 연결 — publish_agent 통합 headless 실측:

| 기준 | 결과 |
|---|---|
| 워크스페이스 지정(존재 검증) | ✅ PUT /settings workspace_dir=~/LocalProjects/publish_agent 저장됨 |
| 스킬 감지 | ✅ /workspace/info → publish-* 10개 + CLAUDE.md 감지 |
| 미존재 경로 거부 | ✅ /nope/nope → 400, 설정 유지 |
| CLI cwd 반영 | ✅ fake_cwd_dump 응답 = /Users/.../publish_agent (SQLite 기록 확인) |
| 설정 UI(작업 폴더·스킬 안내·권한 권장) | 사용자 수동 확인 대기 |

## P3-1 검증 로그 (2026-07-19)

학습 루프(회상 + 프롬프트 주입) — headless 실측 (temp KAIROS_CONFIG_DIR/KAIROS_DATA_DIR,
PORT=8798, `KAIROS_CLAUDE_CMD=tests/fakes/fake_argv_dump.py`로 provider 수신 프롬프트 캡처):

| 완료 기준 | 결과 |
|---|---|
| 1. 과거 세션 주제를 새 세션에서 물으면 provider 프롬프트에 `[과거 대화 참고]` 블록 포함 | ✅ 세션A "설교 준비를 도와줘"(recalled=0) → 새 세션 "설교 이어서"(recalled=1); argv 덤프 assistant 저장본에 `[과거 대화 참고` 포함 |
| 2. 한글 2글자 단어("설교")로도 bigram 매칭 회상 | ✅ 위와 동일 요청으로 실증 (2글자 질의로 recalled≥1) |
| 3. up 피드백 답변 우선 회상 / down 답변은 회피 신호 분리 | Task 1-2 pytest로 검증됨 (`.venv/bin/python -m pytest -q` 72 passed, `test_recall.py` 재랭킹 케이스 포함) |
| 4. correction 피드백이 `[사용자 교정 이력]`으로 주입 | Task 1-2 pytest로 검증됨 (동일 스위트, `test_recall.py` correction 주입 케이스) |
| 5. `learning_recall_enabled=false` 시 주입 0 | ✅ PUT /settings `{"learning_recall_enabled": false}` 후 같은 질문 "설교 이어서 다시" → `recalled: 0` |
| 6. DB에 저장되는 user 원문에는 주입 블록 미포함 | ✅ `/messages` 조회 결과 — user 텍스트 = "설교 이어서 다시" (원문 그대로), assistant 저장본(argv 덤프)에만 `[과거 대화 참고` 포함 |
| 빌드/유닛 | ✅ `cd app && npm run build` clean, `.venv/bin/python -m pytest -q` 72 passed |
| Chat.tsx 🧠 회상 표시 / Settings.tsx 학습 회상 토글 | GUI 확인: 사용자 수동 확인 대기 |

## P3-2 검증 로그 (2026-07-20)

규칙 증류 UI(`app/src/Settings.tsx` "학습된 규칙" 섹션: 미증류 건수 · [지금 증류] 버튼 · 규칙별 활성 체크박스)
+ headless 수용 실측 (temp `KAIROS_CONFIG_DIR`/`KAIROS_DATA_DIR`, `PORT=8799`,
`KAIROS_CLAUDE_CMD`를 `tests/fakes/fake_distill_claude.py` ↔ `tests/fakes/fake_argv_dump.py`로 전환하며 3개
사이드카를 순차 기동, 각각 `curl`로 검증 후 kill/`ps -p` 부재 확인 → `/tmp` 스크래치 삭제):

| 완료 기준 | 방법 | 결과 |
|---|---|---|
| 1. correction 피드백 → `POST /distill` → `GET /rules`에 규칙 반영 | `/chat`으로 메시지 생성 → `/feedback {"kind":"correction"}` → `/distill` | ✅ `{"added": ["가운뎃점 대신 쉼표를 쓴다"]}`, 이후 `/rules`에 해당 규칙 등재(`active:true`) |
| 2. 활성 규칙이 이후 `/chat` provider 프롬프트에 `[학습된 규칙` 주입 | `KAIROS_CLAUDE_CMD→fake_argv_dump.py`로 전환한 2번째 사이드카에서 재채팅, 저장된 assistant 메시지(argv 덤프) 확인 | ✅ 저장본에 `"[학습된 규칙 — 항상 준수]\n- 가운뎃점 대신 쉼표를 쓴다..."` 포함 |
| 3. `POST /rules {"active":false}` 후 재채팅 → argv에 미포함 | 동일 사이드카에서 규칙 비활성화 후 같은 세션 재채팅 | ✅ 저장본에 `학습된 규칙` 블록 없음(`in` 검사 False), `[과거 대화 참고]`/`[사용자 교정 이력]`만 남음 |
| 4. `FAKE_BAD=1` 사이드카로 `/distill` → added 0 + 규칙 불변 | 3번째 사이드카(`FAKE_BAD=1`)에서 correction 피드백 추가 후 `/distill` | ✅ `{"added": [], "error": "parse"}`, 이후 `/rules`가 직전과 동일(규칙 1개, `active:false` 그대로, `undistilled`만 1로 증가) |
| 5. 미증류 피드백 임계치 도달 시 자동 증류 | Task 2 pytest 인용 (`test_server.py` threshold monkeypatch 케이스) | ✅ 동일 스위트 |
| 빌드/유닛 | `cd app && npm run build`, `.venv/bin/python -m pytest -q` | ✅ 빌드 clean, 84 passed |

**GUI: 사용자 수동 확인 대기** — Settings 화면의 "학습된 규칙" 섹션(미증류 건수 표시, [지금 증류] 버튼 클릭,
규칙별 체크박스 토글)에 대한 실제 조작 확인은 이 세션에서 수행할 수 없어 보류.

## P2 검증 로그 (2026-07-20)

인라인 아티팩트 UI 렌더(`app/src/api.ts` content 파트 타입 확장, `app/src/Chat.tsx` image/document 파트 렌더 +
`<details>` 지연 fetch) + headless 수용 실측 (temp `KAIROS_CONFIG_DIR`/`KAIROS_DATA_DIR`, `PORT=8800`,
`KAIROS_CLAUDE_CMD=tests/fakes/fake_echo_claude.py`로 프롬프트 속 파일 경로를 응답 텍스트에 그대로 에코시켜
감지를 유도, `/chat` → `store.list_messages` → `/artifacts/...`를 직접 호출):

| 완료 기준 | 결과 |
|---|---|
| 1. 응답 텍스트의 이미지 경로 → artifacts 복사 + content에 image 파트, done SSE `artifacts≥1` | ✅ 임시 `pic.png`+`doc.md`+11MB `big.png` 경로를 포함한 프롬프트 전송 → `done: {"artifacts": 2, ...}`, content에 `{"type":"image","artifact":"2/pic.png"}` |
| 2. `GET /artifacts/...`로 이미지 바이트 서빙, 경로 탈출은 404 | ✅ 서빙된 바이트가 원본 `pic.png`와 바이트 동일; `GET /artifacts/../../etc/passwd` → HTTP 404 |
| 3. md 경로 → document 파트 + 서빙 | ✅ `{"type":"document","artifact":"2/doc.md","title":"doc.md"}` 생성, `GET /artifacts/2/doc.md` 본문이 원본과 일치 |
| 4. 미존재 경로·크기 초과는 무시, 채팅 정상 완료 | ✅ 11MB `big.png`(이미지 한도 10MB 초과) 경로가 프롬프트에 포함돼도 parts에 등장하지 않고 `done`은 정상 도달(`artifacts:2`만 반영, big.png 제외) |
| 5. 원본 삭제 후에도 채팅 아티팩트는 서빙됨 | ✅ `pic.png`/`doc.md` 원본 삭제 후 동일 `GET /artifacts/2/pic.png` 재요청 → 여전히 200 + 동일 바이트 |
| 빌드/유닛 | ✅ `cd app && npm run build` clean, `python3 -m pytest -q` 95 passed |

**GUI: 사용자 수동 확인 대기** — 채팅 말풍선 안 이미지 인라인 렌더 및 문서 `<details>` 펼침 시 지연
로드 동작에 대한 실제 브라우저 조작 확인은 이 세션에서 수행할 수 없어 보류.
