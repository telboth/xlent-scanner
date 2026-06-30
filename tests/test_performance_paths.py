from __future__ import annotations

from pathlib import Path

from xlent_scanner import scanner


def test_pdf_extraction_uses_fitz_without_docling_when_text_is_enough(monkeypatch, tmp_path: Path):
    pdf = tmp_path / "text.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    extracted = "Dette er tekstbasert PDF-tekst. " * 5

    monkeypatch.setattr(scanner, "_extract_text_pdf_fitz", lambda path: extracted)

    def fail_docling(*_args, **_kwargs):
        raise AssertionError("Docling should not be loaded for normal text PDFs")

    monkeypatch.setattr(scanner, "_get_pdf_converter", fail_docling)

    assert scanner._extract_text_pdf(pdf) == extracted


def test_pdf_extraction_tries_docling_when_fitz_text_is_too_short(monkeypatch, tmp_path: Path):
    pdf = tmp_path / "sparse.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    docling_text = "Docling fant mer strukturert tekst enn PyMuPDF. " * 3

    class FakeDocument:
        def export_to_markdown(self):
            return docling_text

    class FakeConversion:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, path):
            return FakeConversion()

    monkeypatch.setattr(scanner, "_extract_text_pdf_fitz", lambda path: "OK")
    monkeypatch.setattr(scanner, "_get_pdf_converter", lambda ocr=False: FakeConverter())

    assert scanner._extract_text_pdf(pdf) == docling_text


def test_category_filtered_scan_skips_ner_when_names_are_not_selected(monkeypatch):
    text = "Kontakt test@example.com. Navn: Ola Nordmann. Telefon: 41234567."

    def fail_detect_names(*_args, **_kwargs):
        raise AssertionError("spaCy name detection should be skipped")

    def fail_get_load_error(*_args, **_kwargs):
        raise AssertionError("NER load check should not load or check when names are disabled")

    monkeypatch.setattr(scanner, "detect_names", fail_detect_names)
    monkeypatch.setattr(scanner, "get_load_error", fail_get_load_error)

    result = scanner.scan_text(text, language="nb", categories=["epost"])

    assert [f.category for f in result.findings] == ["e-post"]
    assert result.findings[0].text == "test@example.com"

