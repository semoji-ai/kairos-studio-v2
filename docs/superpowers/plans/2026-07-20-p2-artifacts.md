# P2 인라인 아티팩트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 응답 속 파일 경로 감지 → data_dir/artifacts 보존 → content 파트 → /artifacts 서빙 → UI 렌더.
**Architecture:** 스펙 `docs/superpowers/specs/2026-07-20-p2-artifacts-design.md` 정본.

## Global Constraints
- Python stdlib only. 아티팩트 실패는 조용히 스킵(채팅 흐름 보호). 서빙 경로는 artifacts 루트 감금.
- 기존 86 테스트 그린. 커밋 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: core/artifacts.py + store.append_parts + 서버 연결 (TDD)

**Files:** Create `core/artifacts.py`; Modify `core/store.py`, `core/server.py`; Test `tests/test_artifacts.py`, `tests/test_server.py` (append)

**Interfaces:**
- `extract_artifacts(text, workspace_dir: str | None) -> list[Path]` — 스펙 감지 규칙(정규식·해석 순서·확장자 무시대소문자·중복 제거). 존재 검증 포함. data_dir 제외는 collect에서.
- `collect(text, workspace_dir, data_dir: Path, message_id: int) -> list[dict]` — 각 파일: 크기 검사(이미지 10MB/문서 1MB 초과 스킵), data_dir 내부 원본 스킵, `data_dir/artifacts/{message_id}/{filename}` 복사(shutil.copy2, 이름 충돌 시 `-2` 접미), 파트 dict 반환(스펙 형식). 최대 6개. 모든 예외 개별 스킵.
- store: `append_parts(message_id: int, parts: list[dict])` — content_json 로드→extend→UPDATE.
- server `_chat`: done 후 add_message → cfg workspace_dir로 collect → parts 있으면 append_parts → done SSE `"artifacts": len(parts)`.
- server `do_GET`: `/artifacts/` prefix → data_dir/artifacts 루트 감금 서빙(Host 검증만, Bearer 불요 — 정적과 동일 근거 주석). Content-Type: png/jpg/webp/gif/md 매핑. 탈출·미존재 404.
- data_dir 위치: server가 아는 현재 store 경로의 부모(`Path(state["store"]._path).parent`).

- [ ] Step 1: 실패 테스트 — test_artifacts.py: ① 텍스트 속 실재 png 절대경로 → extract 1건 ② workspace 상대경로 해석 ③ 미존재 스킵 ④ collect가 복사+파트 생성(image/document 타입 구분) ⑤ 크기 초과 스킵(11MB 더미) ⑥ 최대 6개 캡. test_server.py append: ⑦ fake CLI 응답에 임시 이미지 경로 포함 → /chat done artifacts==1 + messages content에 image 파트 + GET /artifacts/... 200 바이트 일치 ⑧ `/artifacts/../..` 경로 탈출 404 ⑨ 원본 삭제 후에도 서빙(보존).
  (fake 응답에 경로 넣기: fake_claude.py는 prompt를 에코하지 않으므로 새 fake `fake_echo_claude.py` — `-p` 인자 텍스트를 result로 그대로 출력 → 질문에 경로를 넣으면 응답에 경로가 포함됨.)
- [ ] Step 2: FAIL → Step 3: 구현 → Step 4: 전체 회귀(86+9=95) → Step 5: Commit `feat(core): artifact detection, preservation and serving`

---

### Task 2: UI 렌더 + 수용 검증

**Files:** Modify `app/src/api.ts`, `app/src/Chat.tsx`; README
- api.ts: Msg content 파트 타입에 `{type:"image"|"document", artifact?: string, title?: string}` 반영, done에 `artifacts?: number`.
- Chat.tsx: 버블 렌더를 파트 순회로 확장 — text는 기존, image는 `<img src={"/artifacts/"+p.artifact}>`(maxWidth "100%", borderRadius 8), document는 `<details>`+지연 fetch pre.
- 검증: npm build + pytest 95 + headless 수용(완료 기준 1~5 curl 실증, fake_echo 사용) → README "P2 검증 로그" → Commit.
