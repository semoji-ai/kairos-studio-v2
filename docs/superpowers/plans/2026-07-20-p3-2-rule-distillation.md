# P3-2 규칙 증류 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 피드백 → LLM 증류 → learned_rules → [학습된 규칙] 주입 → UI 관리.
**Architecture:** 스펙 `docs/superpowers/specs/2026-07-20-p3-2-rule-distillation-design.md` 정본.

## Global Constraints
- Python stdlib only. LLM은 provider(claude CLI subprocess)만. 파싱 실패 시 저장 0(날조 방지).
- 기존 75 테스트 그린 유지. 커밋 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: store learned_rules + core/distill.py (TDD)

**Files:** Modify `core/store.py`; Create `core/distill.py`; Test `tests/test_distill.py`, `tests/fakes/fake_distill_claude.py`

**Interfaces:**
- store: `_SCHEMA`에 learned_rules + `distill_state(id INTEGER PK CHECK(id=1), last_feedback_id INTEGER NOT NULL DEFAULT 0)`. 헬퍼 `add_rule(rule: str, source_ids: list[int]) -> int`, `list_rules(active_only=True) -> list[dict]`, `set_rule_active(rule_id, active: bool)`, `count_undistilled_feedback() -> int` (correction/down만, id > last_feedback_id), `mark_distilled()` (last_feedback_id = MAX(feedback.id)).
- `core.distill.distill(store, chat_fn, cfg=None) -> dict` — chat_fn(prompt, session_ref=None, cfg=None)→Iterator[dict] (provider.chat 시그니처). 미증류 correction/down 수집(각 항목: kind, payload, 원 질문 300자, 답변 300자; 최대 30건) + 기존 active 규칙 목록 → 스펙 프롬프트 → done.text에서 첫 `[` .. 매칭 `]` json.loads (실패 시 {"added": [], "error": "parse"}), 성공 시 각 {"rule","source_ids"} add_rule + mark_distilled → {"added": [rule...]}. 피드백 0건 → {"added": [], "skipped": "no new feedback"} (mark 안 함).
- fake_distill_claude.py: stream-json 형식으로 `{"type":"result","result":"[{\"rule\":\"가운뎃점 대신 쉼표를 쓴다\",\"source_ids\":[1]}]",...}` 출력. (KAIROS_CLAUDE_CMD 오버라이드용)

- [ ] Step 1: 실패 테스트 — test_distill.py: ① correction 2건 → distill(fake) → list_rules에 1건, count_undistilled 0 ② 피드백 없음 → skipped ③ fake가 "말로 설명…" 비JSON 출력(fake에 env FAKE_BAD=1 분기) → added 0, 규칙 0, mark 안 됨(count 유지) ④ set_rule_active(False) → list_rules(active_only) 제외 ⑤ up 피드백은 미증류 카운트에 미포함
- [ ] Step 2: FAIL → Step 3: 구현 → Step 4: 전체 회귀(75+5=80) → Step 5: Commit `feat(core): learned_rules store + LLM rule distillation`

---

### Task 2: server 라우트 + 주입 + 자동 트리거 (TDD)

**Files:** Modify `core/server.py`; Test `tests/test_server.py` (append)

**Interfaces:**
- `GET /rules` (authed) → {"rules": store.list_rules(active_only=False), "undistilled": N}
- `POST /rules` {id, active} → set_rule_active, {"ok": true}
- `POST /distill` → distill(state["store"], providers.get("claude").chat, cfg) 결과 그대로 (동시 실행 방지: threading.Lock non-blocking, 잠겨 있으면 409)
- build_prompt: rec에 `rules` 키 추가(recall이 아니라 server가 store.list_rules로 채움 — recall.py 시그니처 불변). `[학습된 규칙 — 항상 준수]` 블록을 최상단에. 캡 로직에 포함하되 규칙은 최근(id 큰) 것 우선 유지, 스니펫 먼저 감축(기존 우선순위 유지: 규칙>교정>회피>스니펫).
- /chat 끝(스트림 완료 후): learning_recall_enabled && count_undistilled_feedback() >= 10 → 데몬 스레드로 distill 1회(같은 Lock).
- 자동 트리거 임계값: 모듈 상수 `DISTILL_THRESHOLD = 10`, 테스트는 monkeypatch로 2로 낮춰 검증.

- [ ] Step 1: 실패 테스트 — append: ① correction 후 POST /distill(fake_distill_claude env) → rules 1건, GET /rules 반영 ② 이후 /chat argv 덤프에 "[학습된 규칙" 포함 ③ POST /rules로 비활성 → 다음 /chat 주입 제외 ④ threshold=2 monkeypatch + correction 2건 + /chat → (폴링 최대 3초) count_undistilled 0 확인(자동 증류)
- [ ] Step 2: FAIL → Step 3: 구현 → Step 4: 전체 회귀(80+4=84) → Step 5: Commit `feat(core): distill routes + learned-rules injection + auto trigger`

---

### Task 3: UI + 수용 검증

**Files:** Modify `app/src/api.ts`, `app/src/Settings.tsx`; README
- api.ts: Rule 타입 {id, rule, active, created_at}, getRules(), setRuleActive(id, active), runDistill().
- Settings.tsx "학습된 규칙" 섹션: 미증류 N건 표시, [지금 증류] 버튼(결과 added 수 표시), 규칙 목록 각각 활성 체크박스.
- 검증: npm build + 전체 pytest + headless 수용(완료 기준 1~4를 fake CLI로 curl 실증; 5는 Task 2 테스트 인용) → README "P3-2 검증 로그" → Commit.
