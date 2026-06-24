"""Ruter for rapportvisning, eksport og anonymisering."""
from __future__ import annotations

import csv
import io
import json
import logging
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from xlent_scanner.ai_findings import (
    as_model_findings,
    findings_from_payload,
    replacement_texts,
)
from xlent_scanner.anonymize import anonymize_text, build_replacements
from xlent_scanner.app_state import app_state
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES, patch_file
from xlent_scanner.report import generate_html
from xlent_scanner.whitelist import add_to_whitelist

LOGGER = logging.getLogger("xlent_scanner")
reports_bp = Blueprint("reports", __name__)


def _downloads_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.exists() else Path.home() / "Desktop"


def ai_findings_for_report() -> list[dict]:
    if app_state.last_result is None:
        return []
    if (
        app_state.last_ai_findings_file_name
        and app_state.last_result.file_name != app_state.last_ai_findings_file_name
    ):
        return []
    return app_state.last_ai_findings


def write_text_pdf(text: str, out_path: Path, title: str = "") -> None:
    import fitz  # noqa: PLC0415

    doc = fitz.open()
    margin, width, height = 54, 595, 842
    max_width = width - 2 * margin
    fontsize, line_height = 10, 14

    def new_page():
        return doc.new_page(width=width, height=height), margin

    page, y = new_page()
    if title:
        page.insert_text(
            (margin, y),
            title[:90],
            fontsize=14,
            fontname="hebo",
            color=(0.1, 0.2, 0.5),
        )
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
                page.insert_text(
                    (margin, y),
                    current,
                    fontsize=fontsize,
                    fontname="helv",
                    color=(0.1, 0.1, 0.1),
                )
                y += line_height
                current = word
                if y > height - margin:
                    page, y = new_page()
            else:
                current = candidate
        if current:
            page.insert_text(
                (margin, y),
                current,
                fontsize=fontsize,
                fontname="helv",
                color=(0.1, 0.1, 0.1),
            )
            y += line_height
            if y > height - margin:
                page, y = new_page()

    doc.save(str(out_path), garbage=4, deflate=True)
    doc.close()


@reports_bp.post("/add-to-whitelist")
def add_to_whitelist_endpoint():
    data = request.get_json(force=True)
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "Ingen tekst oppgitt."})
    add_to_whitelist(text)
    return jsonify({"ok": True})


@reports_bp.post("/report/ai-findings")
def set_ai_findings():
    data = request.get_json(force=True) or {}
    findings = data.get("findings") or []
    if isinstance(findings, list):
        app_state.last_ai_findings = [
            {
                "category": str(finding.get("category", "")),
                "text": str(finding.get("text", "")),
                "context": str(finding.get("context", "")),
            }
            for finding in findings
            if isinstance(finding, dict)
        ]
        app_state.last_ai_findings_file_name = str(data.get("file_name") or "")
    return jsonify({"ok": True, "count": len(app_state.last_ai_findings)})


@reports_bp.get("/report")
def report():
    if app_state.last_result is None:
        return "Ingen rapport tilgjengelig.", 404
    rendered = generate_html(
        app_state.last_result,
        api_base=f"http://127.0.0.1:{app_state.port}",
        ai_findings=ai_findings_for_report(),
    )
    return rendered, 200, {"Content-Type": "text/html; charset=utf-8"}


@reports_bp.post("/open-report")
def open_report():
    if app_state.last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig ennå."})
    try:
        webbrowser.open(f"http://127.0.0.1:{app_state.port}/report")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)})


@reports_bp.get("/report/pdf")
def report_pdf():
    if app_state.last_result is None:
        return "Ingen rapport tilgjengelig.", 404
    try:
        import fitz  # noqa: PLC0415
        from xlent_scanner.report import ai_severity  # noqa: PLC0415

        colors = {
            "grønn": (0.18, 0.69, 0.31),
            "gul": (0.85, 0.60, 0.15),
            "rød": (0.87, 0.22, 0.22),
            "svart": (0.61, 0.15, 0.69),
        }
        result = app_state.last_result
        doc = fitz.open()

        def new_page():
            return doc.new_page(width=595, height=842), 54

        def add_text(page, y, text, size=10, color=(0.85, 0.88, 0.93), bold=False):
            page.insert_text(
                (54, y),
                text,
                fontsize=size,
                fontname="hebo" if bold else "helv",
                color=color,
            )
            return y + size + 4

        page, y = new_page()
        y = add_text(page, y, "XLENT Compliance-scanner", 18, (0.31, 0.56, 1.0), True)
        y = add_text(page, y, f"Fil: {result.file_name}", 11)
        y = add_text(page, y, f"Dato: {datetime.now().strftime('%d.%m.%Y  %H:%M')}", 9)
        y += 6
        risk_color = colors.get(result.risk_level, (0.85, 0.88, 0.93))
        y = add_text(
            page,
            y,
            f"Risikonivå: {result.risk_level.upper()}  –  {result.risk_summary}",
            12,
            risk_color,
            True,
        )
        y = add_text(page, y, result.recommended_action, 9, (0.72, 0.77, 0.85))
        y += 18

        if not result.findings:
            y = add_text(page, y, "Ingen sensitive funn oppdaget.", 10, colors["grønn"])
        else:
            y = add_text(page, y, f"Funn ({len(result.findings)})", 11, bold=True)
            for finding in result.findings:
                if y > 800:
                    page, y = new_page()
                y = add_text(
                    page,
                    y,
                    f"[{finding.category}]  {finding.text[:120]}",
                    9,
                    colors.get(finding.severity, (0.72, 0.77, 0.85)),
                )
                if finding.context:
                    y = add_text(page, y, f"    {finding.context[:140]}", 7.5, (0.5, 0.57, 0.68))

        ai_findings = ai_findings_for_report()
        if ai_findings:
            if y > 770:
                page, y = new_page()
            y += 12
            y = add_text(page, y, f"AI-dybdeskann-funn ({len(ai_findings)})", 11, bold=True)
            for finding in ai_findings:
                if y > 800:
                    page, y = new_page()
                category = str(finding.get("category", ""))
                y = add_text(
                    page,
                    y,
                    f"[{category}]  {str(finding.get('text', ''))[:120]}",
                    9,
                    colors.get(ai_severity(category), (0.72, 0.77, 0.85)),
                )

        pdf_bytes = doc.tobytes()
        doc.close()
        filename = f"{Path(result.file_name).stem}-rapport.pdf"
        return pdf_bytes, 200, {
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
    except Exception as exc:
        LOGGER.error("report/pdf failed: %s", traceback.format_exc())
        return f"PDF-generering feilet: {exc}", 500


def _selected_findings(data: dict):
    result = app_state.last_result
    indices = data.get("indices", [])
    selected = [
        result.findings[index]
        for index in indices
        if isinstance(index, int) and 0 <= index < len(result.findings)
    ]
    ai_findings = findings_from_payload(data)
    selected.extend(as_model_findings(ai_findings))
    return selected, ai_findings


@reports_bp.post("/anonymize")
def anonymize():
    if app_state.last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig."})
    if not app_state.last_result.original_text:
        return jsonify({"error": "Originaltekst ikke tilgjengelig. Re-skann filen."})
    data = request.get_json(force=True)
    selected, _ai_findings = _selected_findings(data)
    cleaned = anonymize_text(app_state.last_result.original_text, selected)
    output_format = (data.get("format") or "md").lower()
    if output_format not in {"md", "pdf"}:
        output_format = "md"
    stem = Path(app_state.last_result.file_name).stem
    output = _unique_output(f"{stem}-anonymisert", f".{output_format}")
    if output_format == "pdf":
        try:
            write_text_pdf(cleaned, output, title=f"{stem} – anonymisert")
        except Exception:
            LOGGER.error("anonymize pdf failed: %s", traceback.format_exc())
            return jsonify({
                "error": "PDF-generering feilet. Se loggfil for tekniske detaljer.",
                "error_code": "pdfGenerateFailed",
            })
    else:
        output.write_text(cleaned, encoding="utf-8")
    return jsonify({"ok": True, "path": str(output)})


def _unique_output(stem: str, suffix: str) -> Path:
    output = _downloads_dir() / f"{stem}{suffix}"
    counter = 1
    while output.exists():
        output = _downloads_dir() / f"{stem}-{counter}{suffix}"
        counter += 1
    return output


def _replacement_map(data: dict) -> tuple[list, dict[str, str]]:
    selected, ai_findings = _selected_findings(data)
    replacements = build_replacements(selected)
    for text in replacement_texts(ai_findings):
        replacements.setdefault(text, "[ANONYMISERT]")
    return selected, replacements


@reports_bp.post("/redaction/preview")
def redaction_preview():
    if app_state.last_result is None:
        return jsonify({"ok": False, "error": "Ingen rapport tilgjengelig."})
    selected, replacements = _replacement_map(request.get_json(force=True))
    preview = [
        {"original": old, "replacement": new}
        for old, new in sorted(replacements.items(), key=lambda item: item[0].casefold())
    ]
    skipped = [
        {
            "category": finding.category,
            "text": finding.text,
            "reason": "Kan ikke anonymiseres sikkert direkte.",
        }
        for finding in selected
        if (finding.raw_text or finding.text) not in replacements
        and not finding.category.startswith("🤖")
    ]
    return jsonify({
        "ok": True,
        "selected_count": len(selected),
        "replacement_count": len(preview),
        "preview": preview,
        "skipped": skipped,
        "pdf_caveat": bool(
            app_state.last_path and app_state.last_path.suffix.lower() == ".pdf"
        ),
    })


@reports_bp.post("/patch")
def patch():
    if app_state.last_result is None or app_state.last_path is None:
        return jsonify({"error": "Ingen skannet fil tilgjengelig."})
    suffix = app_state.last_path.suffix.lower()
    if suffix not in SUPPORTED_PATCH_SUFFIXES:
        return jsonify({"error": f"In-place anonymisering støttes ikke for {suffix}."})
    data = request.get_json(force=True)
    _selected, replacements = _replacement_map(data)
    strip_annotations = bool(data.get("strip_annotations", False))
    if not replacements and not strip_annotations:
        return jsonify({"error": "Ingen av de valgte funnene kan anonymiseres direkte."})
    output = _unique_output(f"{app_state.last_path.stem}-anonymisert", suffix)
    try:
        patch_file(
            app_state.last_path,
            replacements,
            output,
            strip_annotations=strip_annotations,
        )
    except Exception as exc:
        LOGGER.error("patch failed: %s", traceback.format_exc())
        if suffix == ".pdf":
            return jsonify({
                "error": "PDF-anonymisering feilet. Prøv PDF-rapport eller kontakt support med loggfil.",
                "error_code": "pdfPatchFailed",
            })
        return jsonify({"error": str(exc)})
    return jsonify({"ok": True, "path": str(output)})


@reports_bp.post("/export/json")
def export_json():
    if app_state.last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig."})
    result = app_state.last_result
    data = {
        "file_name": result.file_name,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "risk_level": result.risk_level,
        "scan_status": result.scan_status,
        "risk_summary": result.risk_summary,
        "language": result.language,
        "findings": [
            {
                "severity": finding.severity,
                "category": finding.category,
                "text": finding.text,
                "context": finding.context,
            }
            for finding in result.findings
        ],
    }
    output = _unique_output(f"{Path(result.file_name).stem}-funn", ".json")
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "path": str(output)})


@reports_bp.post("/export/csv")
def export_csv():
    if app_state.last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig."})
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["severity", "category", "text", "context"])
    for finding in app_state.last_result.findings:
        writer.writerow([
            finding.severity,
            finding.category,
            finding.text,
            finding.context,
        ])
    output = _unique_output(
        f"{Path(app_state.last_result.file_name).stem}-funn",
        ".csv",
    )
    output.write_text(buffer.getvalue(), encoding="utf-8-sig")
    return jsonify({"ok": True, "path": str(output)})
