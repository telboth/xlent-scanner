"""In-place anonymisering av originalfiler (DOCX, PPTX, XLSX, PDF).

Strategi per format:
  DOCX  – python-docx: merge runs per avsnitt, erstatt tekst, skriv tilbake
  PPTX  – python-pptx: samme run-merge per tekstramme
  XLSX  – openpyxl:    erstatt celleverdier direkte
  PDF   – pymupdf:     søk+rediger med standard PDF-redaksjonsannotering
"""
from __future__ import annotations

import unicodedata
import re
from pathlib import Path


# ── Normalisering ─────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """NFC + normaliser whitespace for robust matching mot originaltekst."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def _apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """To-fase erstatning: tokens forhindrer kollisjon mellom overlappende funn."""
    if not replacements:
        return text

    # Fase 1: erstatt med null-byte-tokens (lengste-først)
    tokens: list[tuple[str, str]] = []
    sorted_items = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
    for i, (old, new) in enumerate(sorted_items):
        token = f"\x00{i}\x00"
        text = text.replace(old, token)
        norm_old = _norm(old)
        if norm_old != old:
            text = text.replace(norm_old, token)
        tokens.append((token, new))

    # Fase 2: tokens → endelige plassholdere
    for token, new in tokens:
        text = text.replace(token, new)
    return text


# ── DOCX ──────────────────────────────────────────────────────────────────────

def _replace_in_para(para, replacements: dict[str, str]) -> None:
    """Erstatt tekst i ett avsnitt.  Merger runs slik at split-tekst matches."""
    if not para.runs:
        return
    full = "".join(r.text for r in para.runs)
    modified = _apply_replacements(full, replacements)
    if modified == full:
        return
    # Skriv tilbake: legg alt i første run, nullstill resten.
    # Første runs formatering (font, størrelse) beholdes for hele avsnittet.
    para.runs[0].text = modified
    for run in para.runs[1:]:
        run.text = ""


def _process_docx_paras(paragraphs, replacements: dict[str, str]) -> None:
    for para in paragraphs:
        _replace_in_para(para, replacements)


def patch_docx(source: Path, replacements: dict[str, str], output: Path) -> None:
    from docx import Document  # type: ignore[import-untyped]

    doc = Document(str(source))

    # Brødtekst
    _process_docx_paras(doc.paragraphs, replacements)

    # Tabeller i brødtekst
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                _process_docx_paras(cell.paragraphs, replacements)

    # Topptekst, bunntekst og tabeller der
    for section in doc.sections:
        for hf in (section.header, section.footer):
            _process_docx_paras(hf.paragraphs, replacements)
            for table in hf.tables:
                for row in table.rows:
                    for cell in row.cells:
                        _process_docx_paras(cell.paragraphs, replacements)

    doc.save(str(output))


# ── PPTX ──────────────────────────────────────────────────────────────────────

def _iter_pptx_shapes(shapes):
    """Yield alle shapes rekursivt (inkl. grupperte shapes)."""
    for shape in shapes:
        yield shape
        if hasattr(shape, "shapes"):   # GroupShapes
            yield from _iter_pptx_shapes(shape.shapes)


def patch_pptx(source: Path, replacements: dict[str, str], output: Path) -> None:
    from pptx import Presentation  # type: ignore[import-untyped]

    prs = Presentation(str(source))

    for slide in prs.slides:
        for shape in _iter_pptx_shapes(slide.shapes):
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    _replace_in_para(para, replacements)
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for para in cell.text_frame.paragraphs:
                            _replace_in_para(para, replacements)

    # Slide-layout og -master (noter o.l. ignoreres med vilje)
    prs.save(str(output))


# ── XLSX ──────────────────────────────────────────────────────────────────────

def patch_xlsx(source: Path, replacements: dict[str, str], output: Path) -> None:
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    wb = load_workbook(str(source))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.value = _apply_replacements(cell.value, replacements)
    wb.save(str(output))


# ── PDF ───────────────────────────────────────────────────────────────────────

def redact_pdf(source: Path, replacements: dict[str, str], output: Path) -> None:
    """PDF-redaksjon med pymupdf.

    Erstatter sensitiv tekst med plassholder-tekst på hvit bakgrunn.
    Tekst som ikke finnes på siden hoppes over stille.
    """
    import fitz  # type: ignore[import-untyped]  # pymupdf

    doc = fitz.open(str(source))
    for page in doc:
        for old, new in replacements.items():
            hits = page.search_for(old)
            for rect in hits:
                page.add_redact_annot(
                    rect,
                    text=new,
                    fontname="helv",
                    fontsize=9,
                    fill=(1, 1, 1),        # hvit bakgrunn
                    text_color=(0, 0, 0),  # svart tekst
                )
            # Prøv normalisert variant
            norm_old = _norm(old)
            if norm_old != old:
                for rect in page.search_for(norm_old):
                    page.add_redact_annot(
                        rect,
                        text=new,
                        fontname="helv",
                        fontsize=9,
                        fill=(1, 1, 1),
                        text_color=(0, 0, 0),
                    )
        page.apply_redacts()

    doc.save(str(output), garbage=4, deflate=True)
    doc.close()


# ── Dispatcher ────────────────────────────────────────────────────────────────

SUPPORTED_PATCH_SUFFIXES = {".docx", ".pptx", ".xlsx", ".pdf"}


def patch_file(source: Path, replacements: dict[str, str], output: Path) -> None:
    """Kall riktig patcher basert på filsuffikset."""
    suffix = source.suffix.lower()
    if suffix == ".docx":
        patch_docx(source, replacements, output)
    elif suffix == ".pptx":
        patch_pptx(source, replacements, output)
    elif suffix == ".xlsx":
        patch_xlsx(source, replacements, output)
    elif suffix == ".pdf":
        redact_pdf(source, replacements, output)
    else:
        raise ValueError(f"Filformat ikke støttet for in-place anonymisering: {suffix}")
