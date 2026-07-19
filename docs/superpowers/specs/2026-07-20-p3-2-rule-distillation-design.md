# Kairos Studio v2 — P3-2: 규칙 증류 설계

날짜: 2026-07-20
상태: 승인됨 (사용자 "p3-2, p2, publish_agent 푸시까지 모두 진행")

## 목적

쌓인 피드백(교정·👎)을 LLM이 **명문화된 규칙**으로 증류해, raw 이력 주입보다
압축적이고 일관된 학습을 만든다. "이 사용자는 가운뎃점 대신 쉼표를 원한다"처럼.

## 구조

### 저장 (store)
```sql
learned_rules(
  id INTEGER PK, rule TEXT NOT NULL,          -- 명문화된 규칙 한 문장
  source TEXT NOT NULL DEFAULT '',            -- 근거 feedback id들 JSON 배열
  active INTEGER NOT NULL DEFAULT 1,          -- 0이면 주입 안 함
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
```
헬퍼: `add_rule(rule, source_ids) -> id`, `list_rules(active_only=True)`,
`set_rule_active(id, active)`, `count_undistilled_feedback()` — 마지막 증류 이후
새 correction/down 피드백 수 (distill_state 테이블에 last_feedback_id 기록).

### 증류 실행 (core/distill.py)
- `distill(store, provider_chat) -> {"added": [...], "skipped": reason?}`
- 입력: 미증류 correction/down 피드백(+ 해당 원 질문·답변 맥락, 각 300자 절단,
  최대 30건) + 기존 active 규칙 목록(중복 방지용).
- provider_chat = claude provider의 chat 함수(구독 자원, cfg의 permission 그대로).
  프롬프트: "다음 피드백들에서 사용자의 명시적 선호 규칙을 추출하라. 기존 규칙과
  중복되지 않는 것만. 각 규칙은 한 문장, 최대 5개. JSON 배열만 출력:
  [{\"rule\": ..., \"source_ids\": [...]}]"
- 응답 파싱: 텍스트에서 첫 JSON 배열 추출(json.loads, 실패 시 대괄호 슬라이스
  재시도). 파싱 실패 → added 없이 에러 반환(저장 안 함 — 날조 방지).
- 피드백 0건이면 skipped="no new feedback".

### 트리거
- 수동: `POST /distill` (authed) → 증류 실행, 결과 반환.
- 자동: /chat 처리 끝에 `count_undistilled_feedback() >= 10`이면 백그라운드
  스레드로 증류 1회 (동시 실행 방지 플래그).

### 주입 (build_prompt 확장)
- `[학습된 규칙 — 항상 준수]` 블록을 교정 이력보다 앞에, active 규칙 전부
  (한 줄씩, 개행 정규화). 블록 캡 1,500자에 포함 — 규칙이 크면 최근 규칙 우선.
- learning_recall_enabled 토글이 규칙 주입도 함께 제어.

### UI (Settings)
- "학습된 규칙" 섹션: 규칙 목록 + 각 규칙 활성 토글 + [지금 증류] 버튼
  (`POST /distill`) + 미증류 피드백 수 표시(`GET /rules` 응답에 포함).
- `GET /rules` → {rules: [{id, rule, active, created_at}], undistilled: N}
- `PUT /rules/{id}`는 라우트 단순화를 위해 `POST /rules` {id, active}로.

## 완료 기준
1. correction 피드백 후 POST /distill → learned_rules에 규칙 저장 (fake CLI로
   JSON 응답 재현)
2. 이후 /chat의 provider 프롬프트에 [학습된 규칙] 블록 포함
3. 규칙 비활성화 → 주입 제외
4. 파싱 실패 시 규칙 저장 0 (날조 방지)
5. 피드백 10건 누적 시 자동 증류 트리거 (테스트는 임계값 주입으로)

## 제외
- 규칙 편집 UI(활성/비활성만), 규칙 간 충돌 해소, up 피드백 증류(교정·down만)
