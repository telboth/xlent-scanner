"""Docling-wrapper og scan-orkestrering."""
from __future__ import annotations

from pathlib import Path

from docling.document_converter import DocumentConverter
import fitz  # type: ignore[import-untyped]

from xlent_scanner.detectors.clients import detect_clients
from xlent_scanner.detectors.keywords import detect_keywords
from xlent_scanner.detectors.ner_names import detect_names, get_load_error
from xlent_scanner.detectors.creditcards import detect_creditcards
from xlent_scanner.detectors.financials import detect_financials
from xlent_scanner.detectors.iban import detect_iban
from xlent_scanner.detectors.regex_en import detect_en_specific
from xlent_scanner.detectors.regex_no import find_emails, detect_no_specific
from xlent_scanner.detectors.regex_sv import detect_sv_specific
from xlent_scanner.detectors.secrets import detect_secrets
from xlent_scanner.ignore import filter_findings, load_ignore_list
from xlent_scanner.language import resolve_language
from xlent_scanner.models import Finding, ScanResult  # noqa: F401
from xlent_scanner.risk import assess
from xlent_scanner.whitelist import filter_by_whitelist

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".html"}

_converter: DocumentConverter | None = None
_ignore_list: dict | None = None


def reset_ignore_cache() -> None:
    global _ignore_list
    _ignore_list = None


def _patch_docling_picture_description() -> None:
    """Bypass Docling picture-description factory when feature is disabled.

    In packaged builds (PyInstaller), Docling plugin registration for picture
    description classes can be empty, which raises:
    "No class found with the name 'picture_description_vlm_engine' ...".
    We do not use picture-description enrichment in this scanner, so when
    `do_picture_description` is false we return `None` directly.
    """
    from docling.pipeline import base_pipeline as _bp
    target_cls = _bp.ConvertPipeline

    if getattr(target_cls, "_xlent_picture_patch", False):
        return

    _orig = target_cls._get_picture_description_model

    def _safe_get_picture_description_model(self, artifacts_path=None):
        enabled = bool(getattr(self.pipeline_options, "do_picture_description", False))
        if not enabled:
            from docling.datamodel.pipeline_options import PictureDescriptionApiOptions
            from docling.models.stages.picture_description.picture_description_api_model import (
                PictureDescriptionApiModel,
            )

            return PictureDescriptionApiModel(
                enabled=False,
                enable_remote_services=bool(
                    getattr(self.pipeline_options, "enable_remote_services", False)
                ),
                artifacts_path=artifacts_path,
                options=PictureDescriptionApiOptions(),
                accelerator_options=self.pipeline_options.accelerator_options,
            )
        return _orig(self, artifacts_path=artifacts_path)

    target_cls._get_picture_description_model = _safe_get_picture_description_model
    target_cls._xlent_picture_patch = True


def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        _patch_docling_picture_description()
        _converter = DocumentConverter()
    return _converter


def _get_ignore_list() -> dict:
    global _ignore_list
    if _ignore_list is None:
        _ignore_list = load_ignore_list()
    return _ignore_list


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _extract_text_pdf(path)
    return _get_converter().convert(str(path)).document.export_to_markdown()


def _extract_text_pdf(path: Path) -> str:
    """Extract text from PDF using PyMuPDF.

    We prefer this path for stability in packaged desktop builds.
    """
    chunks: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text"))
    return "\n".join(chunks).strip()


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
        # Gi brukervennlig melding for kjente XML-feil (PPTX/DOCX med ugyldige tegn)
        if any(k in msg.lower() for k in ("illegal character", "not well-formed",
                                           "invalid token", "xml", "expat")):
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

    preview = text   # full tekst – grensesnittet håndterer scrolling

    # Sjekk om dokumentet er tomt / kun bildebasert
    _TEXT_MIN = 50    # tegn etter stripping – under dette regnes filen som tom
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
    # E-post er universelt – alltid aktivt
    _run(find_emails, text)
    # Norske mønstre: fødselsnummer, orgnr, kontonummer, telefon
    if lang in ("nb", "en"):
        _run(detect_no_specific, text)
    # Svenske mønstre: personnummer, samordningsnummer, org-nummer, telefon, bankgiro
    if lang in ("sv", "en"):
        _run(detect_sv_specific, text)
    # Engelske mønstre: UK NI-nummer, US SSN
    if lang == "en":
        _run(detect_en_specific, text)
    # Universelle mønstre (alle språk)
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
