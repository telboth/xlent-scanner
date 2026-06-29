from pathlib import Path


def test_windows_build_supports_slim_and_full_flavors() -> None:
    script = Path("scripts/build_win.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("slim", "full")]' in script
    assert '[string]$BuildFlavor = "full"' in script
    assert 'if ($BuildFlavor -eq "full")' in script

    assert '"--collect-all", "docling_parse"' in script
    assert '"--collect-all", "docling"' in script
    assert '"--collect-all", "docling_core"' in script
    assert '"--collect-all", "rapidocr"' in script
    assert '"--collect-all", "onnxruntime"' in script

    assert '"--exclude-module", "docling"' in script
    assert '"--exclude-module", "torch"' in script


def test_windows_release_workflow_uses_full_build() -> None:
    workflow = Path(".github/workflows/build-release.yml").read_text(encoding="utf-8")

    assert r".\scripts\build_win.ps1 -BuildFlavor full" in workflow
    assert r".\scripts\build_win.ps1 -BuildFlavor slim" not in workflow
