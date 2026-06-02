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
  --argv-emulation \
  --name "$APP_NAME" \
  --osx-bundle-identifier "no.xlent.xlent-scanner" \
  --paths "$REPO_ROOT/src" \
  \
  --collect-data xlent_scanner \
  --collect-data langdetect \
  --collect-all docling \
  --collect-all docling_core \
  --collect-data docling_ibm_models \
  \
  --hidden-import "webview.platforms.cocoa" \
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
  --hidden-import "spacy.lang.de" \
  --hidden-import "spacy.lang.fr" \
  --hidden-import "spacy.lang.es" \
  --hidden-import "spacy.lang.da" \
  \
  --exclude-module "torchvision" \
  \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --specpath "$SPEC_DIR" \
  "$ENTRY_SCRIPT"

APP_PATH="$DIST_DIR/$APP_NAME.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Expected app bundle missing: $APP_PATH" >&2
  exit 1
fi

APP_PLIST="$APP_PATH/Contents/Info.plist"
python3 - "$APP_PLIST" <<'PY'
import plistlib
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
with plist_path.open("rb") as f:
    plist = plistlib.load(f)

supported_extensions = [
    "pdf", "docx", "pptx", "xlsx", "txt", "md", "html", "csv", "eml", "rtf", "odt",
]
supported_utis = [
    "com.adobe.pdf",
    "org.openxmlformats.wordprocessingml.document",
    "org.openxmlformats.presentationml.presentation",
    "org.openxmlformats.spreadsheetml.sheet",
    "public.plain-text",
    "net.daringfireball.markdown",
    "public.html",
    "public.comma-separated-values-text",
    "public.email-message",
    "public.rtf",
    "org.oasis-open.opendocument.text",
]

plist["CFBundleDocumentTypes"] = [
    {
        "CFBundleTypeName": "Documents supported by XLENT Scanner",
        "CFBundleTypeRole": "Viewer",
        "CFBundleTypeExtensions": supported_extensions,
        "LSItemContentTypes": supported_utis,
        "LSHandlerRank": "Alternate",
    }
]

with plist_path.open("wb") as f:
    plistlib.dump(plist, f, sort_keys=False)
PY

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_PATH"
  codesign --verify --deep --strict "$APP_PATH"
else
  echo "Warning: codesign not found; app bundle was not re-signed after Info.plist update." >&2
fi

echo "Build complete: $APP_PATH"
