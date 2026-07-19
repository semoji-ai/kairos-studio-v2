# Windows 릴리스 빌드 절차 (P4)

`scripts/build-resources.ps1` + `cargo tauri build`로 `.msi` 인스톨러를 만든다.
개발 모드 스모크는 `docs/windows-smoke.md` 참조 — 이 문서는 **릴리스 번들** 절차다.

## 사전 준비

- Rust (stable, MSVC toolchain) — https://rustup.rs
- Node 20+
- `cargo install tauri-cli --version "^2"` (또는 `cargo tauri --version`으로 이미 설치 확인)
- Python 3.12+ (개발 모드 `.venv` 및 `pytest` 실행용 — 릴리스 앱 자체는 번들된 embeddable
  Python을 쓰므로 별도 설치 불요하지만, 로컬 pytest/cargo test 회귀 확인엔 필요)
- git (embeddable Python 다운로드는 스크립트가 처리, `publish_agent` 스냅샷은 로컬에
  `%USERPROFILE%\LocalProjects\publish_agent`가 클론되어 있어야 함 — 경로는
  `KAIROS_PUBLISH_AGENT_REPO` 환경변수로 override 가능)

## 절차

```powershell
# 1. 저장소 루트에서 리소스 스테이징 (frontend build + core 복사 + publish_agent 스냅샷 + embeddable python)
powershell -ExecutionPolicy Bypass -File scripts\build-resources.ps1

# 2. 회귀 확인 (선택이지만 권장)
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
cd src-tauri
cargo test

# 3. 릴리스 번들 빌드
cargo tauri build --config tauri.release.conf.json
```

`scripts\build-resources.ps1`이 수행하는 일:
1. `app/` 에서 `npm run build` → `src-tauri/resources/dist`로 복사
2. `core/` 를 `__pycache__`/`.pyc` 제외하고 `src-tauri/resources/core`로 복사
3. `git -C <publish_agent repo> archive --format=zip -o src-tauri/resources/publish_agent.zip HEAD`
4. python.org에서 pinned 버전(3.12.7) embeddable amd64 zip을 받아 SHA256 검증 후
   `src-tauri/resources/python-embed`에 해제

## 산출물 위치

빌드가 끝나면 `.msi`는 아래 경로에 생성된다 (Tauri 버전 문자열은 `src-tauri/tauri.conf.json`
`version` 필드 기준):

```
src-tauri\target\release\bundle\msi\Kairos Studio_<version>_x64_en-US.msi
```

(WiX 대신 NSIS를 쓰도록 설정을 바꾸면 `bundle\nsis\*.exe`가 대신 생성된다 — 기본 설정은 `all`이라
설치된 번들러에 따라 둘 다 나올 수 있다.)

## 첫 실행 마법사 스모크 체크리스트

`.msi` 설치 후 앱을 처음 실행하면 `GET /setup/status`의 `all_ready`가 `false`일 때
Setup 화면이 뜬다. 아래를 순서대로 확인한다.

1. **CLI 설치 버튼**: [설치하기] 클릭 → 진행 스피너 → 완료 후 상태가 갱신되는지
   (실패 시 수동 안내 문구가 보이는지)
2. **로그인**: [터미널 열기] 클릭 → `cmd /k claude`가 새 콘솔 창으로 열리는지 →
   터미널에서 로그인 완료 후 [다시 확인] 클릭 → `authed: true`로 넘어가는지
3. **설교 도우미 설치(선택)**: [설치] 클릭 → `~\Documents\publish-agent`에 압축 해제되고
   "스킬 N개 사용 가능" 문구가 뜨는지; [권한 올리기] 버튼으로 `acceptEdits` 권장 안내가
   적용되는지
4. **시작하기**: `all_ready`가 true가 되면 [시작하기] → 채팅 화면 진입
5. **채팅 1회 + 한국어 확인**: 한국어로 질문 1회 보내 응답이 깨지지 않는지(UTF-8),
   토큰 스트리밍이 보이는지
6. **워크스페이스 스킬 동작**: 설교 도우미 워크스페이스를 지정한 상태에서 관련 스킬이
   호출되는 질문을 보내 스킬이 반영되는지
7. **재시작 스킵**: 앱을 껐다 다시 켰을 때 Setup 화면이 다시 뜨지 않고 바로 채팅으로
   진입하는지(`all_ready` 판정이 유지되는지)
8. **종료 정리**: 창을 닫은 뒤 작업 관리자에 사이드카 `python.exe` 프로세스가 남지 않는지
   (watchdog 확인 — `docs/windows-smoke.md`의 기존 체크와 동일)

이 문서의 절차는 macOS에서 문서화만 검증되었고(스크립트 구조가 `build-resources.sh`와
동일 3단계 + embeddable python 추가), **실제 실행은 Windows 머신에서 사용자가 1회
수행해야 한다** — `.msi` 산출과 위 체크리스트 결과를 이 저장소의 README "P4 검증 로그"에
추가 기록하는 것을 권장한다.

> **주의 — 스냅샷 신선도**: `publish_agent.zip`은 로컬 클론의 HEAD에서 만들어집니다.
> 인스톨러 빌드 전 `git -C <publish_agent 경로> pull`로 최신화하세요.
