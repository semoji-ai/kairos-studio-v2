# Kairos Studio v2 — P1: 채팅 코어 + 모델 라우터 설계

날짜: 2026-07-16
상태: 승인됨 (사용자 확인)

## 비전 (전체)

kairos-studio는 **채팅이 유일한 창구인 개인 멀티모달 스튜디오**다.
채팅 안에서 이미지를 보여주고, 글을 보여주고, 문서를 만들어주며,
여러 모델을 라우팅하고, 사용자를 학습한다.

학습의 의미 (사용자 정의, 4종):
1. 대화·문서 기억 누적 (RAG/메모리)
2. 사용자 문체·취향 학습 (gn-voice 연동)
3. 피드백 루프 (좋아요/교정 → 규칙·예시 누적)
4. 모델 파인튜닝 — **당장은 제외**, 스키마만 대비

## 단계 분해

| 단계 | 내용 |
|---|---|
| **P1 (이 문서)** | 채팅 코어 + 라우터 + 학습-친화 기록 스키마 |
| P2 | 툴 + 아티팩트 (한 몸): 이미지·문서·RAG를 tool-use로, 결과는 인라인 렌더 |
| P3 | 학습 루프: RAG 자동 누적 + 문체 + 피드백 반영 |
| 제외 | 파인튜닝 (P1 스키마가 데이터를 쌓아두므로 후행 가능) |

설계 원칙: 툴과 렌더는 분리하지 않는다(한 몸). 메모리 스키마는 P1부터 깔린다
(나중에 스키마를 바꾸면 그때까지의 대화가 학습 자산이 못 되기 때문).

## 핵심 결정 사항

- **신규 스캐폴드** (`~/LocalProjects/kairos-studio-v2`). Orca(kairos-app)는 너무 무겁고
  제품 성격이 다름. 기존 kairos-studio 통째 재활용도 하지 않음 — 필요한 것만 담는다.
- **LLM 백엔드: 구독 자원만.** Claude Code CLI + Codex CLI를 subprocess로.
  API 키/과금 없음. 두 provider가 동일 패턴(spawn → stdout 스트림 파싱 → SSE 릴레이).
- **멀티 라우팅**: 규칙 기반으로 시작. LLM-판단 라우팅은 하지 않음(후행 개선).
- **기존 kairos-studio에서 체리픽 (3개 이내, 파일 단위):**
  - sidecar watchdog (parent-death stdin-EOF, 커밋 35862cb에서 검증)
  - health-gate 핸드셰이크 패턴
  - 토큰 인증 미들웨어
- **기존 kairos-studio 처리**: 참조용으로 유지. v2가 P2에서 RAG 흡수하면 NAS 아카이브.
  `src-tauri/target` 2.6G는 cargo clean으로 회수 가능.

## 아키텍처

```
kairos-studio-v2/
├─ src-tauri/                  ← Tauri 2 최소 셸 (창 1개 + sidecar spawn/watchdog)
├─ app/                        ← Vite + React 최소 (채팅 화면 하나)
│   ├─ Chat.tsx                ← 메시지 리스트 + 입력창 + SSE 스트리밍 + 👍/👎
│   └─ api.ts
└─ core/                       ← Python 사이드카 (stdlib 위주, 경량)
    ├─ server.py               ← HTTP+SSE. 라우트: /health /chat /sessions /feedback
    ├─ router.py               ← 규칙 라우팅
    ├─ providers/
    │   ├─ claude.py           ← claude -p --output-format stream-json
    │   │                         --include-partial-messages → JSONL 파싱 → SSE
    │   └─ codex.py            ← codex exec subprocess
    └─ store.py                ← SQLite 3테이블
```

### 라우터 규칙 (P1)

1. 코드·파일·터미널 작업 → Codex CLI
2. 긴 글·기획·일반 대화 → Claude CLI
3. `@claude` / `@codex` 명시 → 강제 지정
4. 로컬 모델(Ollama)은 라우터에 자리만 남기고 미구현

### 기록 스키마 (학습의 씨앗 — P1에서 확정)

```sql
sessions(id, title, created_at)
messages(id, session_id, role, content_json,   -- 텍스트+아티팩트 참조 JSON
         provider, model, created_at)
feedback(message_id, kind,                     -- 'up' | 'down' | 'correction'
         payload, created_at)
```

- 대화 원본은 **항상 우리 SQLite에 저장**. CLI 세션 파일(~/.claude, ~/.codex)에
  의존하지 않는다 — CLI 로그는 통제 밖 (15G 세션 로그 사태 참조).
- `content_json` 구조화로 P2 아티팩트·P3 학습이 스키마 변경 없이 얹힌다.
- 세션 이어가기: claude `--resume`/`-c`, codex 세션 파일 활용하되 원본은 SQLite.

### 안전 (설계에 명시)

CLI들은 툴 실행 권한을 가진 에이전트다. 채팅 앱 뒤에서 돌 때
**권한 모드를 보수적으로 고정**한다:
- claude: `--permission-mode` 제한
- codex: sandbox 설정 강제
"채팅했는데 파일이 지워졌다"를 원천 차단.

### 응답 지연

CLI 부팅 오버헤드로 API 대비 첫 토큰이 느림 — P1에서는 수용.
필요 시 프로세스 풀로 후행 개선.

## 크로스플랫폼 (macOS + Windows)

P1부터 Windows 동작을 요구사항으로 한다. 스택(Tauri/React/Python/SQLite)은
모두 크로스플랫폼. 구현 시 지킬 것:

- **프로세스 스폰**: shell 경유 금지, 실행파일 직접 spawn. CLI 탐색은
  PATH 조회로 (`claude`/`claude.cmd`, `codex`/`codex.cmd` — Windows는
  npm 래퍼가 .cmd일 수 있음).
- **watchdog**: parent-death 감지는 stdin-EOF 방식이라 양 OS 동일 동작
  (Windows 전용 job object 불필요 — 기존 방식 그대로 이식).
- **경로/저장소**: 하드코딩 금지. 데이터 디렉토리는 Tauri app-data dir 기준
  (macOS `~/Library/Application Support/`, Windows `%APPDATA%`).
- **인코딩**: subprocess stdout은 UTF-8 강제 (Windows 기본 cp949 함정 방지,
  한국어 대화 필수 요건).
- **CI/검증**: 개발은 macOS에서, Windows는 각 단계 완료 시 수동 스모크
  (Windows 머신은 hwp-control 건과 동일하게 사용자 보유).

## 테스트

- provider: mock CLI(stdout에 고정 JSONL을 뱉는 가짜 실행파일)로 계약 테스트
- router: golden 테스트 (입력 → 기대 provider)
- server: SSE 스트리밍/인증/스키마를 pytest로 (기존 kairos-studio test_server.py 패턴)
- sidecar watchdog: 기존 검증 테스트 이식

## P1 완료 기준

1. 앱 실행 → 채팅창 질문 → Claude 응답이 토큰 단위 스트리밍
2. 코드·파일 질문 → 라우터가 Codex로 보내고 결과가 채팅에 표시
3. `@claude`/`@codex` 강제 지정 동작
4. 재시작 후 세션 목록·대화 복원 (SQLite)
5. 메시지마다 👍/👎 저장 (P3의 씨앗, UI는 버튼 2개만)

## 담지 않는 것 (명시적 제외)

- Orca 관련 일체
- 기존 RAG 패널·문체 탭 UI (P2·P3에서 tool로 재설계, 로직만 참조)
- 로컬 모델 구현
- 파인튜닝
- LLM-판단 라우팅
