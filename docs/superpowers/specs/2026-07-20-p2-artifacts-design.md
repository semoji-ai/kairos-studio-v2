# Kairos Studio v2 — P2: 인라인 아티팩트 설계

날짜: 2026-07-20
상태: 승인됨 (사용자 "p3-2, p2, publish_agent 푸시까지 모두 진행")

## 목적

채팅 안에서 이미지·문서가 바로 보이게 한다. CLI 에이전트(claude/codex)가
워크스페이스에 만들거나 언급한 파일을 감지해 말풍선 안에 렌더.

## 원리 (P1 스펙의 "툴과 렌더는 한 몸" 원칙)

툴 실행은 CLI가 이미 함(파일 생성·이미지 생성 등). 스튜디오의 몫은
**결과물 감지 → 보존 → 렌더** 3단계다.

```
assistant 응답 텍스트
  → ① 감지: 텍스트에서 파일 경로 추출 (이미지 png/jpg/jpeg/webp/gif, 문서 md)
       - 절대 경로 + workspace_dir 상대 경로 해석, 실제 존재하는 파일만
       - 이미지 10MB·문서 1MB 초과 스킵, 메시지당 최대 6개
  → ② 보존: data_dir/artifacts/{message_id}/{filename}로 복사
       - 채팅 기록의 진실성: 원본이 나중에 수정·삭제돼도 당시 결과물 유지
  → ③ 저장: assistant content에 파트 추가
       {"type":"image","artifact":"{message_id}/{filename}"}
       {"type":"document","artifact":"{message_id}/{filename}","title":"파일명"}
  → ④ 서빙: GET /artifacts/{message_id}/{filename}
       - 인증: 정적 서빙과 동일하게 Host 검증만 (로컬 단일 사용자, <img>는
         Bearer 헤더 불가). 경로는 artifacts 루트에 감금(relative_to 검증)
  → ⑤ 렌더: UI가 image 파트→<img>, document 파트→접이식 카드(pre 텍스트)
```

## 감지 규칙 (core/artifacts.py)

- 정규식: 공백/따옴표/백틱 경계의 `[^\s"'` + "`" + `]+\.(png|jpe?g|webp|gif|md)` 후보 추출
- 해석 순서: 절대 경로 그대로 → cfg workspace_dir 기준 상대 → (미존재 시 스킵)
- 대소문자 무시 확장자. 중복 경로 1회. data_dir 내부 파일(자기 참조) 제외.
- `extract_artifacts(text, workspace_dir) -> list[Path]` 순수 함수 + 
  `collect(text, workspace_dir, data_dir, message_id) -> list[dict]` (복사+파트 생성)

## 서버 연결 (server.py `_chat`)

- provider done 후, assistant content 구성 시 `collect()` 결과 파트를 text 파트
  뒤에 추가. message_id가 필요하므로: add_message 먼저 → collect(mid) → 파트가
  있으면 messages.content_json UPDATE (store에 `append_parts(message_id, parts)`
  헬퍼 추가). done SSE에 `artifacts: N`.
- 실패(복사 불가 등)는 조용히 스킵 — 채팅 흐름을 깨지 않는다.

## UI (Chat.tsx)

- image 파트: `<img src={"/artifacts/" + p.artifact}>` (max-width 100%, 둥근 모서리)
- document 파트: `<details><summary>📄 {title}</summary><pre>{내용}</pre></details>`
  — 내용은 `GET /artifacts/...`를 fetch해 지연 로드(열 때 1회)
- 기존 textOf 렌더는 유지 (text 파트만)

## 완료 기준
1. 응답 텍스트에 존재하는 이미지 경로 → artifacts로 복사되고 content에 image
   파트, done SSE artifacts≥1 (fake CLI + 임시 파일로 실증)
2. GET /artifacts/... 로 이미지 바이트 서빙, 경로 탈출 시도는 404
3. md 경로 → document 파트 + 서빙
4. 미존재 경로·크기 초과는 무시 (채팅 정상 완료)
5. 원본 파일 삭제 후에도 채팅의 아티팩트는 서빙됨 (보존 실증)

## 제외 (YAGNI)
- 마크다운 리치 렌더링(단순 pre), 아티팩트 편집·버전, 이미지 생성 툴 내장
  (CLI 워크스페이스 스킬의 몫), 스트리밍 중 실시간 감지(done 후 일괄)
