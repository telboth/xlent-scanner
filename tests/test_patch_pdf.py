from pathlib import Path

import fitz

from xlent_scanner.patch import redact_pdf


def _write_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def _read_pdf_text(path: Path) -> str:
    with fitz.open(str(path)) as doc:
        return "\n".join(page.get_text() for page in doc)


def test_redact_pdf_uses_current_pymupdf_api(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "redacted.pdf"

    _write_pdf(source, "Kunde Ola Nordmann har fnr 01010112345.")

    redact_pdf(source, {"01010112345": "[ANONYMISERT]"}, output)

    text = _read_pdf_text(output)
    assert "01010112345" not in text
    assert "[ANONYMISERT]" in text


def test_redact_pdf_can_strip_existing_annotations(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "redacted.pdf"

    _write_pdf(source, "Kunde Ola Nordmann har fnr 01010112345.")
    with fitz.open(str(source)) as doc:
        page = doc[0]
        page.add_text_annot((72, 96), "intern kommentar")
        doc.saveIncr()

    redact_pdf(source, {"01010112345": "[ANONYMISERT]"}, output, strip_annotations=True)

    with fitz.open(str(output)) as doc:
        assert sum(1 for page in doc for _ in (page.annots() or [])) == 0
