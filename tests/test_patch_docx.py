from pathlib import Path

from docx import Document
from docx.parts.hdrftr import FooterPart, HeaderPart

from xlent_scanner.patch import patch_docx


def test_patch_docx_without_header_footer_does_not_create_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"

    doc = Document()
    doc.add_paragraph("Kunde Ola Nordmann har konto 12345678901.")
    doc.save(source)

    def fail_default_xml(cls):
        raise AssertionError("default header/footer template should not be loaded")

    monkeypatch.setattr(HeaderPart, "_default_header_xml", classmethod(fail_default_xml))
    monkeypatch.setattr(FooterPart, "_default_footer_xml", classmethod(fail_default_xml))

    patch_docx(source, {"12345678901": "[ANONYMISERT]"}, output)

    patched = Document(output)
    text = "\n".join(p.text for p in patched.paragraphs)
    assert "12345678901" not in text
    assert "[ANONYMISERT]" in text
