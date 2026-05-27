"""Tekstekstraksjon og scan-orkestrering."""
from __future__ import annotations

import html
import re
from pathlib import Path

import fitz  # type: ignore[import-untyped]

from xlent_scanner.detectors.clients import detect_clients
from xlent_scanner.detectors.creditcards import detect_creditcards
from xlent_scanner.detectors.financials import detect_financials
from xlent_scanner.detectors.iban import detect_iban
from xlent_scanner.detectors.keywords import detect_keywords
from xlent_scanner.detectors.ner_names import detect_names, get_load_error
from xlent_scanner.detectors.regex_en import detect_en_specific
from xlent_scanner.detectors.regex_no import detect_no_specific, find_emails
from xlent_scanner.detectors.regex_sv import detect_sv_specific
from xlent_scanner.detectors.secrets import detect_secrets
from xlent_scanner.ignore import filter_findings, load_ignore_list
from xlent_scanner.language import resolve_language
from xlent_scanner.models import Finding, ScanResult  # noqa: F401
from xlent_scanner.risk import assess
from xlent_scanner.whitelist import filter_by_whitelist

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".html"}

_ignore_list: dict | None = None


def reset_ignore_cache() -> None:
    global _ignore_list
    _ignore_list = None


def _get_ignore_list() -> dict:
    global _ignore_list
    if _ignore_list is None:
        _ignore_list = load_ignore_list()
    return _ignore_list


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_text_pdf(path: Path) -> str:
    chunks: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text"))
    return "\n".join(chunks).strip()


def _extract_text_docx(path: Path) -> str:
    from docx import Document as DocxDocument  # lazy import for packaged stability

    doc = DocxDocument(str(path))
    parts: list[str] = []
    parts.extend(p.text for p in doc.paragraphs if p.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    parts.append(cell.text)
    return "\n".join(parts).strip()


def _extract_text_pptx(path: Path) -> str:
    from pptx import Presentation  # lazy import for packaged stability

    prs = Presentation(str(path))
    parts: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text:
                parts.append(shape.text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    for cell in row.cells:
                        if cell.text:
                            parts.append(cell.text)
        try:
            notes = slide.notes_slide.notes_text_frame.text
            if notes:
                parts.append(notes)
        except Exception:
            pass
    return "\n".join(parts).strip()


def _extract_text_xlsx(path: Path) -> str:
    from openpyxl import load_workbook  # lazy import for packaged stability

    wb = load_workbook(filename=str(path), data_only=True, read_only=True)
    try:
        parts: list[str] = []
        for ws in wb.worksheets:
            parts.append(f"[{ws.title}]")
            for row in ws.iter_rows(values_only=True):
                vals = [str(v) for v in row if v is not None and str(v).strip()]
                if vals:
                    parts.append(" | ".join(vals))
        return "\n".join(parts).strip()
    finally:
        wb.close()


def _extract_text_html(path: Path) -> str:
    content = _read_text_file(path)
    content = re.sub(r"(?is)<script.*?>.*?</script>", " ", content)
    content = re.sub(r"(?is)<style.*?>.*?</style>", " ", content)
    content = re.sub(r"(?s)<[^>]+>", " ", content)
    content = html.unescape(content)
    content = re.sub(r"\s+", " ", content)
    return content.strip()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_text_pdf(path)
    if suffix == ".docx":
        return _extract_text_docx(path)
    if suffix == ".pptx":
        return _extract_text_pptx(path)
    if suffix == ".xlsx":
        return _extract_text_xlsx(path)
    if suffix in {".md", ".txt"}:
        return _read_text_file(path).strip()
    if suffix == ".html":
        return _extract_text_html(path)
    raise ValueError(f"Filtype ikke støttet: {suffix}")


def scan_file(path: str | Path, ignore_xlent: bool = False, language: str = "auto") -> ScanResult:
    p = Path(path)
    if not p.exists():
        return ScanResult(
            file_name=p.name, file_size=0, text_length=0, text_preview="",
            error=f"Fil ikke funnet: {p}",
        )
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return ScanResult(
            file_name=p.name, file_size=p.stat().st_size,
            text_length=0, text_preview="",
            error=f"Filtype ikke støttet: {suffix}",
        )
    try:
        text = extract_text(p)
    except Exception as exc:
        msg = str(exc)
        if any(k in msg.lower() for k in ("illegal character", "not well-formed", "invalid token", "xml", "expat")):
            friendly = (
                "Filen inneholder ugyldige tegn og kunne ikke leses automatisk. "
                "Dette skjer gjerne med innscannede eller redigerte PPTX/DOCX-filer. "
                "Prøv å åpne filen og lagre den på nytt, eller konverter til PDF."
            )
        else:
            friendly = f"Klarte ikke å lese fil: {msg}"
        return ScanResult(
            file_name=p.name, file_size=p.stat().st_size,
            text_length=0, text_preview="",
            error=friendly,
        )

    preview = text

    _TEXT_MIN = 50
    warning: str | None = None
    if len(text.strip()) < _TEXT_MIN:
        warning = (
            "Lite eller ingen tekst ble funnet i dokumentet. "
            "Filen kan bestå av innscannede bilder (bilde-PDF) "
            "og innholdet kan ikke sjekkes automatisk. "
            "Vurder å bruke en tekstbasert versjon av filen."
        )

    lang = resolve_language(language, text)

    findings: list[Finding] = []
    _detector_errors: list[str] = []

    def _run(fn, *args):
        try:
            findings.extend(fn(*args))
        except Exception as _e:
            _detector_errors.append(f"{fn.__name__}: {_e}")

    _run(detect_keywords, text)
    _run(detect_secrets, text)
    _run(find_emails, text)
    if lang in ("nb", "en"):
        _run(detect_no_specific, text)
    if lang in ("sv", "en"):
        _run(detect_sv_specific, text)
    if lang == "en":
        _run(detect_en_specific, text)
    _run(detect_iban, text)
    _run(detect_creditcards, text)
    _run(detect_financials, text)
    _run(detect_clients, text)
    _run(detect_names, text, lang)

    if ignore_xlent:
        findings = filter_findings(findings, _get_ignore_list())

    findings = filter_by_whitelist(findings)

    ner_err = get_load_error(lang)
    if ner_err:
        findings.append(Finding(
            category="⚠ NER ikke tilgjengelig",
            text=ner_err,
            context="",
        ))

    for det_err in _detector_errors:
        findings.append(Finding(
            category="⚠ Detektor-feil",
            text=det_err,
            context="",
        ))

    result = ScanResult(
        file_name=p.name,
        file_size=p.stat().st_size,
        text_length=len(text),
        text_preview=preview,
        findings=findings,
        original_text=text,
        language=lang,
        warning=warning,
    )
    return assess(result)
