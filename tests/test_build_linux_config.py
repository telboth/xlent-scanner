from pathlib import Path


def test_linux_build_collects_image_ocr_but_excludes_docling_stack() -> None:
    script = Path("scripts/build_linux.sh").read_text(encoding="utf-8")

    assert "--collect-all rapidocr" in script
    assert "--collect-all onnxruntime" in script
    assert '--exclude-module "docling"' in script
    assert '--exclude-module "torch"' in script
