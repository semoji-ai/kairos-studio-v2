#!/usr/bin/env bash
# Build src-tauri/resources/ for a macOS release bundle.
#
# Produces:
#   src-tauri/resources/dist/            (app/dist build output)
#   src-tauri/resources/core/            (core/ minus __pycache__)
#   src-tauri/resources/publish_agent.zip (git archive snapshot of publish_agent HEAD)
#
# macOS release builds rely on the system /usr/bin/python3 (stdlib only), so
# unlike the Windows script this does NOT fetch an embeddable Python.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCES_DIR="$ROOT_DIR/src-tauri/resources"
PUBLISH_AGENT_REPO="${KAIROS_PUBLISH_AGENT_REPO:-$HOME/LocalProjects/publish_agent}"

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

echo "==> Done. Resources staged at $RESOURCES_DIR"
