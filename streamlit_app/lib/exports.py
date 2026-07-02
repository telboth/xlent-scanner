"""Rapport- og eksportgenerering (HTML + PDF), gjenbruker xlent_scanner.report."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from xlent_scanner.models import ScanResult
from xlent_scanner.report import (
    _build_merged_findings,
    combined_assessment,
    generate_html,
)

_RISK_COLORS = {
    "grønn": (0.18, 0.69, 0.31),
    "gul": (0.85, 0.60, 0.15),
    "rød": (0.87, 0.22, 0.22),
    "svart": (0.61, 0.15, 0.69),
}


def build_html_report(result: ScanResult) -> str:
    """Full HTML-rapport (uten AI-funn / M365)."""
    return generate_html(result, api_base="", ai_findings=[], audit_metadata={}, redaction_audit=None)


def build_pdf_report(result: ScanResult) -> bytes:
    """PDF-rapport med samme innhold som HTML-rapporten. Speiler report_pdf-ruten."""
    import fitz  # noqa: PLC0415

    assessment = combined_assessment(result, [], {})
    merged_findings, _ = _build_merged_findings(result, [], {})
    doc = fitz.open()

    def new_page():
        return doc.new_page(width=595, height=842), 54

    def add_text(page, y, text, size=10, color=(0.1, 0.12, 0.15), bold=False):
        page.insert_text(
            (54, y), text, fontsize=size,
            fontname="hebo" if bold else "helv", color=color,
        )
        return y + size + 4

    page, y = new_page()
    y = add_text(page, y, "XLENT Compliance-scanner", 18, (0.20, 0.40, 0.85), True)
    y = add_text(page, y, f"Fil: {result.file_name}", 11)
    y = add_text(page, y, f"Dato: {datetime.now().strftime('%d.%m.%Y  %H:%M')}", 9)
    y += 6
    risk_color = _RISK_COLORS.get(assessment.risk_level, (0.1, 0.12, 0.15))
    y = add_text(page, y, f"Risikonivå: {assessment.risk_level.upper()}  –  {assessment.risk_summary}", 12, risk_color, True)
    y = add_text(page, y, assessment.recommended_action, 9, (0.3, 0.35, 0.42))
    y += 18

    if not merged_findings:
        y = add_text(page, y, "Ingen sensitive funn oppdaget.", 10, _RISK_COLORS["grønn"])
    else:
        y = add_text(page, y, f"Funn ({len(merged_findings)})", 11, bold=True)
        for finding in merged_findings:
            if y > 800:
                page, y = new_page()
            y = add_text(
                page, y,
                f"[{finding.category}] [{finding.engine}]  {finding.text[:100]}",
                9, _RISK_COLORS.get(finding.severity, (0.3, 0.35, 0.42)),
            )
            if finding.context:
                y = add_text(page, y, f"    {finding.context[:140]}", 7.5, (0.5, 0.55, 0.62))

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def report_filename(result: ScanResult, ext: str) -> str:
    stem = Path(result.file_name or "rapport").stem or "rapport"
    return f"{stem}-rapport.{ext}"


def downloads_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.exists() else Path.home() / "Desktop"


def unique_output(stem: str, suffix: str) -> Path:
    """Finn et ledig filnavn i Downloads (stem.suffix, stem-1.suffix, …)."""
    base = downloads_dir()
    output = base / f"{stem}{suffix}"
    counter = 1
    while output.exists():
        output = base / f"{stem}-{counter}{suffix}"
        counter += 1
    return output


def write_text_pdf(text: str, out_path: Path, title: str = "") -> None:
    """Skriv ren tekst til en enkel PDF. Speiler write_text_pdf i reports.py."""
    import fitz  # noqa: PLC0415

    doc = fitz.open()
    margin, width, height = 54, 595, 842
    max_width = width - 2 * margin
    fontsize, line_height = 10, 14

    def new_page():
        return doc.new_page(width=width, height=height), margin

    page, y = new_page()
    if title:
        page.insert_text((margin, y), title[:90], fontsize=14, fontname="hebo", color=(0.1, 0.2, 0.5))
        y += 22

    max_chars = max(20, int(max_width / (fontsize * 0.5)))
    for raw_line in text.split("\n"):
        if not raw_line.strip():
            y += line_height // 2
            continue
        current = ""
        for word in raw_line.split(" "):
            candidate = (current + " " + word).strip()
            if len(candidate) > max_chars and current:
                page.insert_text((margin, y), current, fontsize=fontsize, fontname="helv", color=(0.1, 0.1, 0.1))
                y += line_height
                current = word
                if y > height - margin:
                    page, y = new_page()
            else:
                current = candidate
        if current:
            page.insert_text((margin, y), current, fontsize=fontsize, fontname="helv", color=(0.1, 0.1, 0.1))
            y += line_height
            if y > height - margin:
                page, y = new_page()

    doc.save(str(out_path), garbage=4, deflate=True)
    doc.close()
