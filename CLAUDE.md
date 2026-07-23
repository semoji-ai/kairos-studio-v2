# Kairos Studio v2 — 내부 작업 규칙

## 이미지 작업 규칙

**규칙**: 이 컴퓨터에서 Claude로 하는 작업 중 이미지 생성이 필요하면 **항상 codex-fleet 스킬을 사용한다**.

**사용 시나리오**:
- 다수의 이미지를 일괄 생성해야 할 때 (예: 배경 이미지 100장, 아이콘 50개 등)
- 복잡한 생성 조건을 반복 적용해야 할 때
- 대규모 이미지 작업으로 인한 rate limit 회피가 필요할 때

**스킬**: `/codex-imagegen`

**병렬 처리**:
- 기본: `PARALLEL=auto` (작업 수에 맞춰 자동 스케일, 최대 min(16, CPU-1))
- 최대 **32개 이미지까지 동시 처리 가능** (ChatGPT Plus/Pro 계정 rate limit 고려)
- 수동 조정: `PARALLEL=8` 같이 고정 가능

**결과 회수**:
- 이미지 작업 시 레이스 조건 방지 (claimed 락 사용)
- 결과는 `~/.codex/generated_images/` 또는 지정한 `OUTDIR`에 저장
- 파일 충돌 방지 (세션 UUID 기반 격리)

**성능 특성**:
- 단일 이미지보다 **대량 처리가 훨씬 효율적** (초당 처리량 증가)
- 429 rate limit 감지 시 자동으로 성장 멈춤 (안전 메커니즘)

**관련 문서**:
- 스킬 문서: `~/.claude/skills/codex-imagegen/SKILL.md`
- 예제: `D:\projects\codex-fleet\examples\manifest.jsonl`
- 러너: `D:\projects\codex-fleet\runners\codex_imagegen_runner.py`

---

## 코드 작업 규칙

**규칙**: 대규모 코드 수정, 분석, 요약, 리뷰가 필요하면 **codex-spawn 스킬을 사용한다**.

**사용 시나리오**:
- 50개 이상의 파일을 일괄 처리
- 반복적인 코드 패턴 변환 (예: Python 2 → 3 마이그레이션)
- 다수의 파일에 대한 동시 분석/요약

**스킬**: `/codex-spawn`

**설정**:
```bash
TASKS=tasks.jsonl OUTDIR=./out SANDBOX=read-only \
  python3 D:\projects\codex-fleet\runners\codex_spawn_runner.py
```

**병렬 처리**: 이미지 작업과 동일 (`PARALLEL=auto` 기본)

---

## Bible RAG 시스템

**상태**: Phase 4 완료 (94,576개 문서 색인)

**기능**:
- 성경 본문 검색 (Bethlehem + MyBible)
- 자동 구절 주입 (채팅 시 관련 성경 구절 자동 포함)
- SQLite FTS5 기반 (경량, 의존성 최소)

**데이터**:
- Bethlehem: 93,291개 구절
- MyBible: 1,189개 구절
- 성경지도: 96장

**DB**: `bible_documents.db`

**참고**: 외부 API 없이 모두 로컬에서 처리 (구독 Claude CLI만 사용)

---

## 크로스머신(맥·윈도우) 작업 규약

한 리포·한 main. **OS별 브랜치 금지** — 플랫폼 차이는 코드/마커로 처리한다.

1. **테스트**: 공용 테스트는 `tests/`에만 (pytest는 `pyproject.toml`의
   `testpaths=["tests"]`로 여기만 수집). 환경 의존 테스트는
   `pytest.mark.skipif(sys.platform != "win32", ...)` 식으로 스킵 처리 —
   어느 머신에서든 `pytest` 한 방이 항상 그린이어야 한다.
2. **scripts/ = 로컬 스크립트**: pytest 수집 대상 아님. 일회성 추출·검증
   스크립트는 여기에. 하드코딩 경로가 필요하면 env 오버라이드를 열어둘 것
   (예: `KAIROS_BIBLE_MDB`), 없으면 명확한 에러 메시지.
3. **경로**: 공용 코드(core/, app/, src-tauri/)에 `C:\...`·`/Users/...`
   하드코딩 금지. 데이터 위치는 settings/env로.
4. **작업 흐름**: 시작 전 `git pull`(+ `cd app && npm install` — 의존성이
   바뀌었을 수 있음), feature 브랜치에서 작업 → main 머지 → push.
5. **머지 전 3종 체크**: `.venv/bin/python -m pytest -q`(맥) 또는
   `.venv\Scripts\python -m pytest -q`(윈), `cd src-tauri && cargo test`,
   `cd app && npm run build`.
