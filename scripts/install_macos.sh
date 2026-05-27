#!/usr/bin/env bash
set -euo pipefail

OWNER="${1:-telboth}"
REPO="${2:-xlent-scanner}"
TAG="${3:-}"
ASSET_REGEX='xlent-scanner-.*\.(dmg|pkg)$'
DOWNLOAD_DIR="${HOME}/Downloads/xlent-scanner-install"

if [[ -n "${TAG}" ]]; then
  API_URL="https://api.github.com/repos/${OWNER}/${REPO}/releases/tags/${TAG}"
else
  API_URL="https://api.github.com/repos/${OWNER}/${REPO}/releases/latest"
fi

RELEASE_JSON="$(curl -fsSL -H "User-Agent: xlent-scanner-install" "${API_URL}")"

ASSET_NAME="$(python3 -c 'import json,re,sys; data=json.loads(sys.stdin.read()); rgx=re.compile(sys.argv[1]); print(next((a["name"] for a in data.get("assets",[]) if rgx.match(a["name"])), ""))' "${ASSET_REGEX}" <<< "${RELEASE_JSON}")"
ASSET_URL="$(python3 -c 'import json,re,sys; data=json.loads(sys.stdin.read()); rgx=re.compile(sys.argv[1]); print(next((a["browser_download_url"] for a in data.get("assets",[]) if rgx.match(a["name"])), ""))' "${ASSET_REGEX}" <<< "${RELEASE_JSON}")"
TAG_NAME="$(python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); print(data.get("tag_name",""))' <<< "${RELEASE_JSON}")"

if [[ -z "${ASSET_NAME}" || -z "${ASSET_URL}" ]]; then
  echo "Fant ingen macOS-installer i release ${TAG_NAME:-unknown}."
  exit 1
fi

mkdir -p "${DOWNLOAD_DIR}"
INSTALLER_PATH="${DOWNLOAD_DIR}/${ASSET_NAME}"

echo "Laster ned ${ASSET_NAME} fra ${TAG_NAME}..."
curl -fL "${ASSET_URL}" -o "${INSTALLER_PATH}"

echo "Åpner installer: ${INSTALLER_PATH}"
open "${INSTALLER_PATH}"
