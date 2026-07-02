from pathlib import Path


def test_linux_build_collects_image_ocr_but_excludes_docling_stack() -> None:
    script = Path("scripts/build_linux.sh").read_text(encoding="utf-8")

    assert "--collect-all rapidocr" in script
    assert "--collect-all onnxruntime" in script
    assert '--exclude-module "docling"' in script
    assert '--exclude-module "torch"' in script


def test_linux_appimage_uses_qt_pywebview_backend() -> None:
    build_script = Path("scripts/build_linux.sh").read_text(encoding="utf-8")
    package_script = Path("scripts/package_linux.sh").read_text(encoding="utf-8")
    app_py = Path("src/xlent_scanner/app.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/build-release.yml").read_text(encoding="utf-8")

    assert '"pywebview[qt]>=5.3.0"' in build_script
    assert '--hidden-import "webview.platforms.qt"' in build_script
    assert '--hidden-import "webview.platforms.gtk"' not in build_script
    assert "--collect-all PyQt6" in build_script
    assert 'export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-qt}"' in package_script
    assert 'webview_gui = os.environ.get("PYWEBVIEW_GUI") or None' in app_py
    assert "webview.start(gui=webview_gui, debug=False, storage_path=webview_cache)" in app_py
    assert "libxcb-cursor0" in workflow
    assert "libwebkit2gtk-4.0-dev" not in workflow
