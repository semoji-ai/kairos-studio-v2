# Kairos Studio v2 — P4: 원클릭 설치 설계

날짜: 2026-07-20
상태: 승인됨 (사용자 "원클릭 설치 해줘")

## 목표

비개발자(목사님)가 **인스톨러 하나**로 스튜디오+publish_agent를 쓰게 한다.
설치 후 첫 실행 마법사가 CLI 설치·로그인·작업 폴더를 안내한다.

## 번들 구성

```
인스톨러(.msi / .dmg)
├─ Kairos Studio 앱 (Tauri release)
├─ resources/
│   ├─ core/                  ← Python 사이드카 소스 (stdlib-only)
│   ├─ dist/                  ← SPA 빌드
│   ├─ python-embed/          ← Windows만: python.org 임베더블 배포판
│   └─ publish_agent.zip      ← main 스냅샷 (.git 제외)
```

## 프로덕션 경로 해석 (src-tauri)

현재 dev 전용(repo_root 기반)을 이중 모드로:
- `resolve_paths()` — dev(디버그 빌드): 기존 repo 경로. release: Tauri
  `resource_dir()` 기준 `resources/core`, `resources/dist`.
- Python 선택: Windows release → `resource_dir/python-embed/python.exe`;
  Windows dev → 기존 `.venv\Scripts\python.exe`; macOS → dev는 `.venv/bin/python`,
  release는 `/usr/bin/python3`(스탈립-only라 시스템으로 충분, 없으면 에러 다이얼로그).
- 사이드카 env: `KAIROS_STATIC_DIR=resources/dist`, DATA/CONFIG는 기존
  app_data_dir 그대로.

## 빌드 파이프라인 (scripts/)

- `scripts/build-resources.sh`(macOS)·`scripts/build-resources.ps1`(Windows):
  ① `cd app && npm run build` → `src-tauri/resources/dist`로 복사
  ② `core/` 복사(`__pycache__` 제외)
  ③ publish_agent 스냅샷 zip (git archive 또는 rsync exclude .git)
  ④ Windows만: 임베더블 Python 다운로드(버전 고정 3.12.x, SHA 검증)·해제
- `tauri.conf.json`에 `bundle.resources` 등록.
- 산출: macOS `cargo tauri build` → .dmg (파이프라인 검증용),
  Windows는 동일 스크립트를 윈도우 머신에서 1회 실행 → .msi.

## 첫 실행 마법사 (Setup 화면)

### 사이드카 라우트
- `GET /setup/status` (authed) → `{cli: <기존 /cli/status 결과>, workspace_dir,
  workspace_ready: bool(publish_agent 스킬 감지), all_ready: bool}`
  - all_ready = claude installed && authed && (workspace는 선택사항 — all_ready에
    미포함. 채팅만 하려면 CLI만 있으면 됨)
- `POST /setup/install-cli` → OS별 공식 설치 명령 실행(비대화):
  Windows `powershell -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"`,
  macOS `/bin/bash -c "curl -fsSL https://claude.ai/install.sh | bash"`.
  subprocess 완료 코드·출력 꼬리 반환(타임아웃 300s). 실패 시 수동 안내 문자열.
- `POST /setup/open-login` → OS 터미널에서 claude 로그인 세션 열기:
  Windows `cmd /c start cmd /k claude`, macOS `open -a Terminal` + 스크립트.
  (로그인은 대화형 — 앱이 대신 못 함, 터미널만 열어준다)
- `POST /setup/install-workspace` → 번들 `publish_agent.zip`(env
  `KAIROS_BUNDLE_DIR`로 위치 전달, Tauri가 세팅)을
  `~/Documents/publish-agent`(Windows `%USERPROFILE%\Documents`)에 해제(기존
  폴더 있으면 덮어쓰지 않고 그대로 사용) → settings.workspace_dir 지정 →
  `{workspace_dir, skills: N}` 반환.

### UI (Setup.tsx)
- 앱 시작 시 `GET /setup/status`: `all_ready==false`면 Setup 화면 먼저.
- 스텝 카드 3개: ① Claude 설치([설치하기] 버튼→install-cli, 진행 스피너)
  ② 로그인([터미널 열기]→open-login, [다시 확인] 버튼으로 status 재조회)
  ③ 설교 도우미(선택, [설치]→install-workspace, 성공 시 "스킬 N개 사용 가능"
  + 권한 acceptEdits 권장 안내와 [권한 올리기] 버튼=putSettings)
- all_ready 되면 [시작하기] → 채팅. 이후 실행에선 자동 스킵.

## 완료 기준
1. release 모드 경로 해석: 리소스 구조를 흉내낸 임시 디렉토리로 rust 단위 테스트
2. /setup/status·install-workspace가 headless 실증(zip 해제→workspace 지정→스킬 감지)
3. install-cli는 명령 구성만 단위 테스트(실 다운로드는 mock 커맨드 env 오버라이드)
4. macOS에서 build-resources.sh + `cargo tauri build` 성공, .dmg 산출·실행 확인
5. Windows 빌드 절차 문서화(docs/windows-build.md) — 실행은 사용자 윈도우 머신

## 제외
- 자동 업데이트, 코드사이닝/공증(추후), codex CLI 마법사(claude만 필수),
  church 브랜치 선택 UI(스냅샷은 main)
