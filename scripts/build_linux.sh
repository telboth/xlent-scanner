#!/usr/bin/env bash
# Bygger XLENT Compliance-scanner som en PyInstaller-bundle på Linux.
# Bruker samme struktur som build_mac.sh.
set -euo pipefail

PYTHON_EXE="${PYTHON_EXE:-}"
OUTPUT_ROOT="${OUTPUT_ROOT:-artifacts/linux/app}"
CLEAN="${CLEAN:-0}"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --python)       PYTHON_EXE="$2"; shift 2 ;;
    --output-root)  OUTPUT_ROOT="$2"; shift 2 ;;
    --clean)        CLEAN=1; shift ;;
    *)              echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${PYTHON_EXE}" ]]; then
  for candidate in "$REPO_ROOT/.venv/bin/python3" "$REPO_ROOT/.venv/bin/python"; do
    if [[ -x "$candidate" ]]; then PYTHON_EXE="$candidate"; break; fi
  done
  if [[ -z "${PYTHON_EXE}" ]]; then
    echo "Could not find Python in .venv. Run 'uv sync' first or set PYTHON_EXE." >&2
    exit 1
  fi
fi

command -v uv >/dev/null 2>&1 || { echo "Missing command: uv" >&2; exit 1; }

OUT_ROOT_ABS="$REPO_ROOT/$OUTPUT_ROOT"
BUILD_DIR="$OUT_ROOT_ABS/build"
DIST_DIR="$OUT_ROOT_ABS/dist"
SPEC_DIR="$OUT_ROOT_ABS/spec"
APP_NAME="XLENTScanner"
ENTRY_SCRIPT="$BUILD_DIR/entrypoint_build.py"

[[ "$CLEAN" == "1" && -d "$OUT_ROOT_ABS" ]] && rm -rf "$OUT_ROOT_ABS"
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
  \
  --collect-data xlent_scanner \
  --collect-data langdetect \
  --collect-all docling \
  --collect-all docling_core \
  --collect-data docling_ibm_models \
  \
  --hidden-import "webview.platforms.gtk" \
  \
  --hidden-import "docx" \
  --hidden-import "docx.oxml" \
  --hidden-import "docx.oxml.ns" \
  --hidden-import "docx.enum.text" \
  --hidden-import "docx.shared" \
  --hidden-import "pptx" \
  --hidden-import "pptx.util" \
  --hidden-import "pptx.enum" \
  --hidden-import "pptx.enum.text" \
  --hidden-import "pptx.dml.color" \
  --hidden-import "openpyxl" \
  --hidden-import "openpyxl.styles" \
  --hidden-import "openpyxl.utils" \
  --hidden-import "openpyxl.utils.exceptions" \
  \
  --hidden-import "langdetect" \
  --hidden-import "langdetect.detector" \
  --hidden-import "langdetect.detector_factory" \
  --hidden-import "langdetect.language" \
  --hidden-import "langdetect.utils.lang_detect_exception" \
  --hidden-import "langdetect.utils.unicode_block" \
  \
  --hidden-import "fitz" \
  \
  --hidden-import "xlent_scanner.model_manager" \
  --hidden-import "xlent_scanner.deep_scanner" \
  --hidden-import "spacy" \
  --hidden-import "spacy.lang.nb" \
  --hidden-import "spacy.lang.sv" \
  --hidden-import "spacy.lang.en" \
  \
  --exclude-module "torchvision" \
  \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --specpath "$SPEC_DIR" \
  "$ENTRY_SCRIPT"

APP_DIR="$DIST_DIR/$APP_NAME"
if [[ ! -d "$APP_DIR" ]]; then
  echo "Expected build output missing: $APP_DIR" >&2
  exit 1
fi

echo "Build complete: $APP_DIR"
