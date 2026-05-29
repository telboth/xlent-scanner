"""Tekstekstraksjon og scan-orkestrering."""
from __future__ import annotations

import html
import re
from pathlib import Path

import fitz  # type: ignore[import-untyped]  # fallback PDF-parser

_pdf_converter = None  # Docling DocumentConverter – lazy-initialisert ved første PDF-scan

from xlent_scanner.detectors.clients import detect_clients
from xlent_scanner.detectors.creditcards import detect_creditcards
from xlent_scanner.detectors.financials import detect_financials
from xlent_scanner.detectors.iban import detect_iban
from xlent_scanner.detectors.keywords import detect_keywords
from xlent_scanner.detectors.ner_names import detect_names, get_load_error
from xlent_scanner.detectors.regex_en import detect_en_specific
from xlent_scanner.detectors.regex_no import detect_no_specific, find_emails
from xlent_scanner.detectors.regex_sv import detect_sv_specific
from xlent_scanner.detectors.regex_da import detect_da_specific
from xlent_scanner.detectors.regex_url import detect_urls
from xlent_scanner.detectors.secrets import detect_secrets
from xlent_scanner.ignore import filter_findings, load_ignore_list
from xlent_scanner.language import resolve_language
from xlent_scanner.models import Finding, ScanResult  # noqa: F401
from xlent_scanner.risk import assess
from xlent_scanner.whitelist import filter_by_whitelist

SUPPORTED_SUFFIXES = {
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".md", ".txt", ".html",
    ".csv", ".eml", ".rtf", ".odt",
}

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


def _get_pdf_converter():
    """Returnerer (og cacher) en Docling DocumentConverter for PDF-parsing.
    Raises RuntimeError hvis Docling eller en av dens avhengigheter ikke er tilgjengelig.
    """
    global _pdf_converter
    if _pdf_converter is None:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat

        opts = PdfPipelineOptions()
        opts.do_ocr = False  # hopp over EasyOCR (tung avhengighet, ikke nødvendig her)
        # Docling laster layout-modell automatisk ved første konvertering.
        _pdf_converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    return _pdf_converter


def _extract_text_pdf_fitz(path: Path) -> str:
    """Fallback: enkel tekstekstraksjon via PyMuPDF."""
    chunks: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text"))
    return "\n".join(chunks).strip()


def _extract_text_pdf(path: Path) -> str:
    """Ekstraherer tekst fra PDF.

    Prøver Docling først (bedre layout-rekonstruksjon og tabelldeteksjon).
    Faller tilbake til PyMuPDF ved feil (f.eks. hvis Docling ikke er tilgjengelig i frozen build).
    """
    try:
        converter = _get_pdf_converter()
        return converter.convert(str(path)).document.export_to_markdown()
    except Exception:
        return _extract_text_pdf_fitz(path)


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


def _extract_text_csv(path: Path) -> str:
    """Leser CSV og returnerer celleinnhold rad for rad."""
    import csv as _csv
    content = _read_text_file(path)
    try:
        reader = _csv.reader(content.splitlines())
        parts = [" | ".join(cell for cell in row if cell.strip()) for row in reader]
        return "\n".join(p for p in parts if p).strip()
    except Exception:
        return content.strip()


def _extract_text_eml(path: Path) -> str:
    """Ekstraherer tekst fra e-post (.eml) via stdlib email-modulen."""
    import email as _email
    from email import policy as _policy
    content = _read_text_file(path)
    msg = _email.message_from_string(content, policy=_policy.default)
    parts: list[str] = []
    # Relevante headers
    for header in ("From", "To", "Cc", "Bcc", "Subject", "Date", "Reply-To"):
        val = msg.get(header, "")
        if val:
            parts.append(f"{header}: {val}")
    # Brødtekst
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    parts.append(str(part.get_content()))
                except Exception:
                    pass
    else:
        try:
            parts.append(str(msg.get_content()))
        except Exception:
            pass
    return "\n".join(parts).strip()


# Regex for å strippe RTF-kontrollkoder (enkel men presis for vanlig tekst-RTF)
_RTF_CTRL = re.compile(
    r"\\(?:[a-z]+(?:-?\d+)? ?|\'[0-9a-fA-F]{2}|[^a-z\s])"
    r"|[{}]",
    re.IGNORECASE,
)


def _extract_text_rtf(path: Path) -> str:
    """Enkel RTF-ekstraksjon: fjerner kontrollkoder, beholder løpende tekst."""
    content = _read_text_file(path)
    if not content.lstrip().startswith("{\\rtf"):
        return content.strip()
    text = _RTF_CTRL.sub("", content)
    return re.sub(r"\s+", " ", text).strip()


def _extract_text_odt(path: Path) -> str:
    """Ekstraherer tekst fra ODT/ODS/ODP via zipfile + XML-parsing."""
    import xml.etree.ElementTree as _ET
    import zipfile as _zf

    with _zf.ZipFile(str(path), "r") as zf:
        if "content.xml" not in zf.namelist():
            return ""
        with zf.open("content.xml") as f:
            root = _ET.parse(f).getroot()

    parts: list[str] = []
    for elem in root.iter():
        if elem.text and elem.text.strip():
            parts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail.strip())
    return "\n".join(parts).strip()


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
    if suffix == ".csv":
        return _extract_text_csv(path)
    if suffix == ".eml":
        return _extract_text_eml(path)
    if suffix == ".rtf":
        return _extract_text_rtf(path)
    if suffix == ".odt":
        return _extract_text_odt(path)
    raise ValueError(f"Filtype ikke støttet: {suffix}")


def scan_text(text: str, language: str = "auto", source_name: str = "Innlimt tekst") -> ScanResult:
    """Skann ren tekst direkte (uten filekstraksjon). Brukes for utklippstavle/paste."""
    if not text.strip():
        return ScanResult(
            file_name=source_name, file_size=0, text_length=0, text_preview="",
            error="Ingen tekst å skanne.",
        )
    lang = resolve_language(language, text)
    findings: list[Finding] = []
    _detector_errors: list[str] = []

    def _run(fn, *args):
        try:
            findings.extend(fn(*args))
        except BaseException as _e:
            _detector_errors.append(f"{fn.__name__}: {type(_e).__name__}: {_e}")

    _run(detect_keywords, text)
    _run(detect_secrets, text)
    _run(find_emails, text)
    _run(detect_urls, text)
    if lang in ("nb", "en"):
        _run(detect_no_specific, text)
    if lang in ("sv", "en"):
        _run(detect_sv_specific, text)
    if lang == "da":
        _run(detect_da_specific, text)
    if lang == "en":
        _run(detect_en_specific, text)
    _run(detect_iban, text)
    _run(detect_creditcards, text)
    _run(detect_financials, text)
    _run(detect_clients, text)
    _run(detect_names, text, lang)

    findings = filter_by_whitelist(findings)

    ner_err = get_load_error(lang)
    if ner_err:
        findings.append(Finding(category="⚠ NER ikke tilgjengelig", text=ner_err, context=""))
    for det_err in _detector_errors:
        findings.append(Finding(category="⚠ Detektor-feil", text=det_err, context=""))

    result = ScanResult(
        file_name=source_name,
        file_size=len(text.encode("utf-8")),
        text_length=len(text),
        text_preview=text,
        findings=findings,
        original_text=text,
        language=lang,
    )
    return assess(result)


def scan_folder(
    folder: str | Path,
    ignore_xlent: bool = False,
    language: str = "auto",
    max_files: int = 100,
) -> list[ScanResult]:
    """Skann alle støttede filer i en mappe. Returnerer resultater sortert etter risikonivå."""
    p = Path(folder)
    if not p.is_dir():
        raise ValueError(f"Ikke en mappe: {folder}")
    files = sorted(
        [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES],
        key=lambda f: f.name.lower(),
    )[:max_files]
    results = [scan_file(f, ignore_xlent=ignore_xlent, language=language) for f in files]
    level_order = {"svart": 3, "rød": 2, "gul": 1, "grønn": 0}
    results.sort(key=lambda r: level_order.get(r.risk_level, 0), reverse=True)
    return results


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
        except BaseException as _e:   # fanger også SystemExit / KeyboardInterrupt
            _detector_errors.append(f"{fn.__name__}: {type(_e).__name__}: {_e}")

    _run(detect_keywords, text)
    _run(detect_secrets, text)
    _run(find_emails, text)
    _run(detect_urls, text)
    if lang in ("nb", "en"):
        _run(detect_no_specific, text)
    if lang in ("sv", "en"):
        _run(detect_sv_specific, text)
    if lang == "da":
        _run(detect_da_specific, text)
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
