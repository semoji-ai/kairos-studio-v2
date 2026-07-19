# Kairos Studio v2 — P3(1단계): 학습 루프 — 회상 + 피드백 주입 설계

날짜: 2026-07-19
상태: 승인됨 (사용자 확인. RAG 구조 설명 후 "구현우선 진행")

## 목적

대화가 쌓일수록 앱이 사용자를 알아가게 한다. 모델 가중치가 아니라 **컨텍스트
주입으로 학습** — provider(claude/codex)를 바꿔도 학습 자산이 유지된다.

## 구조 (확정)

### ① 색인 — 문자 bigram + SQLite FTS5
- 실측 근거: FTS5 trigram은 한국어 2글자 단어("설교") 매칭 실패. 문자 bigram을
  공백 결합한 색인문을 unicode61 토크나이저 FTS5에 저장하면 2글자도 정확 매칭.
- `messages_fts(message_id UNINDEXED, session_id UNINDEXED, role UNINDEXED, body)`
  — body는 bigram 색인문. 원문은 messages가 진실의 원천(변형 금지).
- `add_message`가 자동 색인. Store 초기화 시 미색인 과거 메시지 백필.
- bigram 규칙: 텍스트에서 한글·영숫자 시퀀스만 추출, 각 시퀀스를 2자 창으로
  슬라이드(1자 시퀀스는 그대로), 공백 결합. 질의도 동일 함수로 변환.

### ② 검색 — BM25 + 가중 재랭킹 (core/recall.py)
`recall(store, query, current_session_id, limit=3) -> list[snippet]`
- FTS5 BM25 후보 top-20 (user 메시지 매칭 중심, 짝 assistant 답변 동반 로드)
- 재랭킹 가중치:
  - 현재 세션 제외 (세션 내 기억은 CLI --resume 소관)
  - 해당 assistant 메시지에 up 피드백 → 점수 ×1.5
  - down 피드백 → 회상 후보에서 제외하고 "회피 신호" 목록으로 분리
  - 최신성: rowid 역순 소폭 가점(동점 타이브레이크 수준)
- snippet = `{q_text, a_text, date, score}` — q+a 쌍, 각 400자 절단.
- 반환 별도 채널: `avoid` 목록(down 답변 요지, 200자 절단, 최대 2건),
  `corrections` 목록(correction 피드백 payload + 원 질문 맥락, 최근+관련 최대 3건).

### ③ 주입 — 프롬프트 조립 (server _chat)
- `learning_recall_enabled`(설정, 기본 true)가 켜져 있고 결과가 있을 때만:

```
[과거 대화 참고 — 관련 있을 때만 활용]
(YYYY-MM-DD) Q: ... A: ...

[사용자 교정 이력 — 반드시 준수]
- ...

[회피 신호 — 이런 식의 답변은 거부된 적 있음]
- ...

---
{사용자 원문}
```
- 전체 주입 블록 1,500자 하드캡(초과 시 스니펫부터 감축). 결과 없으면 원문 그대로.
- 주입은 provider로 보내는 프롬프트에만 — **SQLite에 저장되는 user 메시지는
  원문 그대로** (학습 원료 오염 금지).
- SSE done 이벤트에 `recalled: N` (주입된 스니펫 수, 0이면 생략 가능) 추가.

### ④ 설정·UI
- settings: `learning_recall_enabled: true` (bool 화이트리스트 검증).
- Settings.tsx 라우팅·권한 섹션에 "학습 회상" 토글.
- Chat.tsx: done에 recalled>0이면 해당 답변 밑에 "🧠 과거 대화 N건 참조" 소자막.

## 완료 기준
1. 과거 세션에 있는 주제를 새 세션에서 물으면 provider 프롬프트에 [과거 대화
   참고] 블록이 포함된다 (fake CLI의 받은 prompt 캡처로 실증)
2. 한글 2글자 단어 질의로도 회상된다 (bigram 실증)
3. up 피드백 답변이 동점 후보보다 우선 회상, down 답변은 회피 신호로 분리
4. correction 피드백이 [사용자 교정 이력]으로 주입
5. 토글 off 시 주입 0 — 원문 그대로 전달
6. 저장된 user 메시지는 항상 원문 (주입 블록 미포함)

## 제외 (후속)
- 임베딩 시맨틱 검색 (recall() 인터페이스 고정으로 교체 용이하게만)
- LLM 규칙 증류(교정→명문 규칙), 세션 요약 색인, 설교 팩 자동 갱신
