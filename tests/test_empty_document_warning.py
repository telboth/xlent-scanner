from pathlib import Path

from xlent_scanner import scanner


def test_scan_file_warns_when_no_text_is_extracted(monkeypatch, tmp_path: Path) -> None:
    doc = tmp_path / "image-only.pdf"
    doc.write_bytes(b"%PDF-1.4\n% image-only fixture\n")
    monkeypatch.setattr(scanner, "extract_text", lambda path: "")

    result = scanner.scan_file(doc, language="nb")

    assert result.error is None
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
    assert result.text_length == 2
    assert result.warning_code == "little_text_extracted"
