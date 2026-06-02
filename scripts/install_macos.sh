#!/usr/bin/env bash
set -euo pipefail

OWNER="${1:-telboth}"
REPO="${2:-xlent-scanner}"
TAG="${3:-}"
ASSET_REGEX='xlent-scanner-.*\.(dmg|pkg)$'
DOWNLOAD_DIR="${HOME}/Downloads/xlent-scanner-install"
QUICK_ACTION_SCRIPT="install_mac_quick_action.sh"
APP_NAME="XLENTScanner.app"
DEST_APP="/Applications/${APP_NAME}"
MOUNT_POINT=""

cleanup() {
  if [[ -n "${MOUNT_POINT}" && -d "${MOUNT_POINT}" ]]; then
    hdiutil detach "${MOUNT_POINT}" -quiet >/dev/null 2>&1 || true
    rmdir "${MOUNT_POINT}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

run_as_needed() {
  if [[ -w "/Applications" ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

if [[ -n "${TAG}" ]]; then
  API_URL="https://api.github.com/repos/${OWNER}/${REPO}/releases/tags/${TAG}"
else
  API_URL="https://api.github.com/repos/${OWNER}/${REPO}/releases/latest"
fi

RELEASE_JSON="$(curl -fsSL -H "User-Agent: xlent-scanner-install" "${API_URL}")"

ASSET_NAME="$(python3 -c 'import json,re,sys; data=json.loads(sys.stdin.read()); rgx=re.compile(sys.argv[1]); print(next((a["name"] for a in data.get("assets",[]) if rgx.match(a["name"])), ""))' "${ASSET_REGEX}" <<< "${RELEASE_JSON}")"
ASSET_URL="$(python3 -c 'import json,re,sys; data=json.loads(sys.stdin.read()); rgx=re.compile(sys.argv[1]); print(next((a["browser_download_url"] for a in data.get("assets",[]) if rgx.match(a["name"])), ""))' "${ASSET_REGEX}" <<< "${RELEASE_JSON}")"
TAG_NAME="$(python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); print(data.get("tag_name",""))' <<< "${RELEASE_JSON}")"
QUICK_ACTION_URL="$(python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); name=sys.argv[1]; print(next((a["browser_download_url"] for a in data.get("assets",[]) if a["name"] == name), ""))' "${QUICK_ACTION_SCRIPT}" <<< "${RELEASE_JSON}")"

if [[ -z "${ASSET_NAME}" || -z "${ASSET_URL}" ]]; then
  echo "Fant ingen macOS-installer i release ${TAG_NAME:-unknown}."
  exit 1
fi

mkdir -p "${DOWNLOAD_DIR}"
INSTALLER_PATH="${DOWNLOAD_DIR}/${ASSET_NAME}"

echo "Laster ned ${ASSET_NAME} fra ${TAG_NAME}..."
curl -fL "${ASSET_URL}" -o "${INSTALLER_PATH}"

if [[ -n "${QUICK_ACTION_URL}" ]]; then
  QUICK_ACTION_PATH="${DOWNLOAD_DIR}/${QUICK_ACTION_SCRIPT}"
  echo "Laster ned Finder Quick Action-installer..."
  curl -fL "${QUICK_ACTION_URL}" -o "${QUICK_ACTION_PATH}"
  chmod +x "${QUICK_ACTION_PATH}"
fi

echo "Monterer ${ASSET_NAME}..."
MOUNT_POINT="$(mktemp -d /tmp/xlent-scanner-dmg.XXXXXX)"
hdiutil attach "${INSTALLER_PATH}" -quiet -nobrowse -mountpoint "${MOUNT_POINT}"

SOURCE_APP="${MOUNT_POINT}/${APP_NAME}"
if [[ ! -d "${SOURCE_APP}" ]]; then
  echo "Fant ikke ${APP_NAME} i DMG-en."
  exit 1
fi

echo "Installerer ${APP_NAME} til /Applications..."
if [[ -d "${DEST_APP}" ]]; then
  run_as_needed rm -rf "${DEST_APP}"
fi
run_as_needed cp -R "${SOURCE_APP}" "/Applications/"

echo "Fjerner macOS quarantine-attributt..."
if command -v xattr >/dev/null 2>&1; then
  run_as_needed xattr -dr com.apple.quarantine "${DEST_APP}" || true
fi

if command -v codesign >/dev/null 2>&1; then
  codesign --verify --deep --strict "${DEST_APP}" >/dev/null 2>&1 || {
    echo "Advarsel: macOS-signatur kunne ikke verifiseres lokalt. Appen kan fortsatt blokkeres av Gatekeeper."
  }
fi

echo "Installerte ${DEST_APP}"

if [[ -n "${QUICK_ACTION_URL}" ]]; then
  echo ""
  echo "Installer Finder Quick Action med:"
  echo "  bash \"${QUICK_ACTION_PATH}\""
fi

echo ""
echo "Start appen fra Applications. Hvis macOS fortsatt blokkerer den, kjør:"
echo "  xattr -dr com.apple.quarantine \"${DEST_APP}\""
