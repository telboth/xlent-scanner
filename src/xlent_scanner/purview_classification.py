"""Read Microsoft Purview sensitivity labels without inspecting document text.

The primary adapter reads clear-text label metadata embedded in Office and PDF
files.  A configured Microsoft Graph connection is used only as a fallback for
synced files.  The returned status deliberately distinguishes an unlabelled
file from a file that could not be checked.
"""
from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx"}
SUPPORTED_SUFFIXES = OFFICE_SUFFIXES | {".pdf"}
DEFAULT_KNOWN_LABELS = (
    "PERSONAL",
    "PUBLIC",
    "KDA LIMITED",
    "KDA RESTRICTED",
    "KDA PROTECTED",
    "UPI",
    "CUI",
    "ITAR",
)
KNOWN_LABELS = {
    value.strip().casefold(): value.strip()
    for value in os.environ.get(
        "XLENT_PURVIEW_KNOWN_LABELS",
        ",".join(DEFAULT_KNOWN_LABELS),
    ).split(",")
    if value.strip()
}

_PDF_COLORS = {
    "public": (0.12, 0.44, 0.20),
    "personal": (0.09, 0.36, 0.62),
    "limited": (0.50, 0.31, 0.00),
    "protected": (0.58, 0.25, 0.00),
    "regulated": (0.58, 0.25, 0.00),
    "unknown": (0.44, 0.21, 0.56),
    "neutral": (0.37, 0.43, 0.49),
    "not-checked": (0.37, 0.43, 0.49),
}

SUPPORTED_UI_LANGUAGES = ("nb", "sv", "en", "de", "fr", "es")
_PURVIEW_TRANSLATIONS = {
    "nb": {
        "title": "Microsoft Purview-klassifisering",
        "folder_title": "Purview-klassifisering",
        "unclassified": "Ikke klassifisert",
        "unsupported": "Ikke kontrollert for denne filtypen",
        "unknown": "Ukjent klassifisering",
        "disabled": "Deaktivert",
        "not_checked": "Ikke kontrollert",
    },
    "sv": {
        "title": "Microsoft Purview-klassificering",
        "folder_title": "Purview-klassificering",
        "unclassified": "Inte klassificerad",
        "unsupported": "Inte kontrollerad för den här filtypen",
        "unknown": "Okänd klassificering",
        "disabled": "Inaktiverad",
        "not_checked": "Inte kontrollerad",
    },
    "en": {
        "title": "Microsoft Purview classification",
        "folder_title": "Purview classification",
        "unclassified": "Not classified",
        "unsupported": "Not checked for this file type",
        "unknown": "Unknown classification",
        "disabled": "Disabled",
        "not_checked": "Not checked",
    },
    "de": {
        "title": "Microsoft Purview-Klassifizierung",
        "folder_title": "Purview-Klassifizierung",
        "unclassified": "Nicht klassifiziert",
        "unsupported": "Für diesen Dateityp nicht geprüft",
        "unknown": "Unbekannte Klassifizierung",
        "disabled": "Deaktiviert",
        "not_checked": "Nicht geprüft",
    },
    "fr": {
        "title": "Classification Microsoft Purview",
        "folder_title": "Classification Purview",
        "unclassified": "Non classifiée",
        "unsupported": "Non contrôlée pour ce type de fichier",
        "unknown": "Classification inconnue",
        "disabled": "Désactivée",
        "not_checked": "Non contrôlée",
    },
    "es": {
        "title": "Clasificación de Microsoft Purview",
        "folder_title": "Clasificación Purview",
        "unclassified": "Sin clasificar",
        "unsupported": "No comprobada para este tipo de archivo",
        "unknown": "Clasificación desconocida",
        "disabled": "Desactivada",
        "not_checked": "No comprobada",
    },
}

_PROPERTY_RE = re.compile(
    r"^MSIP_Label_([0-9a-fA-F-]{36})_([A-Za-z][A-Za-z0-9]*)$",
    re.IGNORECASE,
)
_GUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)


def _result(
    status: str,
    *,
    label_id: str = "",
    display_name: str = "",
    source: str = "",
    assignment_method: str = "",
    tenant_id: str = "",
    error: str = "",
) -> dict[str, Any]:
    canonical = KNOWN_LABELS.get(display_name.strip().casefold(), display_name.strip())
    return {
        "status": status,
        "label_id": label_id.strip(),
        "display_name": canonical,
        "source": source,
        "assignment_method": assignment_method.strip(),
        "tenant_id": tenant_id.strip(),
        "error": error,
    }


def classification_style_key(classification: dict[str, Any] | None) -> str:
    """Return the stable presentation color key for a classification result."""
    value = classification or {}
    status = str(value.get("status") or "")
    if status in {"unclassified", "unsupported", "disabled"}:
        return "neutral"
    if status == "not_checked":
        return "not-checked"
    if status == "unknown":
        return "unknown"
    if status != "classified":
        return "neutral"
    label = str(value.get("display_name") or "").strip().upper()
    if label == "PUBLIC":
        return "public"
    if label in {"PERSONAL", "PRIVATE"}:
        return "personal"
    if label in {"KDA LIMITED", "KDA RESTRICTED"}:
        return "limited"
    if label == "KDA PROTECTED":
        return "protected"
    if label in {"UPI", "CUI", "ITAR"}:
        return "regulated"
    return "unknown"


def normalize_ui_language(language: str | None) -> str:
    """Return a supported UI language, defaulting safely to Norwegian Bokmål."""
    normalized = str(language or "").strip().lower()
    return normalized if normalized in SUPPORTED_UI_LANGUAGES else "nb"


def purview_translation(key: str, language: str | None = "nb") -> str:
    """Return one localized Purview presentation string."""
    return _PURVIEW_TRANSLATIONS[normalize_ui_language(language)][key]


def classification_display_text(
    classification: dict[str, Any] | None,
    language: str | None = "nb",
) -> str:
    """Return a concise localized display value without inferring a label."""
    value = classification or {}
    status = str(value.get("status") or "")
    translated = _PURVIEW_TRANSLATIONS[normalize_ui_language(language)]
    if status == "classified":
        return str(value.get("display_name") or value.get("label_id") or translated["unknown"])
    if status == "unclassified":
        return translated["unclassified"]
    if status == "unsupported":
        return translated["unsupported"]
    if status == "unknown":
        detail = value.get("display_name") or value.get("label_id") or ""
        return f"{translated['unknown']}: {detail}" if detail else translated["unknown"]
    if status == "disabled":
        return translated["disabled"]
    error = str(value.get("error") or "")
    return f"{translated['not_checked']}: {error}" if error else translated["not_checked"]


def classification_pdf_color(classification: dict[str, Any] | None) -> tuple[float, float, float]:
    """Return an accessible RGB text color for PDF rendering."""
    return _PDF_COLORS[classification_style_key(classification)]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _properties_from_xml(raw: bytes | str) -> dict[str, str]:
    root = ElementTree.fromstring(raw)
    properties: dict[str, str] = {}
    for element in root.iter():
        local = _local_name(element.tag)
        if local == "property" and element.attrib.get("name"):
            value = "".join(element.itertext()).strip()
            properties[element.attrib["name"]] = value
        elif local.startswith("MSIP_Label_"):
            properties[local] = "".join(element.itertext()).strip()
        for key, value in element.attrib.items():
            attr_name = _local_name(key)
            if attr_name.startswith("MSIP_Label_"):
                properties[attr_name] = str(value)
    return properties


def _properties_from_label_info(raw: bytes | str) -> dict[str, str]:
    root = ElementTree.fromstring(raw)
    properties: dict[str, str] = {}
    for element in root.iter():
        if _local_name(element.tag).casefold() not in {"label", "classificationlabel"}:
            continue
        attrs = {_local_name(key).casefold(): str(value) for key, value in element.attrib.items()}
        label_id = attrs.get("id") or attrs.get("labelid")
        if not label_id or not _GUID_RE.fullmatch(label_id):
            continue
        mapping = {
            "enabled": attrs.get("enabled", "true"),
            "removed": attrs.get("removed", "false"),
            "method": attrs.get("method", ""),
            "siteid": attrs.get("siteid", attrs.get("tenantid", "")),
        }
        for attribute, value in mapping.items():
            if value:
                properties[f"MSIP_Label_{label_id}_{attribute}"] = value
    return properties


def _classification_from_properties(properties: dict[str, str], source: str) -> dict[str, Any]:
    grouped: dict[str, dict[str, str]] = {}
    sensitivity_id = ""
    for name, value in properties.items():
        if name.casefold() == "sensitivity":
            match = _GUID_RE.search(str(value))
            sensitivity_id = match.group(0) if match else ""
            continue
        match = _PROPERTY_RE.match(name)
        if match:
            grouped.setdefault(match.group(1).lower(), {})[match.group(2).casefold()] = str(value)

    candidates = []
    for label_id, values in grouped.items():
        enabled = values.get("enabled", "true").strip().casefold() in {"1", "true", "yes"}
        removed = values.get("removed", "false").strip().casefold() in {"1", "true", "yes"}
        if enabled and not removed:
            candidates.append((label_id, values))

    selected: tuple[str, dict[str, str]] | None = None
    if sensitivity_id:
        selected = next((item for item in candidates if item[0] == sensitivity_id.lower()), None)
        if selected is None:
            selected = (sensitivity_id.lower(), grouped.get(sensitivity_id.lower(), {}))
    elif candidates:
        selected = candidates[0]

    if selected is None:
        return _result("unclassified", source=source)

    label_id, values = selected
    name = values.get("name", "").strip()
    status = "classified" if name and name.casefold() in KNOWN_LABELS else "unknown"
    return _result(
        status,
        label_id=label_id,
        display_name=name,
        source=source,
        assignment_method=values.get("method", ""),
        tenant_id=values.get("siteid", values.get("tenantid", "")),
    )


def _read_office_metadata(path: Path) -> dict[str, Any]:
    properties: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for member in ("docProps/custom.xml", "docMetadata/LabelInfo.xml"):
                if member not in archive.namelist():
                    continue
                raw = archive.read(member)
                if member.endswith("LabelInfo.xml"):
                    properties.update(_properties_from_label_info(raw))
                else:
                    properties.update(_properties_from_xml(raw))
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError) as exc:
        return _result("not_checked", source="embedded_metadata", error=str(exc))
    return _classification_from_properties(properties, "embedded_metadata")


def _read_pdf_metadata(path: Path) -> dict[str, Any]:
    try:
        import fitz  # type: ignore[import-untyped]

        properties: dict[str, str] = {}
        with fitz.open(path) as document:
            metadata = document.metadata or {}
            properties.update({str(key): str(value) for key, value in metadata.items() if value})
            xml = document.get_xml_metadata() or ""
        if xml:
            try:
                properties.update(_properties_from_xml(xml))
            except ElementTree.ParseError:
                # Some producers emit non-standard XMP. Extract conventional
                # MSIP key/value pairs without treating the file as unlabelled.
                for match in re.finditer(
                    r"(MSIP_Label_[0-9a-fA-F-]{36}_[A-Za-z0-9]+)[\s=\"'>:]+([^<\"']+)",
                    xml,
                ):
                    properties[match.group(1)] = match.group(2).strip()
        return _classification_from_properties(properties, "embedded_metadata")
    except Exception as exc:  # PyMuPDF exposes several format-specific exceptions.
        return _result("not_checked", source="embedded_metadata", error=str(exc))


def _classification_from_graph(tags: dict[str, Any]) -> dict[str, Any]:
    sensitivity = tags.get("sensitivity") if isinstance(tags, dict) else {}
    labels = sensitivity.get("labels", []) if isinstance(sensitivity, dict) else []
    if not labels:
        raw = sensitivity.get("raw", {}) if isinstance(sensitivity, dict) else {}
        if isinstance(raw, dict) and raw.get("error"):
            return _result("not_checked", source="microsoft_graph", error=str(raw["error"]))
        return _result("unclassified", source="microsoft_graph")
    label = labels[0] if isinstance(labels[0], dict) else {}
    label_id = str(label.get("id") or label.get("labelId") or label.get("sensitivityLabelId") or "")
    name = str(label.get("displayName") or label.get("name") or label.get("labelName") or "")
    status = "classified" if name and name.casefold() in KNOWN_LABELS else "unknown"
    return _result(
        status,
        label_id=label_id,
        display_name=name,
        source="microsoft_graph",
        assignment_method=str(label.get("assignmentMethod") or ""),
        tenant_id=str(label.get("tenantId") or ""),
    )


def read_document_classification(
    path: str | Path,
    *,
    enabled: bool = True,
    graph_drive_id: str | None = None,
    graph_sync_root: str | None = None,
    graph_reader: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a stable Purview classification result for one local file."""
    if not enabled:
        return _result("disabled")
    file_path = Path(path)
    if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return _result("unsupported")
    if file_path.suffix.lower() in OFFICE_SUFFIXES:
        local = _read_office_metadata(file_path)
    else:
        local = _read_pdf_metadata(file_path)

    # Embedded metadata is sufficient when it contains a known display name.
    # Graph is only attempted when its mapping context is explicitly configured.
    if local["status"] == "classified" or not (graph_drive_id and graph_sync_root):
        return local
    try:
        if graph_reader is None:
            from xlent_scanner.microsoft_graph import read_document_tags_for_local_path

            graph_reader = read_document_tags_for_local_path
        tags = graph_reader(file_path, drive_id=graph_drive_id, sync_root=graph_sync_root)
        graph_result = _classification_from_graph(tags)
        if graph_result["status"] in {"classified", "unknown"}:
            return graph_result
        if local["status"] == "unclassified":
            return graph_result
    except Exception as exc:
        if local["status"] == "not_checked":
            return _result("not_checked", source="embedded_metadata+microsoft_graph", error=str(exc))
    return local
