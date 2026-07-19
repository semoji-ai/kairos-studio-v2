# P4 원클릭 설치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 인스톨러 하나 + 첫 실행 마법사. 스펙 `docs/superpowers/specs/2026-07-20-p4-one-click-install-design.md` 정본.

## Global Constraints
- Python stdlib only. 설치 명령은 env 오버라이드 가능(`KAIROS_CLI_INSTALL_CMD`, 테스트 mock용).
- dev 모드 동작 완전 보존(모든 기존 테스트 95 그린 + cargo 9).
- 커밋 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: 사이드카 setup 라우트 (TDD)

**Files:** Modify `core/server.py`, `core/settings.py`(불요 시 생략); Create `core/setup.py`; Test `tests/test_setup.py`

**Interfaces:**
- `core.setup.cli_install_command() -> list[str]` — env `KAIROS_CLI_INSTALL_CMD`(공백 분리) 우선, 기본은 OS별 스펙 명령(sys.platform 판정).
- `core.setup.open_login_command() -> list[str]` — env `KAIROS_LOGIN_CMD` 우선, 기본 OS별.
- `core.setup.install_workspace(bundle_dir: Path, dest_root: Path) -> dict` — bundle_dir/publish_agent.zip을 dest_root/publish-agent에 해제(이미 있으면 해제 스킵하고 그대로 사용), 반환 {"workspace_dir": str, "existed": bool}. zip 없으면 FileNotFoundError.
- server 라우트(authed):
  - `GET /setup/status` → {"cli": <기존 _cli_status 재사용>, "workspace_dir": settings, "workspace_ready": bool(스킬 디렉토리 감지 — 기존 workspace/info 로직 재사용), "all_ready": cli.claude.installed && cli.claude.authed}
  - `POST /setup/install-cli` → subprocess.run(cli_install_command(), timeout=300, capture) → {"ok": rc==0, "tail": 출력 끝 500자}
  - `POST /setup/open-login` → subprocess.Popen(open_login_command()) 발사 후 {"ok": true} (대기 안 함)
  - `POST /setup/install-workspace` → install_workspace(env KAIROS_BUNDLE_DIR, Documents 경로) → settings.save({"workspace_dir": ...}) → {"workspace_dir", "skills": N}
  - Documents 경로: `Path.home()/"Documents"` (존재 안 하면 home 직하).

- [ ] Step 1: 실패 테스트 — test_setup.py: ① cli_install_command env 오버라이드 ② install_workspace가 zip 해제+기존 폴더 보존(existed) ③ zip 없으면 에러. test_server.py append: ④ /setup/status 형태(all_ready 계산 — fake CLI라 installed true, authed는 fake `login status`... 기존 _cli_status의 fake 동작 확인해 기대값 맞춤) ⑤ /setup/install-cli를 KAIROS_CLI_INSTALL_CMD=`python -c "print('ok')"`로 → ok true ⑥ /setup/install-workspace: 임시 KAIROS_BUNDLE_DIR에 publish_agent.zip(스킬 1개 든 미니 zip을 테스트가 생성) → workspace_dir 지정 + skills≥1
- [ ] Step 2: FAIL → Step 3: 구현 → Step 4: 전체 회귀(95+6=101) → Step 5: Commit `feat(core): first-run setup routes`

---

### Task 2: Setup.tsx 마법사 + Tauri 경로 이중화

**Files:** Create `app/src/Setup.tsx`; Modify `app/src/App.tsx`, `app/src/api.ts`; Modify `src-tauri/src/lib.rs`, `src-tauri/src/sidecar.rs`, `src-tauri/tauri.conf.json`

**Interfaces:**
- api.ts: setupStatus(), installCli(), openLogin(), installWorkspace() (라우트 그대로).
- App.tsx: 최초 setupStatus() 호출 → all_ready false면 <Setup onDone={...}/> 렌더, true면 기존 Chat.
- Setup.tsx: 스펙의 스텝 카드 3개(설치/로그인+다시확인/설교 도우미 선택) + [시작하기].
- sidecar.rs: `python_path(repo_root, os)` → `python_path(base: &PathBuf, os, release: bool)` 형태로 확장(release: Windows는 base(=resource_dir)/python-embed/python.exe, macOS는 /usr/bin/python3). `sidecar_env`에 `KAIROS_BUNDLE_DIR`(resource_dir) 추가. 단위 테스트 갱신.
- lib.rs: `resolve_paths(app) -> (python, core_dir, static_dir, bundle_dir)` — `cfg!(debug_assertions)`로 dev/release 분기, release는 `app.path().resource_dir()`. spawn 시 core_dir을 cwd 또는 PYTHONPATH로 (python -m core가 리소스에서 동작하도록 `cmd.current_dir(core_dir 부모)`).
- tauri.conf.json: `bundle.resources`: ["resources/core/**/*", "resources/dist/**/*", "resources/publish_agent.zip", "resources/python-embed/**/*"] (없는 항목은 빌드 스크립트가 채움 — macOS엔 python-embed 없음: resources 글롭이 비어도 빌드 실패 않도록 확인, 실패하면 플랫폼별 conf 분리).

- [ ] Step 1: Setup.tsx+App.tsx+api.ts 작성 → `npm run build` 클린
- [ ] Step 2: rust 변경 + 단위 테스트(경로 분기, release python 경로) → `cargo test` 그린
- [ ] Step 3: dev 모드 무회귀: `cargo tauri dev` 수동 스모크는 컨트롤러 몫으로 보고만
- [ ] Step 4: Commit `feat: first-run setup wizard + production path resolution`

---

### Task 3: 빌드 파이프라인 + macOS 실빌드 + 문서

**Files:** Create `scripts/build-resources.sh`, `scripts/build-resources.ps1`, `docs/windows-build.md`; README

- build-resources.sh: 스펙 ①~③ (macOS — python-embed 스킵). ps1: ①~④(임베더블 python 3.12 고정 URL+SHA256 검증). 산출물은 `src-tauri/resources/` (gitignore 추가).
- publish_agent 스냅샷: `git -C ~/LocalProjects/publish_agent archive --format=zip -o .../publish_agent.zip HEAD` — 존재 안 하면 명확한 에러.
- macOS 검증: `./scripts/build-resources.sh && cd src-tauri && cargo tauri build` → .dmg/.app 산출 확인, .app 직접 실행해 사이드카 기동+채팅 1회(실 CLI) 확인 — 여기까지 컨트롤러(또는 서브에이전트가 headless로 .app 내 사이드카 실행 검증).
- docs/windows-build.md: 윈도우 머신 절차(사전물, ps1 실행, cargo tauri build, .msi 위치, 스모크 체크리스트 — 기존 windows-smoke.md 참조 갱신).
- README 갱신 + "P4 검증 로그".
- [ ] 실행 → 검증 → Commit `feat: installer build pipeline + windows build docs`
