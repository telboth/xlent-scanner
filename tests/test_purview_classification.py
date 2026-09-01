"""Synthetic metadata fixtures; these are not genuine tenant-labelled files."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

import fitz
from docx import Document

from xlent_scanner import scanner
from xlent_scanner.purview_classification import (
    classification_display_text,
    classification_style_key,
    purview_translation,
    read_document_classification,
)

LABEL_ID = "11111111-2222-3333-4444-555555555555"
SITE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _synthetic_docx(path: Path, label_name: str | None, text: str = "Synthetic Purview metadata fixture") -> Path:
    """Create a readable DOCX and inject conventional synthetic MSIP metadata."""
    document = Document()
    document.add_paragraph(text)
    document.save(path)
    if label_name is None:
        return path
    return _inject_synthetic_purview_metadata(path, label_name)


def _inject_synthetic_purview_metadata(path: Path, label_name: str) -> Path:
    """Add a valid OOXML custom-properties part with synthetic MSIP values."""
    custom_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
 <property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="MSIP_Label_{LABEL_ID}_Enabled"><vt:lpwstr>true</vt:lpwstr></property>
 <property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="3" name="MSIP_Label_{LABEL_ID}_Method"><vt:lpwstr>Standard</vt:lpwstr></property>
 <property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="4" name="MSIP_Label_{LABEL_ID}_Name"><vt:lpwstr>{label_name}</vt:lpwstr></property>
 <property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="5" name="MSIP_Label_{LABEL_ID}_SiteId"><vt:lpwstr>{SITE_ID}</vt:lpwstr></property>
 <property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="6" name="Sensitivity"><vt:lpwstr>{LABEL_ID}</vt:lpwstr></property>
</Properties>"""
    replacement = path.with_suffix(".synthetic.tmp.docx")
    content_types_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    relationships_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    ElementTree.register_namespace("", content_types_namespace)
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(replacement, "w") as target:
        for item in source.infolist():
            if item.filename == "docProps/custom.xml":
                continue
            data = source.read(item.filename)
            if item.filename == "[Content_Types].xml":
                root = ElementTree.fromstring(data)
                for child in list(root):
                    if child.attrib.get("PartName") == "/docProps/custom.xml":
                        root.remove(child)
                ElementTree.SubElement(
                    root,
                    f"{{{content_types_namespace}}}Override",
                    {
                        "PartName": "/docProps/custom.xml",
                        "ContentType": "application/vnd.openxmlformats-officedocument.custom-properties+xml",
                    },
                )
                data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            elif item.filename == "_rels/.rels":
                root = ElementTree.fromstring(data)
                for child in list(root):
                    if child.attrib.get("Type", "").endswith("/custom-properties"):
                        root.remove(child)
                ElementTree.SubElement(
                    root,
                    f"{{{relationships_namespace}}}Relationship",
                    {
                        "Id": "rIdSyntheticPurview",
                        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties",
                        "Target": "docProps/custom.xml",
                    },
                )
                data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item, data)
        target.writestr("docProps/custom.xml", custom_xml)
    replacement.replace(path)
    return path


def test_reads_known_label_from_synthetic_office_metadata(tmp_path: Path):
    path = _synthetic_docx(tmp_path / "limited.docx", "KDA LIMITED")

    result = read_document_classification(path)

    assert result == {
        "status": "classified",
        "label_id": LABEL_ID,
        "display_name": "KDA LIMITED",
        "source": "embedded_metadata",
        "assignment_method": "Standard",
        "tenant_id": SITE_ID,
        "error": "",
    }


def test_reads_kda_restricted_as_known_classification(tmp_path: Path):
    path = _synthetic_docx(tmp_path / "restricted.docx", "KDA RESTRICTED")

    result = read_document_classification(path)

    assert result["status"] == "classified"
    assert result["display_name"] == "KDA RESTRICTED"
    assert classification_style_key(result) == "limited"


def test_purview_presentation_text_is_available_in_all_ui_languages():
    expected = {
        "nb": ("Microsoft Purview-klassifisering", "Ikke klassifisert", "Ikke kontrollert for denne filtypen"),
        "sv": ("Microsoft Purview-klassificering", "Inte klassificerad", "Inte kontrollerad för den här filtypen"),
        "en": ("Microsoft Purview classification", "Not classified", "Not checked for this file type"),
        "de": ("Microsoft Purview-Klassifizierung", "Nicht klassifiziert", "Für diesen Dateityp nicht geprüft"),
        "fr": ("Classification Microsoft Purview", "Non classifiée", "Non contrôlée pour ce type de fichier"),
        "es": ("Clasificación de Microsoft Purview", "Sin clasificar", "No comprobada para este tipo de archivo"),
    }

    for language, (title, status, unsupported) in expected.items():
        assert purview_translation("title", language) == title
        assert classification_display_text({"status": "unclassified"}, language) == status
        assert classification_display_text({"status": "unsupported"}, language) == unsupported


def test_purview_presentation_defaults_to_norwegian_for_unknown_language():
    assert purview_translation("title", "xx") == "Microsoft Purview-klassifisering"
    assert classification_display_text({"status": "not_checked"}, "xx") == "Ikke kontrollert"


def test_distinguishes_unclassified_unsupported_disabled_and_unreadable(tmp_path: Path):
    unclassified = _synthetic_docx(tmp_path / "plain.docx", None)
    unsupported = tmp_path / "plain.txt"
    unsupported.write_text("plain", encoding="utf-8")
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"not a zip")

    assert read_document_classification(unclassified)["status"] == "unclassified"
    assert read_document_classification(unsupported)["status"] == "unsupported"
    assert read_document_classification(unclassified, enabled=False)["status"] == "disabled"
    assert read_document_classification(corrupt)["status"] == "not_checked"


def test_unknown_label_is_not_treated_as_unclassified(tmp_path: Path):
    path = _synthetic_docx(tmp_path / "unknown.docx", "TENANT SPECIAL")

    result = read_document_classification(path)

    assert result["status"] == "unknown"
    assert result["display_name"] == "TENANT SPECIAL"
    assert result["label_id"] == LABEL_ID


def test_reads_known_label_from_synthetic_pdf_xmp(tmp_path: Path):
    path = tmp_path / "public.pdf"
    xmp = f"""<?xml version="1.0"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description xmlns:pdfx="http://ns.adobe.com/pdfx/1.3/">
   <pdfx:MSIP_Label_{LABEL_ID}_Enabled>true</pdfx:MSIP_Label_{LABEL_ID}_Enabled>
   <pdfx:MSIP_Label_{LABEL_ID}_Method>Standard</pdfx:MSIP_Label_{LABEL_ID}_Method>
   <pdfx:MSIP_Label_{LABEL_ID}_Name>PUBLIC</pdfx:MSIP_Label_{LABEL_ID}_Name>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""
    document = fitz.open()
    document.new_page()
    document.set_xml_metadata(xmp)
    document.save(path)
    document.close()

    result = read_document_classification(path)

    assert result["status"] == "classified"
    assert result["display_name"] == "PUBLIC"


def test_reads_modern_office_label_info_as_unknown_id(tmp_path: Path):
    path = _synthetic_docx(tmp_path / "label-info.docx", None)
    label_info = f"""<?xml version="1.0"?>
<clbl:labelList xmlns:clbl="http://schemas.microsoft.com/office/2020/mipLabelMetadata">
 <clbl:label id="{LABEL_ID}" siteId="{SITE_ID}" enabled="1" method="Standard" />
</clbl:labelList>"""
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("docMetadata/LabelInfo.xml", label_info)

    result = read_document_classification(path)

    assert result["status"] == "unknown"
    assert result["label_id"] == LABEL_ID
    assert result["tenant_id"] == SITE_ID


def test_graph_is_an_explicit_fallback_for_synced_file(tmp_path: Path):
    path = _synthetic_docx(tmp_path / "plain.docx", None)

    result = read_document_classification(
        path,
        graph_drive_id="drive",
        graph_sync_root=str(tmp_path),
        graph_reader=lambda *_args, **_kwargs: {
            "sensitivity": {"labels": [{"sensitivityLabelId": LABEL_ID, "name": "KDA PROTECTED"}]}
        },
    )

    assert result["status"] == "classified"
    assert result["display_name"] == "KDA PROTECTED"
    assert result["source"] == "microsoft_graph"


def test_scan_file_keeps_secret_detection_and_adds_classification(tmp_path: Path):
    path = _synthetic_docx(
        tmp_path / "protected.docx",
        "KDA PROTECTED",
        "password=synthetic-secret-value",
    )

    result = scanner.scan_file(path)

    assert result.purview_classification["display_name"] == "KDA PROTECTED"
    assert any(finding.category == "Passord i konfig" for finding in result.findings)


def test_scan_file_can_disable_classification(tmp_path: Path):
    path = _synthetic_docx(tmp_path / "public.docx", "PUBLIC")

    result = scanner.scan_file(path, include_purview_classification=False)

    assert result.purview_classification["status"] == "disabled"
