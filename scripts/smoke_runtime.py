from __future__ import annotations

from pathlib import Path


def main() -> None:
    import docx
    import fitz
    from transformers import AutoProcessor

    import xlent_scanner
    from xlent_scanner import app as app_module
    from xlent_scanner import scanner

    root = Path(xlent_scanner.__file__).parent
    required_files = [
        root / "web" / "index.html",
        root / "web" / "logo.svg",
        root / "data" / "ignore.toml",
        root / "data" / "clients.toml",
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing package data: {missing}")

    docx_root = Path(docx.__file__).parent
    docx_templates = [
        docx_root / "templates" / "default-header.xml",
        docx_root / "templates" / "default.docx",
    ]
    missing_docx = [str(path) for path in docx_templates if not path.exists()]
    if missing_docx:
        raise RuntimeError(f"Missing python-docx templates: {missing_docx}")

    page = fitz.open().new_page()
    if not hasattr(page, "apply_redactions"):
        raise RuntimeError("PyMuPDF Page.apply_redactions is not available")

    if not callable(scanner.scan_text):
        raise RuntimeError("scanner.scan_text is not callable")
    if not callable(app_module.flask_app.test_client):
        raise RuntimeError("Flask app is not initialized")
    if AutoProcessor is None:
        raise RuntimeError("transformers.AutoProcessor is not available")

    print("runtime smoke test ok")


if __name__ == "__main__":
    main()
