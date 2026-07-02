"""Eksport, audit og batch-redaction for mappeskann-resultater."""
from __future__ import annotations

import csv
import html
import io
import json
import tempfile
from datetime import datetime
from pathlib import Path

from xlent_scanner.anonymize import build_replacements
from xlent_scanner.models import ScanResult
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES, patch_file

from lib.exports import downloads_dir, write_text_pdf


def _top_findings(result: ScanResult, limit: int = 5) -> str:
    parts = []
    for f in result.findings:
        if f.category.startswith("⚠") or f.severity == "grønn":
            continue
        parts.append(f"{f.category}: {f.text}")
        if len(parts) >= limit:
            break
    return " ; ".join(parts)


def _rows(results: list[ScanResult]) -> list[dict]:
    return [
        {
            "relative_path": r.relative_path or r.file_name,
            "risk_level": r.risk_level,
            "scan_status": r.scan_status,
            "finding_count": len(r.findings),
            "file_size": r.file_size,
            "text_length": r.text_length,
            "error": r.error or "",
            "warning": r.warning or "",
            "top_findings": _top_findings(r),
        }
        for r in results
    ]


def export_json_bytes(results: list[ScanResult], folder: str) -> bytes:
    payload = {
        "folder": folder,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(results),
        "files": _rows(results),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def export_csv_bytes(results: list[ScanResult]) -> bytes:
    fieldnames = [
        "relative_path", "risk_level", "scan_status", "finding_count",
        "file_size", "text_length", "error", "warning", "top_findings",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in _rows(results):
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")


def audit_html(results: list[ScanResult], folder: str) -> str:
    risk_bg = {"svart": "#111827", "rød": "#b91c1c", "gul": "#a16207", "grønn": "#15803d"}
    rows_html = []
    for row in _rows(results):
        color = risk_bg.get(row["risk_level"], "#555")
        rows_html.append(
            f"<tr>"
            f"<td style='padding:6px 10px'><span style='background:{color};color:#fff;"
            f"padding:2px 8px;border-radius:4px'>{html.escape(row['risk_level'])}</span></td>"
            f"<td style='padding:6px 10px'>{html.escape(row['relative_path'])}</td>"
            f"<td style='padding:6px 10px;text-align:right'>{row['finding_count']}</td>"
            f"<td style='padding:6px 10px'>{html.escape(row['top_findings'])}</td>"
            f"</tr>"
        )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>XLENT mappeskann-rapport</title></head>"
        "<body style='font-family:system-ui,sans-serif;max-width:1000px;margin:24px auto'>"
        f"<h1>XLENT mappeskann-rapport</h1>"
        f"<p><b>Mappe:</b> {html.escape(folder)}<br>"
        f"<b>Dato:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}<br>"
        f"<b>Filer:</b> {len(results)}</p>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<tr style='background:#f3f4f6;text-align:left'>"
        "<th style='padding:6px 10px'>Risiko</th><th style='padding:6px 10px'>Fil</th>"
        "<th style='padding:6px 10px'>Funn</th><th style='padding:6px 10px'>Toppfunn</th></tr>"
        + "".join(rows_html)
        + "</table></body></html>"
    )


def audit_pdf_bytes(results: list[ScanResult], folder: str) -> bytes:
    lines = [
        f"Mappe: {folder}",
        f"Dato: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        f"Filer: {len(results)}",
        "",
    ]
    for row in _rows(results):
        lines.append(f"{row['risk_level'].upper()} | {row['relative_path']} | {row['finding_count']} funn | {row['top_findings']}")
        if row["error"]:
            lines.append(f"  Feil: {row['error']}")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="xlent-audit-") as tmp:
        tmp_path = Path(tmp.name)
    try:
        write_text_pdf("\n".join(lines), tmp_path, title="XLENT mappeskann-rapport")
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def batch_redact(results: list[ScanResult], strip_annotations: bool = False) -> dict:
    """Anonymiser flere filer in-place til en tidsstemplet mappe i Downloads."""
    out_root = downloads_dir() / f"XLENT-redacted-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out_root.mkdir(parents=True, exist_ok=True)
    outputs: list[dict] = []
    errors: list[dict] = []
    for r in results:
        name = r.relative_path or r.file_name
        source = Path(r.source_path) if r.source_path else None
        if source is None or not source.exists():
            errors.append({"file": name, "error": "Originalfilen finnes ikke lenger."})
            continue
        if source.suffix.lower() not in SUPPORTED_PATCH_SUFFIXES:
            errors.append({"file": name, "error": "Formatet støttes ikke for redaction."})
            continue
        findings = [f for f in r.findings if not f.category.startswith("⚠") and f.severity != "grønn"]
        replacements = build_replacements(findings)
        if not replacements:
            errors.append({"file": name, "error": "Ingen direkte redigerbare funn."})
            continue
        relative = Path(name)
        out = out_root / relative.parent / f"{relative.stem}-redacted{source.suffix}"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            patch_file(source, replacements, out, strip_annotations=strip_annotations)
            outputs.append({"file": name, "path": str(out)})
        except Exception as exc:  # noqa: BLE001
            errors.append({"file": name, "error": str(exc)})
    if not outputs and errors:
        import shutil
        shutil.rmtree(out_root, ignore_errors=True)
    return {"folder": str(out_root), "outputs": outputs, "errors": errors}
