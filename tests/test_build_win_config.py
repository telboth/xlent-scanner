from pathlib import Path


def test_windows_build_collects_docling_parse_resources() -> None:
    script = Path("scripts/build_win.ps1").read_text(encoding="utf-8")

    assert '"--collect-all", "docling_parse"' in script
    assert '"--collect-all", "docling"' in script
    assert '"--collect-all", "docling_core"' in script
