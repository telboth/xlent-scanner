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

STAGING_PARENT="$(mktemp -d "${TMPDIR:-/tmp}/xlent-scanner-dmg.XXXXXX")"
STAGING_DIR="$STAGING_PARENT/staging"

cleanup() {
  rm -rf "$STAGING_PARENT"
}
trap cleanup EXIT

mkdir -p "$STAGING_DIR"

cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

DMG_PATH="$OUT_DIR/xlent-scanner-macos-$VERSION.dmg"
DMG_TMP="$(mktemp "$OUT_DIR/.xlent-scanner-macos-$VERSION.XXXXXX.dmg")"
rm -f "$DMG_PATH"
rm -f "$DMG_TMP"

create_dmg() {
  local attempt
  local status

  for attempt in 1 2 3; do
    rm -f "$DMG_TMP"
    if hdiutil create \
      -volname "XLENT Scanner" \
      -srcfolder "$STAGING_DIR" \
      -ov \
      -format UDZO \
      "$DMG_TMP"; then
      mv "$DMG_TMP" "$DMG_PATH"
      return 0
    else
      status=$?
    fi

    rm -f "$DMG_TMP"
    if [[ "$attempt" -eq 3 ]]; then
      return "$status"
    fi

    echo "hdiutil create failed (attempt $attempt/3, status $status). Retrying..." >&2
    sync || true
    sleep "$((attempt * 5))"
  done
}

create_dmg

echo "DMG created: $DMG_PATH"
