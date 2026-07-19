# P3(1단계) 학습 회상 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** 대화 bigram-FTS 색인 → 가중 회상 → 프롬프트 주입 → 피드백 신호 반영 → 설정 토글 + UI 표시.

**Architecture:** 스펙 `docs/superpowers/specs/2026-07-19-p3-learning-recall-design.md`가 정본. store에 FTS 레이어, 신규 core/recall.py, server 주입, settings 1키, UI 소폭.

## Global Constraints
- Python stdlib only (FTS5는 내장 sqlite3 — 가용성은 이미 실측됨).
- 저장되는 user 메시지는 항상 원문 — 주입 블록은 provider 전달 프롬프트에만.
- 주입 블록 총 1,500자 하드캡. 현재 세션은 회상에서 제외.
- 기존 테스트(58 python) 전부 그린 유지. 커밋 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: store FTS 색인 + core/recall.py (TDD)

**Files:** Modify `core/store.py`; Create `core/recall.py`; Test `tests/test_recall.py`

**Interfaces:**
- `core.recall.bigrams(text: str) -> str` — 한글·영숫자 시퀀스만 추출(`re.findall(r"[가-힣A-Za-z0-9]+")`), 각 시퀀스를 2자 슬라이딩 창(len<2면 그대로), 전부 공백 결합. 예: `"설교 문체!"` → `"설교 문체"`, `"목사님"` → `"목사 사님"`.
- store.py: `_SCHEMA`에 `CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(body, message_id UNINDEXED, session_id UNINDEXED, role UNINDEXED)`. `add_message`가 content의 text 파트 결합문을 bigrams()로 변환해 색인. `Store.__init__`에서 백필: `messages`에 있고 `messages_fts`에 없는 message_id 색인.
- `core.recall.recall(store, query, current_session_id, limit=3) -> dict`
  반환: `{"snippets": [{"q_text","a_text","date","score"}], "avoid": [str], "corrections": [str]}`
  - FTS `bm25(messages_fts)` 후보 top-20 (role='user' 매칭 위주 + 그 다음 assistant 답변을 messages에서 로드)
  - 현재 세션 제외, up 피드백 ×1.5, down 답변은 snippets 제외+avoid로(200자), corrections는 feedback 테이블에서 관련(FTS 매칭 세션) + 최근 순 최대 3건
  - q/a 각 400자 절단. store 접근은 기존 공개 API + `store._conn()` 직접 질의 허용(같은 패키지).
- store에 헬퍼 추가: `feedback_for_message(message_id) -> list[dict]`, `list_corrections(limit=20) -> list[dict]` (message_id의 세션·원질문 조인 포함).

- [ ] **Step 1: 실패하는 테스트** — tests/test_recall.py:

```python
import pytest

from core.recall import bigrams, recall
from core.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "r.db")


def _conv(store, sid, q, a):
    store.add_message(sid, "user", [{"type": "text", "text": q}])
    return store.add_message(sid, "assistant", [{"type": "text", "text": a}],
                             provider="claude")


def test_bigrams_korean_two_char():
    assert bigrams("설교") == "설교"
    assert bigrams("목사님") == "목사 사님"
    assert bigrams("설교 문체!") == "설교 문체"


def test_recall_finds_past_session_with_two_char_query(store):
    s1 = store.create_session("과거")
    _conv(store, s1, "설교 준비를 도와줘", "네, 본문을 알려주세요")
    s2 = store.create_session("현재")
    out = recall(store, "설교 어떻게 하지", current_session_id=s2)
    assert out["snippets"] and "설교 준비" in out["snippets"][0]["q_text"]


def test_recall_excludes_current_session(store):
    s1 = store.create_session("현재")
    _conv(store, s1, "설교 준비를 도와줘", "네")
    out = recall(store, "설교", current_session_id=s1)
    assert out["snippets"] == []


def test_upvote_boosts_downvote_avoids(store):
    s1 = store.create_session("a")
    up_mid = _conv(store, s1, "썸네일 스타일 추천", "3등신 chibi 스타일")
    s2 = store.create_session("b")
    down_mid = _conv(store, s2, "썸네일 스타일 골라줘", "디즈니 베이스로 하세요")
    store.add_feedback(up_mid, "up")
    store.add_feedback(down_mid, "down")
    s3 = store.create_session("c")
    out = recall(store, "썸네일 스타일", current_session_id=s3)
    texts = [s["a_text"] for s in out["snippets"]]
    assert any("chibi" in t for t in texts)
    assert not any("디즈니" in t for t in texts)      # down은 snippets에서 제외
    assert any("디즈니" in a for a in out["avoid"])   # avoid로 분리


def test_corrections_surface(store):
    s1 = store.create_session("a")
    mid = _conv(store, s1, "원고 써줘", "가운뎃점·을 씁니다")
    store.add_feedback(mid, "correction", "가운뎃점 대신 쉼표를 써라")
    s2 = store.create_session("b")
    out = recall(store, "원고 작성", current_session_id=s2)
    assert any("쉼표" in c for c in out["corrections"])


def test_backfill_indexes_existing_messages(tmp_path):
    db = tmp_path / "b.db"
    s = Store(db)
    sid = s.create_session("x")
    # FTS를 우회해 원본만 삽입한 상황을 흉내내기 어렵므로: 새 Store 인스턴스가
    # 깨진 색인 없이 동작하는지(중복 색인 없이 검색 정상)를 검증
    _conv(s, sid, "레오파드 렌더 배치", "네")
    s2 = Store(db)  # 재오픈 = 백필 경로 실행
    out = recall(s2, "레오파드", current_session_id=999)
    assert len(out["snippets"]) == 1  # 중복 색인 없음
```

- [ ] **Step 2: FAIL 확인** — `.venv/bin/python -m pytest tests/test_recall.py -q`
- [ ] **Step 3: 구현** (Interfaces 대로; FTS MATCH 질의는 bigrams(query)를 `"` 구문으로 감싸 OR 조합: 각 bigram 토큰을 `token OR token ...`으로. 결과 0건이면 빈 dict 반환)
- [ ] **Step 4: PASS + 전체 회귀** — 전체 `.venv/bin/python -m pytest -q` (58+6=64)
- [ ] **Step 5: Commit** `feat(core): bigram FTS index + weighted recall`

---

### Task 2: server 주입 + settings 토글 (TDD)

**Files:** Modify `core/server.py`, `core/settings.py`; Test `tests/test_server.py`, `tests/test_settings.py` (append)

**Interfaces:**
- settings: DEFAULTS `"learning_recall_enabled": True`, _validate bool 검사.
- server `_chat`: cfg 로드 후, `cfg.get("learning_recall_enabled", True)`면
  `recall(state["store"], text, session_id)` 실행 → 스펙 ③ 형식으로 주입 프롬프트 조립
  (`build_prompt(text, rec) -> (prompt, n_snippets)` 를 server 모듈 함수로 분리, 1,500자 캡 로직 포함 — 캡 초과 시 snippets 뒤에서부터 제거).
  provider.chat(조립본, ...), **store.add_message에는 원문 text** (기존 코드가 이미 원문 저장 — 순서 유지).
  done SSE에 `"recalled": n_snippets` 포함 (0이어도 포함, UI가 판단).
- 라우팅(route())은 원문 기준 — 주입 전 텍스트로 판정 (기존 코드 순서상 자연 충족, 테스트로 고정).

- [ ] **Step 1: 실패하는 테스트** — tests/test_server.py append:

```python
def test_chat_injects_recall_from_past_session(srv):
    url, store = srv
    done1 = _sse_events(_req(url, "/chat", {"text": "설교 준비를 도와줘"}))[-1]
    ev = _sse_events(_req(url, "/chat", {"text": "설교 이어서 하자"}))  # 새 세션
    done2 = ev[-1]
    assert done2["recalled"] >= 1
    # fake_claude는 받은 prompt를 그대로 알 수 없으므로 fake_argv_dump로 재검:
    # (아래 별도 테스트에서 argv 캡처로 주입 실증)


def test_injection_reaches_provider_but_not_db(srv, tmp_path, monkeypatch):
    url, store = srv
    _sse_events(_req(url, "/chat", {"text": "레오파드 렌더 방법 알려줘"}))
    monkeypatch.setenv("KAIROS_CLAUDE_CMD",
                       f"{sys.executable} {FAKES/'fake_argv_dump.py'}")
    done = _sse_events(_req(url, "/chat", {"text": "@claude 레오파드 얘기 다시"}))[-1]
    msgs = json.load(_req(url, f"/messages?session_id={done['session_id']}"))["messages"]
    # DB의 user 원문에는 주입 블록 없음
    assert "[과거 대화 참고" not in msgs[0]["content"][0]["text"]
    # provider가 받은 argv(-p 값)에는 주입 블록 있음
    argv_text = msgs[1]["content"][0]["text"]
    assert "[과거 대화 참고" in argv_text and "레오파드 얘기 다시" in argv_text


def test_recall_toggle_off(srv):
    url, _ = srv
    _sse_events(_req(url, "/chat", {"text": "설교 준비를 도와줘"}))
    json.load(_req(url, "/settings", {"learning_recall_enabled": False}, method="PUT"))
    done = _sse_events(_req(url, "/chat", {"text": "설교 이어서"}))[-1]
    assert done["recalled"] == 0
```

tests/test_settings.py append:
```python
def test_learning_recall_flag_validation():
    settings.save({"learning_recall_enabled": False})
    with pytest.raises(ValueError):
        settings.save({"learning_recall_enabled": "yes"})
```

- [ ] **Step 2: FAIL** → **Step 3: 구현** → **Step 4: 전체 회귀 (64+4=68)** → **Step 5: Commit** `feat(core): recall injection into chat + learning toggle`

---

### Task 3: UI + 수용 검증

**Files:** Modify `app/src/Chat.tsx`, `app/src/api.ts`, `app/src/Settings.tsx`; README

- api.ts ChatEvent done에 `recalled?: number`. Chat.tsx: done 시 recalled를 메시지 로컬 상태에 기록, assistant 버블 하단 provider 옆에 recalled>0이면 `🧠 과거 대화 N건 참조`. Settings.tsx 라우팅·권한 섹션에 "학습 회상(과거 대화 참조)" 체크박스(learning_recall_enabled).
- 검증: `npm run build` + 전체 pytest + headless 수용(스펙 완료 기준 1·2·5를 curl로, 3·4는 Task 1-2 테스트 결과 인용) → README "P3-1 검증 로그" → Commit.
