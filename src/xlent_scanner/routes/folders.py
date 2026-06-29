"""Mappe-skanning, eksport, rapport og batch-redaction."""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request

from xlent_scanner.anonymize import build_replacements
from xlent_scanner.app_state import app_state
from xlent_scanner.history import add_history_entry
from xlent_scanner.models import ScanResult
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES
from xlent_scanner.report import generate_html
from xlent_scanner.routes.reports import write_text_pdf
from xlent_scanner.scanner import (
    DEFAULT_FOLDER_MAX_DEPTH,
    DEFAULT_FOLDER_MAX_FILES,
    build_folder_scan_plan,
)

LOGGER = logging.getLogger("xlent_scanner")
_FOLDER_SCAN_MAX_RESULTS = 10_000

_downloads_dir: Callable[[], Path]
_open_path: Callable[[Path], None]
_scan_file: Callable
_scan_folder: Callable
_patch_file: Callable

folders_bp = Blueprint("folders", __name__)


def create_folders_blueprint(
    *,
    downloads_dir: Callable[[], Path],
    open_path: Callable[[Path], None],
    scan_file_fn: Callable,
    scan_folder_fn: Callable,
    patch_file_fn: Callable,
) -> Blueprint:
    global _downloads_dir, _open_path, _scan_file, _scan_folder, _patch_file
    _downloads_dir = downloads_dir
    _open_path = open_path
    _scan_file = scan_file_fn
    _scan_folder = scan_folder_fn
    _patch_file = patch_file_fn
    return folders_bp


def _folder_scan_options(data: dict) -> dict:
    def _int(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(data.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    def _bool(name: str, default: bool = False) -> bool:
        value = data.get(name, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    return {
        "recursive": _bool("recursive", False),
        "max_files": _int("max_files", DEFAULT_FOLDER_MAX_FILES, 1, 10_000),
        "max_depth": _int("max_depth", DEFAULT_FOLDER_MAX_DEPTH, 0, 50),
    }


def _folder_finding_summary(result: ScanResult, limit: int = 8) -> list[dict]:
    rows = []
    for finding in result.findings:
        if finding.category.startswith("⚠"):
            continue
        rows.append({
            "category": finding.category,
            "text": finding.text,
            "severity": finding.severity,
            "context": finding.context,
        })
        if len(rows) >= limit:
            break
    return rows


def _remember_folder_result(result: ScanResult) -> str:
    report_id = uuid.uuid4().hex
    with app_state.folder_scan_lock:
        app_state.folder_scan_results[report_id] = result
        while len(app_state.folder_scan_results) > _FOLDER_SCAN_MAX_RESULTS:
            oldest = next(iter(app_state.folder_scan_results))
            app_state.folder_scan_results.pop(oldest, None)
    return report_id


def folder_result_row(result: ScanResult, report_id: str | None = None) -> dict:
    report_id = report_id or _remember_folder_result(result)
    return {
        "file_name": result.file_name,
        "relative_path": result.relative_path or result.file_name,
        "report_id": report_id,
        "risk_level": result.risk_level,
        "scan_status": result.scan_status,
        "finding_count": len(result.findings),
        "findings_summary": _folder_finding_summary(result),
        "error": result.error,
        "file_size": result.file_size,
        "text_length": result.text_length,
        "warning": result.warning,
        "warning_code": result.warning_code,
    }


def folder_job_snapshot(job_id: str) -> dict | None:
    job = app_state.folder_job_manager.snapshot(job_id)
    if not job:
        return None
    return {
        "ok": True,
        "job_id": job_id,
        "status": job["status"],
        "folder": job.get("folder", ""),
        "recursive": job.get("recursive", False),
        "total": job.get("total", 0),
        "completed": job.get("completed", 0),
        "folder_count": job.get("folder_count", 0),
        "truncated": job.get("truncated", False),
        "max_files": job.get("max_files", DEFAULT_FOLDER_MAX_FILES),
        "max_depth": job.get("max_depth", DEFAULT_FOLDER_MAX_DEPTH),
        "cancel_requested": job.get("cancel_requested", False),
        "error": job.get("error", ""),
        "files": list(job.get("files", [])),
    }


def folder_job_from_request(data: dict | None = None) -> tuple[str, dict]:
    job_id = str(
        (data or {}).get("job_id")
        or app_state.folder_job_manager.last_job_id
        or ""
    )
    if not job_id:
        raise ValueError("Ingen mappeskann tilgjengelig.")
    job = app_state.folder_job_manager.snapshot(job_id)
    if not job:
        raise ValueError("Ukjent mappeskann-jobb.")
    job["files"] = list(job.get("files", []))
    return job_id, job


def folder_result_for_report_id(report_id: str) -> ScanResult:
    with app_state.folder_scan_lock:
        result = app_state.folder_scan_results.get(report_id)
    if result is None:
        raise ValueError("Ukjent filrapport.")
    return result


def _folder_export_rows(job: dict) -> list[dict]:
    rows = []
    for row in job.get("files", []):
        rows.append({
            "relative_path": row.get("relative_path", ""),
            "file_name": row.get("file_name", ""),
            "risk_level": row.get("risk_level", ""),
            "scan_status": row.get("scan_status", "success"),
            "finding_count": row.get("finding_count", 0),
            "file_size": row.get("file_size", 0),
            "text_length": row.get("text_length", 0),
            "error": row.get("error") or "",
            "warning": row.get("warning") or "",
            "top_findings": "; ".join(
                f"{finding.get('category', '')}: {finding.get('text', '')}"
                for finding in (row.get("findings_summary") or [])
            ),
        })
    return rows


def _safe_csv_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _folder_audit_html(job_id: str, job: dict) -> str:
    rows = _folder_export_rows(job)
    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['relative_path']))}</td>"
            f"<td>{html.escape(str(row['risk_level']))}</td>"
            f"<td>{html.escape(str(row['finding_count']))}</td>"
            f"<td>{html.escape(str(row['top_findings']))}</td>"
            f"<td>{html.escape(str(row['error']))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="nb">
<head>
  <meta charset="utf-8">
  <title>XLENT mappeskann-rapport</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #d9dee8; padding: 7px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef3f8; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }}
    .meta {{ color: #5d6980; line-height: 1.6; margin-bottom: 18px; }}
  </style>
</head>
<body>
  <h1>XLENT mappeskann-rapport</h1>
  <div class="meta">
    <div>Jobb: {html.escape(job_id)}</div>
    <div>Mappe: {html.escape(str(job.get("folder", "")))}</div>
    <div>Tidspunkt: {datetime.now().isoformat(timespec="seconds")}</div>
    <div>Rekursiv: {html.escape(str(job.get("recursive", False)))}</div>
    <div>Filer: {html.escape(str(job.get("completed", 0)))} / {html.escape(str(job.get("total", 0)))}</div>
    <div>Status: {html.escape(str(job.get("status", "")))}</div>
  </div>
  <table>
    <thead><tr><th>Fil</th><th>Risiko</th><th>Funn</th><th>Toppfunn</th><th>Feil</th></tr></thead>
    <tbody>{''.join(table_rows)}</tbody>
  </table>
</body>
</html>"""


def _run_folder_scan_job(
    job_id: str,
    folder_path: str,
    ignore_xlent: bool,
    language: str,
    scan_profile: str,
    opts: dict,
) -> None:
    try:
        plan = build_folder_scan_plan(folder_path, **opts)
        app_state.folder_job_manager.update(job_id, {
            "status": "running",
            "folder": plan["folder"],
            "recursive": plan["recursive"],
            "total": plan["file_count"],
            "folder_count": plan["folder_count"],
            "truncated": plan["truncated"],
            "max_files": plan["max_files"],
            "max_depth": plan["max_depth"],
        })
        root = Path(folder_path)
        for file_path in plan["files"]:
            with app_state.folder_job_manager.mutate(job_id) as job:
                if job is None or job.get("cancel_requested"):
                    if job is not None:
                        job.update(status="cancelled", completed_at=time.time())
                    return
            try:
                result = _scan_file(
                    file_path,
                    ignore_xlent=ignore_xlent,
                    language=language,
                    scan_profile=scan_profile,
                )
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise
                result = _scan_file(file_path, ignore_xlent=ignore_xlent, language=language)
            result.relative_path = str(Path(file_path).relative_to(root))
            result.source_path = str(file_path)
            row = folder_result_row(result)
            add_history_entry(
                file_name=result.file_name,
                risk_level=result.risk_level,
                finding_count=len(result.findings),
                file_size=result.file_size,
                source="batch",
            )
            with app_state.folder_job_manager.mutate(job_id) as job:
                if job is None:
                    return
                job["files"].append(row)
                job["completed"] = len(job["files"])
        with app_state.folder_job_manager.mutate(job_id) as job:
            if job is not None:
                job["status"] = "cancelled" if job.get("cancel_requested") else "completed"
                job["completed_at"] = time.time()
    except Exception as exc:
        LOGGER.error("folder scan job failed: %s", traceback.format_exc())
        app_state.folder_job_manager.update(
            job_id,
            status="error",
            error=str(exc),
            completed_at=time.time(),
        )


@folders_bp.post("/scan-folder/preview")
def scan_folder_preview_endpoint():
    try:
        data = request.get_json(force=True)
        folder_path = data.get("folder_path", "")
        opts = _folder_scan_options(data)
        LOGGER.info("scan-folder preview path=%s recursive=%s", folder_path, opts["recursive"])
        plan = build_folder_scan_plan(folder_path, **opts)
        return jsonify({
            "ok": True,
            "folder": plan["folder"],
            "recursive": plan["recursive"],
            "file_count": plan["file_count"],
            "folder_count": plan["folder_count"],
            "truncated": plan["truncated"],
            "max_files": plan["max_files"],
            "max_depth": plan["max_depth"],
            "samples": plan["samples"],
            "excluded_dirs": plan["excluded_dirs"],
        })
    except Exception as exc:
        LOGGER.error("scan-folder preview failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/scan-folder")
def scan_folder_endpoint():
    try:
        data = request.get_json(force=True)
        folder_path = data.get("folder_path", "")
        ignore_xlent = bool(data.get("ignore_xlent", False))
        language = data.get("language", "auto")
        scan_profile = data.get("scan_profile", "normal")
        opts = _folder_scan_options(data)
        plan = build_folder_scan_plan(folder_path, **opts)
        results = _scan_folder(
            folder_path,
            ignore_xlent=ignore_xlent,
            language=language,
            scan_profile=scan_profile,
            **opts,
        )
        summary = []
        for result in results:
            add_history_entry(
                file_name=result.file_name,
                risk_level=result.risk_level,
                finding_count=len(result.findings),
                file_size=result.file_size,
                source="batch",
            )
            summary.append(folder_result_row(result))
        return jsonify({
            "files": summary,
            "total": len(summary),
            "folder_count": plan["folder_count"],
            "truncated": plan["truncated"],
            "max_files": plan["max_files"],
            "max_depth": plan["max_depth"],
            "recursive": plan["recursive"],
        })
    except Exception as exc:
        LOGGER.error("scan-folder endpoint failed: %s", traceback.format_exc())
        return jsonify({"error": str(exc)})


@folders_bp.post("/scan-folder/start")
def scan_folder_start_endpoint():
    try:
        data = request.get_json(force=True)
        folder_path = data.get("folder_path", "")
        ignore_xlent = bool(data.get("ignore_xlent", False))
        language = data.get("language", "auto")
        scan_profile = data.get("scan_profile", "normal")
        opts = _folder_scan_options(data)
        job_id = app_state.folder_job_manager.create({
            "status": "queued",
            "folder": folder_path,
            "recursive": opts["recursive"],
            "total": 0,
            "completed": 0,
            "folder_count": 0,
            "truncated": False,
            "max_files": opts["max_files"],
            "max_depth": opts["max_depth"],
            "cancel_requested": False,
            "error": "",
            "files": [],
        })
        threading.Thread(
            target=_run_folder_scan_job,
            args=(job_id, folder_path, ignore_xlent, language, scan_profile, opts),
            daemon=True,
            name=f"folder-scan-{job_id[:8]}",
        ).start()
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        LOGGER.error("scan-folder/start failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.get("/scan-folder/status/<job_id>")
def scan_folder_status_endpoint(job_id: str):
    snapshot = folder_job_snapshot(job_id)
    if snapshot is None:
        return jsonify({"ok": False, "error": "Ukjent mappeskann-jobb."}), 404
    return jsonify(snapshot)


@folders_bp.post("/scan-folder/cancel/<job_id>")
def scan_folder_cancel_endpoint(job_id: str):
    if not app_state.folder_job_manager.cancel(job_id):
        return jsonify({"ok": False, "error": "Ukjent mappeskann-jobb."}), 404
    return jsonify({"ok": True, "job_id": job_id})


@folders_bp.post("/folder-export/json")
def folder_export_json_endpoint():
    try:
        job_id, job = folder_job_from_request(request.get_json(force=True) or {})
        payload = {
            "job_id": job_id,
            "folder": job.get("folder", ""),
            "status": job.get("status", ""),
            "recursive": job.get("recursive", False),
            "total": job.get("total", 0),
            "completed": job.get("completed", 0),
            "truncated": job.get("truncated", False),
            "files": _folder_export_rows(job),
        }
        out = _unique_download_path(f"xlent-folder-scan-{job_id[:8]}", ".json")
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"ok": True, "path": str(out)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


def _unique_download_path(stem: str, suffix: str) -> Path:
    out = _downloads_dir() / f"{stem}{suffix}"
    counter = 1
    while out.exists():
        out = _downloads_dir() / f"{stem}-{counter}{suffix}"
        counter += 1
    return out


@folders_bp.post("/folder-export/csv")
def folder_export_csv_endpoint():
    try:
        job_id, job = folder_job_from_request(request.get_json(force=True) or {})
        rows = _folder_export_rows(job)
        buf = io.StringIO()
        fieldnames = [
            "relative_path", "risk_level", "scan_status", "finding_count",
            "file_size", "text_length", "error", "warning", "top_findings",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _safe_csv_cell(row.get(key, "")) for key in fieldnames})
        out = _unique_download_path(f"xlent-folder-scan-{job_id[:8]}", ".csv")
        out.write_text(buf.getvalue(), encoding="utf-8-sig")
        return jsonify({"ok": True, "path": str(out)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/folder-audit/html")
def folder_audit_html_endpoint():
    try:
        job_id, job = folder_job_from_request(request.get_json(force=True) or {})
        out = _unique_download_path(f"xlent-folder-audit-{job_id[:8]}", ".html")
        out.write_text(_folder_audit_html(job_id, job), encoding="utf-8")
        return jsonify({"ok": True, "path": str(out)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/folder-audit/pdf")
def folder_audit_pdf_endpoint():
    try:
        job_id, job = folder_job_from_request(request.get_json(force=True) or {})
        lines = [
            "XLENT mappeskann-rapport",
            f"Jobb: {job_id}",
            f"Mappe: {job.get('folder', '')}",
            f"Status: {job.get('status', '')}",
            f"Filer: {job.get('completed', 0)} / {job.get('total', 0)}",
            "",
        ]
        for row in _folder_export_rows(job):
            lines.append(
                f"{row['risk_level'].upper()} | {row['relative_path']} | "
                f"{row['finding_count']} funn | {row['top_findings']}"
            )
            if row["error"]:
                lines.append(f"  Feil: {row['error']}")
        out = _unique_download_path(f"xlent-folder-audit-{job_id[:8]}", ".pdf")
        write_text_pdf("\n".join(lines), out, title="XLENT mappeskann-rapport")
        return jsonify({"ok": True, "path": str(out)})
    except Exception as exc:
        LOGGER.error("folder-audit/pdf failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/folder-file/open")
def folder_file_open_endpoint():
    try:
        result = folder_result_for_report_id(
            str((request.get_json(force=True) or {}).get("report_id") or "")
        )
        path = Path(result.source_path)
        if not path.exists():
            return jsonify({"ok": False, "error": "Filen finnes ikke lenger."})
        _open_path(path)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/folder-file/reveal")
def folder_file_reveal_endpoint():
    try:
        result = folder_result_for_report_id(
            str((request.get_json(force=True) or {}).get("report_id") or "")
        )
        path = Path(result.source_path)
        if not path.exists():
            return jsonify({"ok": False, "error": "Filen finnes ikke lenger."})
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", f"/select,{path}"])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/folder-redact")
def folder_redact_endpoint():
    try:
        data = request.get_json(force=True) or {}
        report_ids = [str(value) for value in data.get("report_ids") or [] if str(value)]
        strip_annotations = bool(data.get("strip_annotations", False))
        if not report_ids:
            return jsonify({"ok": False, "error": "Ingen filer valgt."})
        out_root = _downloads_dir() / f"XLENT-redacted-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        out_root.mkdir(parents=True, exist_ok=True)
        outputs = []
        errors = []
        for report_id in report_ids:
            try:
                result = folder_result_for_report_id(report_id)
                source = Path(result.source_path)
                if not source.exists():
                    errors.append({"file": result.relative_path or result.file_name, "error": "Originalfilen finnes ikke lenger."})
                    continue
                if source.suffix.lower() not in SUPPORTED_PATCH_SUFFIXES:
                    errors.append({"file": result.relative_path or result.file_name, "error": "Formatet støttes ikke for redaction."})
                    continue
                findings = [
                    finding
                    for finding in result.findings
                    if not finding.category.startswith("⚠") and finding.severity != "grønn"
                ]
                replacements = build_replacements(findings)
                if not replacements:
                    errors.append({"file": result.relative_path or result.file_name, "error": "Ingen direkte redigerbare funn."})
                    continue
                relative = Path(result.relative_path or result.file_name)
                out = out_root / relative.parent / f"{relative.stem}-redacted{source.suffix}"
                out.parent.mkdir(parents=True, exist_ok=True)
                _patch_file(source, replacements, out, strip_annotations=strip_annotations)
                outputs.append({"file": result.relative_path or result.file_name, "path": str(out)})
            except Exception as exc:
                errors.append({"file": report_id, "error": str(exc)})
        if not outputs and errors:
            shutil.rmtree(out_root, ignore_errors=True)
        return jsonify({"ok": bool(outputs), "folder": str(out_root), "outputs": outputs, "errors": errors})
    except Exception as exc:
        LOGGER.error("folder-redact failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.get("/folder-report/<report_id>")
def folder_report(report_id: str):
    with app_state.folder_scan_lock:
        result = app_state.folder_scan_results.get(report_id)
    if result is None:
        return "Ingen rapport tilgjengelig for denne filen.", 404
    report_html = generate_html(
        result,
        api_base=f"http://127.0.0.1:{app_state.port}",
        ai_findings=[],
    )
    return report_html, 200, {"Content-Type": "text/html; charset=utf-8"}
