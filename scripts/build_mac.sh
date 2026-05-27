#!/usr/bin/env bash
set -euo pipefail

PYTHON_EXE="${PYTHON_EXE:-}"
OUTPUT_ROOT="${OUTPUT_ROOT:-artifacts/macos/app}"
CLEAN="${CLEAN:-0}"

if [[ "$#" -gt 0 ]]; then
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --python)
        PYTHON_EXE="$2"
        shift 2
        ;;
      --output-root)
        OUTPUT_ROOT="$2"
        shift 2
        ;;
      --clean)
        CLEAN=1
        shift
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

if [[ -z "${PYTHON_EXE}" ]]; then
  if [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then
    PYTHON_EXE="$REPO_ROOT/.venv/bin/python3"
  elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON_EXE="$REPO_ROOT/.venv/bin/python"
  else
    echo "Could not find Python in .venv. Run 'uv sync' first or set PYTHON_EXE." >&2
    exit 1
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing command: uv" >&2
  exit 1
fi

OUT_ROOT_ABS="$REPO_ROOT/$OUTPUT_ROOT"
BUILD_DIR="$OUT_ROOT_ABS/build"
DIST_DIR="$OUT_ROOT_ABS/dist"
SPEC_DIR="$OUT_ROOT_ABS/spec"
APP_NAME="XLENTScanner"
ENTRY_SCRIPT="$BUILD_DIR/entrypoint_build.py"

if [[ "$CLEAN" == "1" && -d "$OUT_ROOT_ABS" ]]; then
  rm -rf "$OUT_ROOT_ABS"
fi

mkdir -p "$BUILD_DIR" "$DIST_DIR" "$SPEC_DIR"

cat > "$ENTRY_SCRIPT" <<'PY'
from xlent_scanner.app import main

if __name__ == "__main__":
    main()
PY

uv pip install --python "$PYTHON_EXE" "pyinstaller>=6.0.0" "pyinstaller-hooks-contrib>=2024.0"

"$PYTHON_EXE" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --paths "$REPO_ROOT/src" \
  --collect-data xlent_scanner \
  --hidden-import webview.platforms.cocoa \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --specpath "$SPEC_DIR" \
  "$ENTRY_SCRIPT"

APP_PATH="$DIST_DIR/$APP_NAME.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Expected app bundle missing: $APP_PATH" >&2
  exit 1
fi

echo "Build complete: $APP_PATH"
