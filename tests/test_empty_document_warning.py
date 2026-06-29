from pathlib import Path

from xlent_scanner import scanner


def test_scan_file_warns_when_no_text_is_extracted(monkeypatch, tmp_path: Path) -> None:
    doc = tmp_path / "image-only.pdf"
    doc.write_bytes(b"%PDF-1.4\n% image-only fixture\n")
    monkeypatch.setattr(scanner, "extract_text", lambda path: "")

    result = scanner.scan_file(doc, language="nb")

    assert result.error is None
    assert result.scan_status == "partial"
    assert result.text_length == 0
    assert result.warning_code == "no_text_extracted"
    assert "Ingen tekst" in (result.warning or "")
    assert "OCR" in (result.warning or "")


def test_scan_file_warns_when_very_little_text_is_extracted(monkeypatch, tmp_path: Path) -> None:
    doc = tmp_path / "almost-empty.pdf"
    doc.write_bytes(b"%PDF-1.4\n% tiny text fixture\n")
    monkeypatch.setattr(scanner, "extract_text", lambda path: "OK")

    result = scanner.scan_file(doc, language="nb")

    assert result.error is None
    assert result.scan_status == "partial"
    assert result.text_length == 2
    assert result.warning_code == "little_text_extracted"


def test_scan_file_warns_when_pdf_only_has_docling_image_placeholders(monkeypatch, tmp_path: Path) -> None:
    doc = tmp_path / "image-markers.pdf"
    doc.write_bytes(b"%PDF-1.4\n% image marker fixture\n")
    extracted = "\n\n".join(["<!-- image -->"] * 7)

    monkeypatch.setattr(scanner, "extract_text", lambda path, ocr=False: extracted)
    monkeypatch.setattr(scanner, "_pdf_looks_image_based", lambda path: True)

    result = scanner.scan_file(doc, language="nb")

    assert result.error is None
    assert result.scan_status == "partial"
    assert result.text_length == len(extracted)
    assert result.warning_code == "no_text_extracted"
    assert "OCR" in (result.warning or "")


def test_scan_file_does_not_warn_when_pdf_has_images_and_enough_real_text(monkeypatch, tmp_path: Path) -> None:
    doc = tmp_path / "text-and-images.pdf"
    doc.write_bytes(b"%PDF-1.4\n% text plus image fixture\n")
    extracted = "<!-- image -->\n" + (
        "Dette er en tekstbasert PDF med nok reell tekst til at OCR ikke skal tilbys automatisk. " * 4
    )

    monkeypatch.setattr(scanner, "extract_text", lambda path, ocr=False: extracted)
    monkeypatch.setattr(scanner, "_pdf_looks_image_based", lambda path: True)

    result = scanner.scan_file(doc, language="nb")

    assert result.error is None
    assert result.warning_code is None
    assert result.scan_status == "success"
