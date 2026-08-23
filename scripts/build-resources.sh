#!/usr/bin/env bash
# Build src-tauri/resources/ for a macOS release bundle.
#
# Produces:
#   src-tauri/resources/dist/            (app/dist build output)
#   src-tauri/resources/core/            (core/ minus __pycache__)
#   src-tauri/resources/publish_agent.zip (git archive snapshot of publish_agent HEAD)
#   src-tauri/resources/{ppt-master,codex-fleet}/ (presentation engines)
#
# macOS release builds rely on the system /usr/bin/python3 (stdlib only), so
# unlike the Windows script this does NOT fetch an embeddable Python.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCES_DIR="$ROOT_DIR/src-tauri/resources"
PUBLISH_AGENT_REPO="${KAIROS_PUBLISH_AGENT_REPO:-$HOME/LocalProjects/publish_agent}"
PPT_MASTER_REPO="${KAIROS_PPT_MASTER_REPO:-$(dirname "$ROOT_DIR")/ppt-master}"
CODEX_FLEET_REPO="${KAIROS_CODEX_FLEET_REPO:-$(dirname "$ROOT_DIR")/codex-fleet}"
PROMPT_KIT_REPO="${KAIROS_PROMPT_KIT_REPO:-$ROOT_DIR/vendor/gongnyang-prompt-kit}"
PPT_MASTER_COMMIT="68c690bbe2e170bca657c2dffd47434056cfabcd"
CODEX_FLEET_COMMIT="dc4d724d3c978077e406b4b3f0811bb0157094ad"
PROMPT_KIT_COMMIT="2d775df72aa03c9d00a699516a26c35e5d0f40db"

echo "==> Building app frontend (npm run build)"
(cd "$ROOT_DIR/app" && npm run build)

echo "==> Staging resources/dist"
rm -rf "$RESOURCES_DIR/dist"
mkdir -p "$RESOURCES_DIR"
cp -R "$ROOT_DIR/app/dist" "$RESOURCES_DIR/dist"

echo "==> Staging resources/core"
rm -rf "$RESOURCES_DIR/core"
mkdir -p "$RESOURCES_DIR/core"
(cd "$ROOT_DIR/core" && tar cf - --exclude='__pycache__' --exclude='*.pyc' .) | (cd "$RESOURCES_DIR/core" && tar xf -)

echo "==> Snapshotting publish_agent -> resources/publish_agent.zip"
if [ ! -d "$PUBLISH_AGENT_REPO/.git" ]; then
  echo "ERROR: publish_agent repo not found at $PUBLISH_AGENT_REPO (set KAIROS_PUBLISH_AGENT_REPO to override)" >&2
  exit 1
fi
rm -f "$RESOURCES_DIR/publish_agent.zip"
git -C "$PUBLISH_AGENT_REPO" archive --format=zip -o "$RESOURCES_DIR/publish_agent.zip" HEAD

echo "==> Staging resources/python-embed (placeholder — macOS uses system python3)"
# macOS release builds don't ship an embedded interpreter, but the Tauri
# resource glob "resources/python-embed/**/*" needs at least one matching
# file or the build fails with "path not found". A placeholder keeps the
# tauri.release.conf.json resource map identical across platforms.
rm -rf "$RESOURCES_DIR/python-embed"
mkdir -p "$RESOURCES_DIR/python-embed"
echo "macOS release builds use the system /usr/bin/python3; no embedded interpreter is bundled here." > "$RESOURCES_DIR/python-embed/README.txt"

echo "==> Staging presentation engines"
test -f "$PPT_MASTER_REPO/skills/ppt-master/SKILL.md" || {
  echo "ERROR: ppt-master not found at $PPT_MASTER_REPO" >&2; exit 1;
}
test -f "$CODEX_FLEET_REPO/runners/codex_imagegen_runner.py" || {
  echo "ERROR: codex-fleet not found at $CODEX_FLEET_REPO" >&2; exit 1;
}
test -f "$PROMPT_KIT_REPO/skills/image-prompt/SKILL.md" || {
  echo "ERROR: gongnyang-prompt-kit not found at $PROMPT_KIT_REPO" >&2; exit 1;
}
test "$(git -C "$PPT_MASTER_REPO" rev-parse HEAD)" = "$PPT_MASTER_COMMIT" || {
  echo "ERROR: ppt-master commit does not match presentation-engines.lock.json" >&2; exit 1;
}
test "$(git -C "$CODEX_FLEET_REPO" rev-parse HEAD)" = "$CODEX_FLEET_COMMIT" || {
  echo "ERROR: codex-fleet commit does not match presentation-engines.lock.json" >&2; exit 1;
}
test "$(git -C "$PROMPT_KIT_REPO" rev-parse HEAD)" = "$PROMPT_KIT_COMMIT" || {
  echo "ERROR: gongnyang-prompt-kit commit does not match presentation-engines.lock.json" >&2; exit 1;
}
rm -rf "$RESOURCES_DIR/ppt-master" "$RESOURCES_DIR/codex-fleet" "$RESOURCES_DIR/gongnyang-prompt-kit"
mkdir -p "$RESOURCES_DIR/ppt-master" "$RESOURCES_DIR/codex-fleet/runners" "$RESOURCES_DIR/gongnyang-prompt-kit"
cp -R "$PPT_MASTER_REPO/skills" "$RESOURCES_DIR/ppt-master/skills"
cp "$PPT_MASTER_REPO/LICENSE" "$RESOURCES_DIR/ppt-master/LICENSE"
python3 "$ROOT_DIR/scripts/patch-ppt-master-compat.py" "$RESOURCES_DIR/ppt-master"
cp "$CODEX_FLEET_REPO/runners/codex_imagegen_runner.py" "$RESOURCES_DIR/codex-fleet/runners/"
cp "$CODEX_FLEET_REPO/LICENSE" "$RESOURCES_DIR/codex-fleet/LICENSE"
cp -R "$PROMPT_KIT_REPO/skills" "$RESOURCES_DIR/gongnyang-prompt-kit/skills"
cp "$PROMPT_KIT_REPO/LICENSE" "$RESOURCES_DIR/gongnyang-prompt-kit/LICENSE"
cp "$ROOT_DIR/presentation-engines.lock.json" "$RESOURCES_DIR/"

echo "==> Installing presentation Python packages"
rm -rf "$RESOURCES_DIR/python-packages"
python3 -m pip install --disable-pip-version-check \
  --target "$RESOURCES_DIR/python-packages" \
  -r "$ROOT_DIR/requirements-presentation.txt"

# bible_documents.db 는 tauri.release.conf.json 이 "../bible_documents.db" 로
# 번들에 굽는 공통 읽기 전용 자산이다. 설치된 번들은 쓸 수 없으므로 관주
# 인덱스는 반드시 여기, 빌드 타임에 만들어 두어야 한다.
echo "==> Building verse cross-reference index into bible_documents.db"
if [ -f "$ROOT_DIR/bible_documents.db" ]; then
  python3 "$ROOT_DIR/scripts/build_verse_links.py"
else
  echo "WARN: bible_documents.db not found at $ROOT_DIR — skipping verse index" >&2
  echo "      (the tauri release build will fail on the missing bundle resource)" >&2
fi

echo "==> Done. Resources staged at $RESOURCES_DIR"
