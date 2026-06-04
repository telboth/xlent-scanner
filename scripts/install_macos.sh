#!/usr/bin/env bash
set -euo pipefail

OWNER="telboth"
REPO="xlent-scanner"
TAG=""
MODE="full"
ASSET_REGEX='xlent-scanner-.*\.(dmg|pkg)$'
DOWNLOAD_DIR="${HOME}/Downloads/xlent-scanner-install"
APP_NAME="XLENTScanner.app"
DEST_APP="/Applications/${APP_NAME}"
MOUNT_POINT=""
POSITIONAL=()

usage() {
  cat <<'EOF'
Bruk:
  bash install_macos.sh
  bash install_macos.sh --tag v1.3.15
  bash install_macos.sh --quick-action-only
  bash install_macos.sh --quick-action-only --app-path /Applications/XLENTScanner.app

Scriptet laster ned siste macOS-release, installerer appen i /Applications,
fjerner quarantine-attributt, oppdaterer Launch Services og installerer
Finder-hurtighandlingen "Skann med XLENT" for riktig bruker.
EOF
}

cleanup() {
  if [[ -n "${MOUNT_POINT}" && -d "${MOUNT_POINT}" ]]; then
    hdiutil detach "${MOUNT_POINT}" -quiet >/dev/null 2>&1 || true
    rmdir "${MOUNT_POINT}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --owner)
      OWNER="$2"
      shift 2
      ;;
    --repo)
      REPO="$2"
      shift 2
      ;;
    --tag)
      TAG="$2"
      shift 2
      ;;
    --app-path)
      DEST_APP="$2"
      shift 2
      ;;
    --quick-action-only)
      MODE="quick-action-only"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

# Bakoverkompatibelt: bash install_macos.sh telboth xlent-scanner v1.3.15
if [[ "${#POSITIONAL[@]}" -gt 0 ]]; then
  OWNER="${POSITIONAL[0]}"
fi
if [[ "${#POSITIONAL[@]}" -gt 1 ]]; then
  REPO="${POSITIONAL[1]}"
fi
if [[ "${#POSITIONAL[@]}" -gt 2 ]]; then
  TAG="${POSITIONAL[2]}"
fi

run_as_needed() {
  if [[ -w "/Applications" ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

target_user() {
  if [[ "$(id -u)" == "0" && -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    printf '%s' "${SUDO_USER}"
  else
    id -un
  fi
}

target_home() {
  local user="$1"
  local home_dir=""
  if command -v dscl >/dev/null 2>&1; then
    home_dir="$(dscl . -read "/Users/${user}" NFSHomeDirectory 2>/dev/null | awk '{print $2}' || true)"
  fi
  if [[ -z "${home_dir}" ]]; then
    home_dir="$(eval echo "~${user}")"
  fi
  printf '%s' "${home_dir}"
}

xml_escape() {
  local s="$1"
  s="${s//&/&amp;}"
  s="${s//</&lt;}"
  s="${s//>/&gt;}"
  s="${s//\"/&quot;}"
  printf '%s' "$s"
}

install_finder_quick_action() {
  local app_path="$1"
  local binary="$app_path/Contents/MacOS/XLENTScanner"

  if [[ ! -x "$binary" ]]; then
    echo "Fant ikke XLENTScanner på: $binary"
    echo "Oppgi alternativ sti: $0 --quick-action-only --app-path /sti/til/XLENTScanner.app"
    exit 1
  fi

  local user
  local home_dir
  local service_dir
  local service_name
  local service_path
  local app_binary_xml

  user="$(target_user)"
  home_dir="$(target_home "${user}")"
  if [[ -z "${home_dir}" || "${home_dir}" == "~${user}" ]]; then
    echo "Fant ikke hjemmekatalog for bruker: ${user}"
    exit 1
  fi

  service_dir="$home_dir/Library/Services"
  service_name="Skann med XLENT.workflow"
  service_path="$service_dir/$service_name"
  app_binary_xml="$(xml_escape "$binary")"

  mkdir -p "$service_dir"
  rm -rf "$service_path"
  mkdir -p "$service_path/Contents"

  cat > "$service_path/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key>
      <dict>
        <key>default</key>
        <string>Skann med XLENT</string>
      </dict>
      <key>NSMessage</key>
      <string>runWorkflow</string>
      <key>NSRequiredContext</key>
      <dict>
        <key>NSApplicationIdentifier</key>
        <string>com.apple.finder</string>
      </dict>
      <key>NSSendFileTypes</key>
      <array>
        <string>public.item</string>
        <string>public.content</string>
        <string>public.data</string>
        <string>public.file-url</string>
      </array>
    </dict>
  </array>
</dict>
</plist>
PLIST

  cat > "$service_path/Contents/document.wflow" <<WFLOW
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>AMApplicationBuild</key>
  <string>521.1</string>
  <key>AMApplicationVersion</key>
  <string>2.10</string>
  <key>AMDocumentVersion</key>
  <string>2</string>
  <key>actions</key>
  <array>
    <dict>
      <key>action</key>
      <dict>
        <key>AMAccepts</key>
        <dict>
          <key>Container</key>
          <string>List</string>
          <key>Optional</key>
          <true/>
          <key>Types</key>
          <array>
            <string>com.apple.cocoa.path</string>
            <string>public.file-url</string>
            <string>public.item</string>
            <string>public.content</string>
            <string>public.data</string>
          </array>
        </dict>
        <key>AMActionVersion</key>
        <string>2.0.3</string>
        <key>AMApplication</key>
        <array><string>Automator</string></array>
        <key>AMParameterProperties</key>
        <dict>
          <key>COMMAND_STRING</key>
          <dict/>
          <key>CheckedForUserDefaultShell</key>
          <dict/>
          <key>inputMethod</key>
          <dict/>
          <key>shell</key>
          <dict/>
          <key>source</key>
          <dict/>
        </dict>
        <key>AMProvides</key>
        <dict>
          <key>Container</key>
          <string>List</string>
          <key>Types</key>
          <array>
            <string>com.apple.cocoa.path</string>
            <string>public.file-url</string>
            <string>public.item</string>
            <string>public.content</string>
            <string>public.data</string>
          </array>
        </dict>
        <key>ActionBundlePath</key>
        <string>/System/Library/Automator/Run Shell Script.action</string>
        <key>ActionName</key>
        <string>Run Shell Script</string>
        <key>ActionParameters</key>
        <dict>
          <key>COMMAND_STRING</key>
          <string>for f in "\$@"; do
  "${app_binary_xml}" "\$f" &amp;
done</string>
          <key>CheckedForUserDefaultShell</key>
          <true/>
          <key>inputMethod</key>
          <integer>1</integer>
          <key>shell</key>
          <string>/bin/bash</string>
          <key>source</key>
          <string></string>
        </dict>
        <key>BundleIdentifier</key>
        <string>com.apple.RunShellScript</string>
        <key>CFBundleVersion</key>
        <string>2.0.3</string>
        <key>CanShowSelectedItemsWhenRun</key>
        <false/>
        <key>CanShowWhenRun</key>
        <true/>
        <key>Category</key>
        <array><string>AMCategoryUtilities</string></array>
        <key>Class Name</key>
        <string>RunShellScriptAction</string>
        <key>InputUUID</key>
        <string>$(uuidgen 2>/dev/null || echo "00000000-0000-0000-0000-000000000001")</string>
        <key>Keywords</key>
        <array><string>Shell</string><string>Script</string><string>Command</string></array>
        <key>OutputUUID</key>
        <string>$(uuidgen 2>/dev/null || echo "00000000-0000-0000-0000-000000000002")</string>
        <key>UUID</key>
        <string>$(uuidgen 2>/dev/null || echo "00000000-0000-0000-0000-000000000003")</string>
        <key>UnlocalizedApplications</key>
        <array><string>Automator</string></array>
        <key>arguments</key>
        <dict>
          <key>0</key>
          <dict>
            <key>default value</key>
            <integer>0</integer>
            <key>name</key>
            <string>inputMethod</string>
            <key>required</key>
            <string>0</string>
            <key>type</key>
            <string>0</string>
            <key>uuid</key>
            <string>0</string>
          </dict>
        </dict>
        <key>isViewVisible</key>
        <true/>
        <key>location</key>
        <string>321.000000:253.000000</string>
        <key>nibPath</key>
        <string>/System/Library/Automator/Run Shell Script.action/Contents/Resources/English.lproj/main.nib</string>
      </dict>
      <key>isViewVisible</key>
      <true/>
    </dict>
  </array>
  <key>connectors</key>
  <dict/>
  <key>workflowMetaData</key>
  <dict>
    <key>serviceInputTypeIdentifier</key>
    <string>com.apple.Automator.fileSystemObject</string>
    <key>serviceOutputTypeIdentifier</key>
    <string>com.apple.Automator.nothing</string>
    <key>serviceProcessesInput</key>
    <integer>1</integer>
    <key>workflowTypeIdentifier</key>
    <string>com.apple.Automator.workflow</string>
  </dict>
</dict>
</plist>
WFLOW

  if [[ "$(id -u)" == "0" && "${user}" != "root" ]]; then
    chown -R "${user}:staff" "$service_path" 2>/dev/null || chown -R "${user}" "$service_path" 2>/dev/null || true
  fi

  /System/Library/CoreServices/pbs -flush 2>/dev/null || true
  touch "$service_path" 2>/dev/null || true
  killall Finder 2>/dev/null || true

  echo ""
  echo "Finder-hurtighandling installert: $service_path"
  echo "Bruker: $user"
  echo ""
  echo "Aktivering:"
  echo "  Hoyreklikk en fil i Finder -> Hurtighandlinger -> Skann med XLENT"
}

if [[ "${MODE}" == "quick-action-only" ]]; then
  install_finder_quick_action "$DEST_APP"
  exit 0
fi

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

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "${LSREGISTER}" ]]; then
  echo "Oppdaterer macOS Launch Services-registrering..."
  "${LSREGISTER}" -f "${DEST_APP}" >/dev/null 2>&1 || true
fi

if [[ -x "/System/Library/CoreServices/pbs" ]]; then
  /System/Library/CoreServices/pbs -flush >/dev/null 2>&1 || true
fi

echo "Installerte ${DEST_APP}"

echo ""
echo "Installerer Finder-hurtighandling for denne brukeren..."
if install_finder_quick_action "${DEST_APP}"; then
  echo "Finder-hurtighandling installert."
else
  echo "Advarsel: Finder-hurtighandling kunne ikke installeres automatisk."
  echo "Proev manuelt:"
  echo "  bash \"$0\" --quick-action-only --app-path \"${DEST_APP}\""
fi

echo ""
echo "Start appen fra Applications. Hvis macOS fortsatt blokkerer den, kjør:"
echo "  xattr -dr com.apple.quarantine \"${DEST_APP}\""
