#!/usr/bin/env bash
# Pakker PyInstaller-bundelen som en AppImage.
#
# Krever:
#   - appimagetool (lastes ned automatisk hvis ikke tilgjengelig)
#   - FUSE (monteres automatisk i CI; på desktop: sudo apt install fuse)
#
# Sluttresultat: artifacts/linux/installer/xlent-scanner-linux-<versjon>-x86_64.AppImage
set -euo pipefail

BUILD_APP_DIR="${BUILD_APP_DIR:-artifacts/linux/app/dist/XLENTScanner}"
INSTALLER_OUT_DIR="${INSTALLER_OUT_DIR:-artifacts/linux/installer}"
VERSION="${VERSION:-}"
ARCH="${ARCH:-x86_64}"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --app-dir)  BUILD_APP_DIR="$2"; shift 2 ;;
    --out-dir)  INSTALLER_OUT_DIR="$2"; shift 2 ;;
    --version)  VERSION="$2"; shift 2 ;;
    --arch)     ARCH="$2"; shift 2 ;;
    *)          echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Hent versjon fra kildekode hvis ikke oppgitt
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

APP_DIR="$REPO_ROOT/$BUILD_APP_DIR"
if [[ ! -d "$APP_DIR" ]]; then
  echo "PyInstaller output missing: $APP_DIR. Run scripts/build_linux.sh first." >&2
  exit 1
fi

OUT_DIR="$REPO_ROOT/$INSTALLER_OUT_DIR"
mkdir -p "$OUT_DIR"

# ── Last ned appimagetool hvis den ikke finnes ──────────────────────────────
APPIMAGETOOL="${APPIMAGETOOL:-}"
if [[ -z "$APPIMAGETOOL" ]] || [[ ! -x "$APPIMAGETOOL" ]]; then
  TOOL_PATH="$OUT_DIR/appimagetool-x86_64.AppImage"
  if [[ ! -x "$TOOL_PATH" ]]; then
    echo "Laster ned appimagetool…"
    curl -fsSL \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
      -o "$TOOL_PATH"
    chmod +x "$TOOL_PATH"
  fi
  APPIMAGETOOL="$TOOL_PATH"
fi

# ── Bygg AppDir-struktur ─────────────────────────────────────────────────────
APPDIR="$OUT_DIR/XLENTScanner.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Kopier PyInstaller-innhold
cp -r "$APP_DIR"/. "$APPDIR/usr/bin/"

# AppRun: entry point
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/bash
# AppRun – starter XLENTScanner fra AppImage
SELF_DIR="$(dirname "$(readlink -f "$0")")"
exec "$SELF_DIR/usr/bin/XLENTScanner" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# .desktop-fil
cat > "$APPDIR/xlent-scanner.desktop" <<DESKTOP
[Desktop Entry]
Name=XLENT Compliance-scanner
Comment=Sjekker dokumenter for sensitiv kundeinfo
Exec=XLENTScanner
Icon=xlent-scanner
Terminal=false
Type=Application
Categories=Office;Utility;
DESKTOP

# Ikon: lag et minimalt SVG-ikon hvis det finnes et i repo-et
LOGO_SVG="$REPO_ROOT/src/xlent_scanner/web/logo.svg"
if [[ -f "$LOGO_SVG" ]]; then
  cp "$LOGO_SVG" "$APPDIR/usr/share/icons/hicolor/256x256/apps/xlent-scanner.svg"
  cp "$LOGO_SVG" "$APPDIR/xlent-scanner.svg"
else
  # Minimalt fallback-ikon
  cat > "$APPDIR/xlent-scanner.svg" <<'SVG'
<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">
  <rect width="256" height="256" rx="32" fill="#1a5a9a"/>
  <text x="128" y="180" font-size="180" text-anchor="middle" fill="white" font-family="sans-serif">X</text>
</svg>
SVG
fi
cp "$APPDIR/xlent-scanner.svg" "$APPDIR/usr/share/icons/hicolor/256x256/apps/"

# ── Bygg AppImage ─────────────────────────────────────────────────────────────
OUTPUT_NAME="xlent-scanner-linux-${VERSION}-${ARCH}.AppImage"
OUTPUT_PATH="$OUT_DIR/$OUTPUT_NAME"
rm -f "$OUTPUT_PATH"

# ARCH må eksporteres for appimagetool
export ARCH
ARCH="$ARCH" "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUTPUT_PATH" 2>&1 || {
  # Noen CI-miljøer trenger --appimage-extract-and-run
  ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUTPUT_PATH"
}

chmod +x "$OUTPUT_PATH"
echo "AppImage created: $OUTPUT_PATH"
