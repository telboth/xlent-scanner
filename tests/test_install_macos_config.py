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
