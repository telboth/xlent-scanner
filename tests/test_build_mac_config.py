from pathlib import Path


def test_macos_build_enables_finder_open_with() -> None:
    script = Path("scripts/build_mac.sh").read_text(encoding="utf-8")

    assert "--argv-emulation" in script
    assert "--collect-data docx" in script
    assert "--collect-data pptx" in script
    assert "CFBundleDocumentTypes" in script
    assert "Documents supported by XLENT Scanner" not in script
    assert "XLENT Scanner supported documents" in script
    assert "supported_extensions" in script
    assert "supported_utis" in script
    assert '"public.content"' in script
    assert '"public.data"' in script
    assert '"public.item"' in script
    assert "org.openxmlformats.wordprocessingml.document" in script
    assert "CFBundleTypeMIMETypes" in script
    assert "CFBundleTypeExtensions" in script
    assert '"docx"' in script
    assert "codesign --force --deep --sign -" in script
    assert "codesign --verify --deep --strict" in script
