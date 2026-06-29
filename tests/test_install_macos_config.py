from pathlib import Path


def test_macos_installer_removes_quarantine() -> None:
    script = Path("scripts/install_macos.sh").read_text(encoding="utf-8")

    assert "hdiutil attach" in script
    assert "cp -R" in script
    assert "com.apple.quarantine" in script
    assert "xattr -dr" in script
    assert 'APP_NAME="XLENTScanner.app"' in script
    assert 'DEST_APP="/Applications/${APP_NAME}"' in script
    assert "lsregister" in script
    assert "Launch Services" in script
    assert "pbs -flush" in script
    assert 'install_finder_quick_action "${DEST_APP}"' in script


def test_macos_quick_action_accepts_finder_file_inputs() -> None:
    script = Path("scripts/install_macos.sh").read_text(encoding="utf-8")
    app = Path("src/xlent_scanner/app.py").read_text(encoding="utf-8")

    for text in ("public.item", "public.content", "public.data", "public.file-url", "com.apple.cocoa.path"):
        assert text in script
        assert text in app

    # Quick Action-format: NSMessage MÅ være runWorkflowAsService og
    # workflowTypeIdentifier MÅ være servicesMenu — ellers vises ikke
    # menyvalget i Finder og/eller kjører ikke når det klikkes.
    for doc in (script, app):
        assert "runWorkflowAsService" in doc
        assert ">runWorkflow<" not in doc
        assert "com.apple.Automator.servicesMenu" in doc
        assert ">com.apple.Automator.workflow<" not in doc
        assert "inputTypeIdentifier" in doc
        assert "presentationMode" in doc

    assert "<key>serviceProcessesInput</key>" in script
    assert "<key>serviceProcessesInput</key><integer>0</integer>" in app
    assert "SUDO_USER" in script
    assert 'user="$(target_user)"' in script
    assert 'home_dir="$(target_home "${user}")"' in script
    assert "chown -R" in script
    assert "chmod -R u+rwX,go+rX" in script
    assert "plutil -lint" in script
    assert "Privacy & Security" in script
    assert "run_xlent_scanner.sh" in script
    assert "run_xlent_scanner.sh" in app
    assert "XLENTScannerQuickAction.log" in script
    assert "XLENTScannerQuickAction.log" in app
    assert 'APP_BUNDLE="${APP_BINARY%/Contents/MacOS/XLENTScanner}"' in script
    assert 'APP_BUNDLE="${APP_BINARY%/Contents/MacOS/XLENTScanner}"' in app
    assert 'inputs=("$@")' in script
    assert 'inputs=("$@")' in app
    assert "note=no_arguments_trying_stdin" in script
    assert "note=no_arguments_trying_stdin" in app
    assert 'while IFS= read -r line; do' in script
    assert 'while IFS= read -r line; do' in app
    assert '/usr/bin/open -n "${APP_BUNDLE}" --args "${f}"' in script
    assert '/usr/bin/open -n "${APP_BUNDLE}" --args "${f}"' in app
    assert 'nohup "${APP_BINARY}" "${f}" </dev/null' in script
    assert 'nohup "${APP_BINARY}" "${f}" </dev/null' in app
    assert 'started_direct pid=$! path=${f}' in script
    assert 'started_direct pid=$! path=${f}' in app
    assert 'XLENT_SCANNER_APP_BINARY="${app_binary_xml}" "${runner_script_xml}" "\\$@"' in script
    assert 'XLENT_SCANNER_APP_BINARY="{app_binary_xml}" "{runner_script_xml}" "$@"' in app
    assert 'if [[ "${f}" != file://* && ! -e "${f}" ]]; then' in script
    assert 'if [[ "${f}" != file://* && ! -e "${f}" ]]; then' in app
    assert "&gt;/dev/null" not in script
    assert "2&gt;&amp;1" not in script
    assert "&gt;/dev/null" not in app
    assert "2&gt;&amp;1" not in app
    assert "killall Finder" in script


def test_release_uses_single_macos_install_script() -> None:
    workflow = Path(".github/workflows/build-release.yml").read_text(encoding="utf-8")
    release_script = Path("create_release.ps1").read_text(encoding="utf-8")

    assert "scripts/install_macos.sh" in workflow
    assert "scripts/install_macos.sh" in release_script
    assert "install_mac_quick_action.sh" not in workflow
    assert "install_mac_quick_action.sh" not in release_script
    assert "install_mac_service.sh" not in workflow
    assert "install_mac_service.sh" not in release_script


def test_macos_package_script_uses_temp_staging_and_hdiutil_retry() -> None:
    script = Path("scripts/package_mac.sh").read_text(encoding="utf-8")

    assert "mktemp -d" in script
    assert "STAGING_PARENT" in script
    assert "trap cleanup EXIT" in script
    assert "for attempt in 1 2 3" in script
    assert "hdiutil create" in script
    assert "else\n      status=$?" in script
    assert "sleep \"$((attempt * 5))\"" in script
    assert 'mv "$DMG_TMP" "$DMG_PATH"' in script
    assert 'ln -s /Applications "$STAGING_DIR/Applications"' in script
