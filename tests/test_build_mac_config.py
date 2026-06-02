from pathlib import Path


def test_macos_build_enables_finder_open_with() -> None:
    script = Path("scripts/build_mac.sh").read_text(encoding="utf-8")

    assert "--argv-emulation" in script
    assert "CFBundleDocumentTypes" in script
    assert "org.openxmlformats.wordprocessingml.document" in script
    assert "CFBundleTypeExtensions" in script
    assert '"docx"' in script
