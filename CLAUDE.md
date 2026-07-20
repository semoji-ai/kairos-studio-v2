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
