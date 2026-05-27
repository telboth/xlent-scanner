#!/usr/bin/env bash
set -euo pipefail

BUILD_APP_DIR="${BUILD_APP_DIR:-artifacts/macos/app/dist/XLENTScanner.app}"
INSTALLER_OUT_DIR="${INSTALLER_OUT_DIR:-artifacts/macos/installer}"
VERSION="${VERSION:-}"

if [[ "$#" -gt 0 ]]; then
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --app-dir)
        BUILD_APP_DIR="$2"
        shift 2
        ;;
      --out-dir)
        INSTALLER_OUT_DIR="$2"
        shift 2
        ;;
      --version)
        VERSION="$2"
        shift 2
        ;;
      *)
        echo "Unknown argument: $1" >&2
        exit 1
        ;;
    esac
  done
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "$VERSION" ]]; then
  VERSION="$(python3 - <<'PY'
import re
from pathlib import Path
text = Path("src/xlent_scanner/__init__.py").read_text(encoding="utf-8")
m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
if not m:
    raise SystemExit("Could not parse __version__")
print(m.group(1))
PY
)"
fi

APP_PATH="$REPO_ROOT/$BUILD_APP_DIR"
if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle missing: $APP_PATH. Run scripts/build_mac.sh first." >&2
  exit 1
fi

if ! command -v hdiutil >/dev/null 2>&1; then
  echo "hdiutil not found. package_mac.sh must run on macOS." >&2
  exit 1
fi

OUT_DIR="$REPO_ROOT/$INSTALLER_OUT_DIR"
mkdir -p "$OUT_DIR"

STAGING_DIR="$OUT_DIR/.dmg_staging"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

DMG_PATH="$OUT_DIR/xlent-scanner-macos-$VERSION.dmg"
rm -f "$DMG_PATH"

hdiutil create \
  -volname "XLENT Scanner" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

rm -rf "$STAGING_DIR"
echo "DMG created: $DMG_PATH"
