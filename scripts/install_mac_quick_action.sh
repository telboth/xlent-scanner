#!/usr/bin/env bash
# Installerer en macOS Finder Quick Action som lar brukeren høyreklikke
# på en fil og velge "Skann med XLENT".

set -euo pipefail

APP_PATH="${1:-/Applications/XLENTScanner.app}"
BINARY="$APP_PATH/Contents/MacOS/XLENTScanner"

if [[ ! -x "$BINARY" ]]; then
  echo "Fant ikke XLENTScanner på: $BINARY"
  echo "Oppgi alternativ sti: $0 /sti/til/XLENTScanner.app"
  exit 1
fi

xml_escape() {
  local s="$1"
  s="${s//&/&amp;}"
  s="${s//</&lt;}"
  s="${s//>/&gt;}"
  s="${s//\"/&quot;}"
  printf '%s' "$s"
}

SERVICE_DIR="$HOME/Library/Services"
SERVICE_NAME="Skann med XLENT.workflow"
SERVICE_PATH="$SERVICE_DIR/$SERVICE_NAME"
APP_BINARY_XML="$(xml_escape "$BINARY")"

mkdir -p "$SERVICE_DIR"
rm -rf "$SERVICE_PATH"
mkdir -p "$SERVICE_PATH/Contents"

cat > "$SERVICE_PATH/Contents/Info.plist" <<'PLIST'
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

cat > "$SERVICE_PATH/Contents/document.wflow" <<WFLOW
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
  "${APP_BINARY_XML}" "\$f" &amp;
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
    <integer>0</integer>
    <key>workflowTypeIdentifier</key>
    <string>com.apple.Automator.workflow</string>
  </dict>
</dict>
</plist>
WFLOW

/System/Library/CoreServices/pbs -flush 2>/dev/null || true

echo ""
echo "Quick Action installert: $SERVICE_PATH"
echo ""
echo "Aktivering:"
echo "  1. Kjor: killall Finder"
echo "  2. Hoyreklikk en fil i Finder -> Hurtighandlinger -> Skann med XLENT"
