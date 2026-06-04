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

    assert "<key>serviceProcessesInput</key>" in script
    assert "<integer>1</integer>" in script
    assert "<key>serviceProcessesInput</key><integer>1</integer>" in app
    assert "SUDO_USER" in script
    assert 'user="$(target_user)"' in script
    assert 'home_dir="$(target_home "${user}")"' in script
    assert "chown -R" in script
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
