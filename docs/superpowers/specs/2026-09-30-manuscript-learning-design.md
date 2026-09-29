# Kairos Studio v2 — 원고 학습 메뉴 설계

날짜: 2026-09-30
상태: 승인됨 (사용자 "진행해" — 대화에서 5개 섹션 설계 확인)

## 목적

목사님이 직접 원고·참고자료 파일을 올려 퍼블리시 에이전트의 지식(위키)과
문체 프로필에 반영할 수 있게 한다. 지금은 대화로 스킬을 하나씩 불러야 하고
(`publish-collect` → `publish-absorb` → `publish-profile`), HWP는 들어가지 못하며
워드·PDF는 컴퓨터마다 pandoc·pdftotext 설치 여부에 따라 결과가 달라진다.

함께, 일반 대화에서 목사님이 말로 밝힌 지속적 선호("서론은 늘 짧게")가
규칙 **후보**로 올라오게 한다.

## 결정 사항 (사용자 확인)

| 질문 | 결정 |
|---|---|
| 학습 범위 | 위키 흡수 + 문체 프로필 갱신. 업로드 때 **목사님 원고 / 참고자료** 구분 |
| 참고자료 취급 | 흡수는 하되 **정말 참고용** — 목사님 입장·문체로 섞이지 않게 |
| 실행 시점 | 올리면 변환 → 목록 확인 → **[학습 시작]** 버튼 |
| 대화 규칙 | 규칙 **후보**로 뽑고 목사님이 켜야 반영 |
| 파이프라인 | **B안** — 변환·수집은 Kairos(파이썬), 흡수·프로필은 Claude |

B안 선택 이유: 수집(프론트매터·해시·파일명)은 결정적 작업이라 Claude가 원고를
한 편씩 읽을 필요가 없다. 수십 편 업로드에서 시간·사용량을 흡수에만 쓴다.
대가는 raw entry 형식을 두 저장소가 함께 안다는 점 — 스키마 준수 테스트로 막는다.

## 1. 화면 — 사이드바 '원고 학습'

- 메뉴 타일: 도자기 세트와 같은 그림체로 1장 추가 생성(Codex `$imagegen`, 공냥 규격).
- **파일 칸**: 여러 파일 끌어놓기/선택. `.hwp .hwpx .docx .pdf .md .markdown .txt`.
- **확인 목록** (올리면 즉시 변환 결과 표시), 파일마다:
  - 제목(수정 가능), 글자 수, 본문 앞부분 미리보기
  - 구분 선택: 목사님 원고(기본) / 참고자료
  - 상태: `ok` · `duplicate`(이미 학습한 원고 — 기존 source_id 안내) ·
    `empty`(글자 거의 없음, 스캔 PDF 추정 — OCR 필요 안내) · `error`(변환 실패 사유)
  - `ok` 외 상태는 자동 제외, `ok`도 개별 제외 가능
- **[학습 시작]** → 작업 카드: 단계·경과·작업 로그. 앱 재시작 후에도 기록 유지
  (PPT 작업과 같은 방식).
- 선행 조건 미충족 시 메뉴 본문 대신 안내:
  - 작업 폴더 미설정 → "설정에서 작업 폴더를 지정하세요"
  - `config.yaml` 없음 → "대화에서 /publish-setup 으로 워크스페이스를 먼저 초기화하세요"

## 2. 변환·수집 — `core/manuscripts.py` (신규, Claude 사용 없음)

### 변환
- `core/presentations.py` 의 `normalize_document` 계열 추출기(docx/hwpx/hwp/pdf)를
  공용 모듈 `core/doc_convert.py` 로 옮기고 PPT와 원고 학습이 함께 쓴다.
  PPT 쪽 동작은 바꾸지 않는다(기존 테스트 그대로 통과).
- `.md/.markdown/.txt` 는 그대로 읽는다(UTF-8, BOM 제거, 실패 시 cp949 재시도).

### 스테이징 (업로드 → 확인 목록)
- 업로드 파일은 `{workspace}/raw/sources/_staging/{upload_id}/` 에 원본 저장,
  변환 결과는 같은 폴더의 `.md`. 목록 확인 전에는 `raw/entries/` 를 건드리지 않는다.
- 상태 판정:
  - `empty`: 정제 본문의 공백 제외 글자 수 < 200
  - `duplicate`: `content_hash` 가 기존 `raw/entries/*.md` 중 하나와 같음, 또는 같은 업로드 안의 앞선 파일과 같음

### 기록 (학습 시작 시) — publish-collect 규칙 준수
`publish_agent/skills/publish-collect/SKILL.md`, `references/format-handling.md`,
`shared/references/workspace-schema.md` 의 raw entry 스키마를 따른다.

- 파일명 `raw/entries/{YYYYMMDD}_{source_id}.md`
- `source_id: src_{YYYYMMDD}_{NNN}` — 같은 날 기존 번호 다음부터
- `batch_id: batch_{YYYYMMDD}` — 같은 날 재사용
- `type: primary | reference` (화면 선택값)
- `category`: 제목·본문 규칙 판정(설교·강해·주일·수요 → `sermon`, 그 외 `book`/`essay`/`article`,
  참고자료 기본 `article`)
- `author`: primary는 `config.yaml` 의 `author.name`, reference는 빈 문자열
- `source_path`: 보관 원본 경로(`raw/sources/{YYYYMMDD}/{파일명}`, `/` 구분자)
- `ingested_at`, `confidence`(docx/md/txt `high`, hwp/hwpx/pdf `medium`),
  `tags: []`, `absorbed: false`, `deleted: false`
- `content_hash`: 정규화(① `\r\n`→`\n` ② 앞뒤 공백 제거 ③ 빈 줄 3개 이상→2개
  ④ 탭→공백 4) 후 `sha256:` + hex
- 500줄 초과: 자연 분할점(`#` 제목 → 빈 줄 문단)으로 나눠 파트별 entry,
  `parent_source_id/part/total_parts/part_title` 기록. 2000줄 이상은 파트당 최대 500줄.
- 원본은 `raw/sources/{YYYYMMDD}/` 로 옮기고 스테이징 폴더를 지운다.

## 3. 학습 작업 — `LearningManager` (PresentationManager 패턴)

- 작업 상태 파일: `{data_dir}/learning/{job_id}/status.json`
  (`queued → absorbing → profiling → completed | failed`, 진행 로그, 배치·항목 수).
- 실행: 작업 폴더를 cwd로 claude provider를 백그라운드 스레드에서 호출.
  - 프롬프트 1: `/publish-absorb` — 이번 배치(batch_id·source_id 목록)를 흡수.
  - 프롬프트 2(이번 배치에 primary가 1건 이상일 때만): `/publish-profile` 증분 갱신.
  - 이 작업에서만 `claude_permission_mode=acceptEdits` 로 실행(흡수는 파일을 써야 함).
    전역 설정은 바꾸지 않는다.
- 흡수 스킬이 실행 전 스냅샷을 만들므로 되돌리기는 스킬의 롤백 절차를 따른다.
- 앱 재시작 시 `absorbing/profiling` 에 멈춘 작업은 `failed`("앱 종료로 중단") 로 표시하고
  [다시 시도] 버튼을 준다(이미 흡수된 항목은 스킬이 `absorbed: true` 로 건너뜀).

### API (모두 Bearer 인증)
| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/learning/status` | 선행 조건(작업 폴더·config.yaml) + 작업 목록 |
| POST | `/learning/uploads` | multipart 파일들 → 변환·판정 결과 목록 |
| POST | `/learning/jobs` | `{upload_id, items:[{name,title,type,include}]}` → 기록 + 작업 시작 |
| POST | `/learning/jobs/{id}/retry` | 실패 작업 재시도 |
| DELETE | `/learning/uploads/{id}` | 스테이징 취소 |

## 4. 참고자료는 정말 참고용 — publish_agent 수정

- `publish-write/SKILL.md`, `publish-sermon/SKILL.md` 에 규칙 추가:
  - `wiki/references/` 기사와 `type: reference` 원문은 **출처를 밝힌 인용·요약**으로만 쓴다.
  - 참고자료 내용을 목사님의 신학적 입장·고백·문장으로 바꿔 쓰지 않는다.
  - 문체(어미·호칭·리듬)는 오직 sermon-pack(primary 기반)을 따른다.
- `publish-absorb`·`publish-profile` 은 이미 primary/reference 를 구분하므로 변경 없음.
- publish_agent main 에 커밋 → 설정의 [스킬 갱신]으로 각 컴퓨터에 전달.

## 5. 대화에서 규칙 후보

- `learned_rules` 에 `pending INTEGER NOT NULL DEFAULT 0` 추가(기존 DB는 ALTER 로 이관).
  - 후보: `pending=1, active=0` → 설정 '학습된 규칙'에 '후보' 표시, 켜면 `pending=0, active=1`.
  - 👎·원고 수정에서 나온 규칙은 지금처럼 `pending=0, active=1`.
- 증류 입력 확장(`core/distill.py`):
  - `distill_state` 에 `last_message_id` 추가. 그 이후의 **목사님(user) 메시지** 중
    지속 지시 표지(`앞으로|항상|늘|매번|계속|기억해|원칙|하지 ?마|말아|지 말고`)가 있는
    문장만 최대 20개 수집(각 300자).
  - LLM 프롬프트에 "대화 지시" 목록을 별도 구획으로 넣고, 그 구획에서 나온 규칙은
    `from: "conversation"` 으로 표시하게 한다 → `pending=1` 로 저장.
  - 일회성 요청 배제 지침: "이번 원고에만 해당하는 요청은 규칙으로 만들지 않는다".
- 자동 증류 문턱: 미증류 피드백 + 미증류 지시 문장 합계 ≥ 10 (기존 `DISTILL_THRESHOLD`).
- 파싱 실패 시 저장 0건(기존 날조 방지 원칙 유지).

## 범위 밖

- 대화 RAG용 `corpus-manifest.json` 갱신 — 교회 컴퓨터의 실제 파일 형식 확인 후 별도 작업.
- 스캔 PDF OCR, 리디바탕 글꼴.

## 테스트

- `tests/test_manuscripts.py`
  - 형식별 변환(md/txt/docx/hwpx/pdf, hwp는 변환기 없으면 `error` 사유)
  - 해시 정규화 4단계가 규칙과 같은지, 파일명·source_id·batch_id 번호 이어가기
  - 프론트매터가 스키마의 필수 키를 모두 갖는지(스키마 준수 테스트)
  - 중복(기존 entries·같은 업로드 내) 판정, `empty` 판정, 500줄 분할과 파트 필드
  - 원본 이동·스테이징 정리, `config.yaml` 저자명 반영
- `tests/test_learning_jobs.py` — 가짜 claude로 상태 전이, primary 없을 때 profile 생략,
  실패·재시작 복구, acceptEdits 가 이 작업에만 적용되는지
- `tests/test_server.py` — 새 경로 인증·업로드·작업 생성
- `tests/test_distill.py`·`tests/test_store.py` — 지시 문장 수집, `pending` 저장·켜기, DB 이관
- 화면: 원고 학습(빈 상태·확인 목록·진행 중) 밝은/다크 캡처
- 머지 전 3종 체크
