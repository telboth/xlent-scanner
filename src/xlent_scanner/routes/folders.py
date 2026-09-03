"""Mappe-skanning, eksport, rapport og batch-redaction."""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
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

from xlent_scanner.access_audit import audit_containing_folder_access
from xlent_scanner.anonymize import build_replacements
from xlent_scanner.app_state import app_state
from xlent_scanner.audit_trail import AuditTrail
from xlent_scanner.history import add_history_entry
from xlent_scanner.microsoft_graph import sharepoint_access_for_local_path
from xlent_scanner.models import ScanResult
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES
from xlent_scanner.purview_classification import (
    classification_display_text,
    classification_pdf_color,
    classification_style_key,
    normalize_ui_language,
    purview_translation,
)
from xlent_scanner.redaction_audit import record_redaction
from xlent_scanner.report import generate_html
from xlent_scanner.routes.reports import write_text_pdf
from xlent_scanner.scanner import (
    DEFAULT_FOLDER_MAX_DEPTH,
    DEFAULT_FOLDER_MAX_FILES,
    build_folder_scan_plan,
)

LOGGER = logging.getLogger("xlent_scanner")


def _record_folder_scan_audit(result: ScanResult, path: Path) -> None:
    AuditTrail().record_scan(
        result,
        document_path=path,
        source="batch",
    )
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

    raw_modified_before = str(data.get("modified_before") or "").strip()
    modified_before = None
    if raw_modified_before:
        try:
            modified_before = datetime.strptime(raw_modified_before, "%Y-%m-%d")
        except ValueError:
            raise ValueError("modified_before må være en gyldig dato i formatet YYYY-MM-DD.") from None
        if modified_before.date() > datetime.now().date():
            raise ValueError("modified_before kan ikke være en fremtidig dato.")

    return {
        "recursive": _bool("recursive", False),
        "max_files": _int("max_files", DEFAULT_FOLDER_MAX_FILES, 1, 10_000),
        "max_depth": _int("max_depth", DEFAULT_FOLDER_MAX_DEPTH, 0, 50),
        "modified_before": modified_before,
    }


def _request_bool(data: dict, name: str, default: bool = False) -> bool:
    value = data.get(name, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ja", "on"}
    return bool(value)


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
        "access_summary": result.access_summary,
        "sharepoint_access_summary": result.sharepoint_access_summary,
        "purview_classification": result.purview_classification,
        "is_redacted": _is_redacted_file_name(result.relative_path or result.file_name),
    }


def _is_redacted_file_name(value: str) -> bool:
    return bool(re.search(r"-redacted(?:-\d+)?$", Path(value).stem, flags=re.IGNORECASE))


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
        "modified_before": job.get("modified_before", ""),
        "age_excluded_count": job.get("age_excluded_count", 0),
        "metadata_error_count": job.get("metadata_error_count", 0),
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


def _folder_export_rows(job: dict, language: str = "nb") -> list[dict]:
    language = normalize_ui_language(language)
    rows = []
    for row in job.get("files", []):
        access = row.get("access_summary") or {}
        sharepoint = row.get("sharepoint_access_summary") or {}
        classification = row.get("purview_classification") or {}
        classification_status = str(classification.get("status") or "")
        classification_display = classification_display_text(classification, language)
        access_level = access.get("access_level", "")
        access_status = {
            "broad": "Bred tilgang",
            "shared_local": "Delt lokalt",
            "restricted": "Begrenset",
        }.get(access_level, "Ikke tilgjengelig" if access and not access.get("available") else "Ikke kontrollert")
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
            "purview_status": classification_status,
            "purview_classification": classification_display,
            "purview_label_id": classification.get("label_id", ""),
            "purview_source": classification.get("source", ""),
            "purview_error": classification.get("error", ""),
            "access_source": access.get("source", ""),
            "access_level": access_level,
            "access_status": access_status,
            "access_entries": access.get("entries_total", ""),
            "access_broad": ", ".join(access.get("broad_identities", []) or []),
            "access_shared": ", ".join(access.get("shared_identities", []) or []),
            "sharepoint_access_level": sharepoint.get("access_level", ""),
            "sharepoint_access_status": {
                "public": "Offentlig lenke",
                "organization": "Hele organisasjonen",
                "group": "Delt med gruppe",
                "specific": "Bestemte personer",
                "restricted": "Begrenset",
                "not_checked": "Ikke kontrollert",
            }.get(sharepoint.get("access_level", ""), "Ikke relevant" if not sharepoint else "Ukjent"),
            "sharepoint_identities": ", ".join(
                (sharepoint.get("group_identities", []) or []) +
                (sharepoint.get("person_identities", []) or [])
            ),
            "top_findings": "; ".join(
                f"{finding.get('category', '')}: {finding.get('text', '')}"
                for finding in (row.get("findings_summary") or [])
            ),
            "filter_modified_before": job.get("modified_before", ""),
            "filter_age_excluded_count": job.get("age_excluded_count", 0),
            "filter_metadata_error_count": job.get("metadata_error_count", 0),
        })
    return rows


def _safe_csv_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _folder_audit_html(job_id: str, job: dict, language: str = "nb") -> str:
    language = normalize_ui_language(language)
    rows = _folder_export_rows(job, language)
    table_rows = []
    for row in rows:
        classification = {
            "status": row["purview_status"],
            "display_name": row["purview_classification"],
        }
        style = classification_style_key(classification)
        purview_class = "purview-neutral" if style == "neutral" else f"purview-badge purview-{style}"
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['relative_path']))}</td>"
            f"<td>{html.escape(str(row['risk_level']))}</td>"
            f"<td>{html.escape(str(row['finding_count']))}</td>"
            f"<td><span class=\"{purview_class}\">"
            f"{html.escape(classification_display_text(classification, language))}</span></td>"
            f"<td>{html.escape(str(row['access_status']))}"
            f"{': ' if row['access_broad'] or row['access_shared'] else ''}"
            f"{html.escape(str(row['access_broad'] or row['access_shared']))}</td>"
            f"<td>{html.escape(str(row['sharepoint_access_status']))}"
            f"{': ' if row['sharepoint_identities'] else ''}"
            f"{html.escape(str(row['sharepoint_identities']))}</td>"
            f"<td>{html.escape(str(row['top_findings']))}</td>"
            f"<td>{html.escape(str(row['error']))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <title>XLENT mappeskann-rapport</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 28px; color: #172033; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #d9dee8; padding: 7px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef3f8; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }}
    .meta {{ color: #5d6980; line-height: 1.6; margin-bottom: 18px; }}
    .purview-badge {{ display: inline-block; padding: 2px 7px; border: 1px solid; border-radius: 999px; font-size: 11px; font-weight: 700; white-space: nowrap; }}
    .purview-public {{ background: #e8f5e9; color: #1f6f32; border-color: #91c99b; }}
    .purview-personal {{ background: #e7f1fb; color: #185c9d; border-color: #91b9df; }}
    .purview-limited {{ background: #fff4d6; color: #805000; border-color: #dbb85a; }}
    .purview-protected, .purview-regulated {{ background: #ffeadb; color: #944100; border-color: #df9b68; }}
    .purview-unknown {{ background: #f3eafb; color: #6f368f; border-color: #bd92d2; }}
    .purview-neutral {{ color: #5f6d7d; }}
    .purview-not-checked {{ border-style: dashed; background: transparent; color: #5f6d7d; border-color: #5f6d7d; }}
  </style>
</head>
<body>
  <h1>XLENT mappeskann-rapport</h1>
  <div class="meta">
    <div>Jobb: {html.escape(job_id)}</div>
    <div>Mappe: {html.escape(str(job.get("folder", "")))}</div>
    <div>Tidspunkt: {datetime.now().isoformat(timespec="seconds")}</div>
    <div>Rekursiv: {html.escape(str(job.get("recursive", False)))}</div>
    <div>Sist endret før: {html.escape(str(job.get("modified_before") or "Alle filer"))}</div>
    <div>Utelatt på grunn av dato: {html.escape(str(job.get("age_excluded_count", 0)))}</div>
    <div>Utelatt på grunn av metadatafeil: {html.escape(str(job.get("metadata_error_count", 0)))}</div>
    <div>Filer: {html.escape(str(job.get("completed", 0)))} / {html.escape(str(job.get("total", 0)))}</div>
    <div>Status: {html.escape(str(job.get("status", "")))}</div>
  </div>
  <table>
    <thead><tr><th>Fil</th><th>Risiko</th><th>Funn</th><th>{html.escape(purview_translation("folder_title", language))}</th><th>Lokal tilgang</th><th>SharePoint-tilgang</th><th>Toppfunn</th><th>Feil</th></tr></thead>
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
    pdf_mode: str,
    categories: list[str] | None,
    include_access_check: bool,
    include_purview_classification: bool,
    graph_drive_id: str,
    graph_sync_root: str,
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
            "modified_before": plan["modified_before"],
            "age_excluded_count": plan["age_excluded_count"],
            "metadata_error_count": plan["metadata_error_count"],
        })
        root = Path(folder_path)
        access_cache: dict[str, dict] = {}
        sharepoint_cache: dict[str, dict | None] = {}
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
                    pdf_mode=pdf_mode,
                    categories=categories,
                    include_access_check=False,
                    include_purview_classification=include_purview_classification,
                    graph_drive_id=graph_drive_id or None,
                    graph_sync_root=graph_sync_root or None,
                )
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise
                result = _scan_file(file_path, ignore_xlent=ignore_xlent, language=language)
            if include_access_check:
                result.access_summary = audit_containing_folder_access(file_path, access_cache)
                result.sharepoint_access_summary = sharepoint_access_for_local_path(
                    Path(file_path).parent,
                    drive_id=graph_drive_id or None,
                    sync_root=graph_sync_root or None,
                    cache=sharepoint_cache,
                )
                if result.sharepoint_access_summary is not None:
                    result.sharepoint_access_summary = {
                        **result.sharepoint_access_summary,
                        "scope": "containing_folder",
                        "scope_note": "Gjelder inneholdende SharePoint-mappe; unike filtillatelser er ikke kontrollert.",
                    }
                    result.access_summary = {
                        **result.access_summary,
                        "scope_note": (
                            result.access_summary.get("scope_note", "") +
                            " Dette er rettighetene til den lokale synkroniserte kopien, ikke SharePoint."
                        ).strip(),
                    }
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
            _record_folder_scan_audit(result, Path(file_path))
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
            "modified_before": plan["modified_before"],
            "age_excluded_count": plan["age_excluded_count"],
            "metadata_error_count": plan["metadata_error_count"],
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
        pdf_mode = data.get("scan_mode", data.get("pdf_mode", "auto"))
        categories = data.get("categories") if isinstance(data.get("categories"), list) else None
        include_access_check = _request_bool(data, "access_check", _request_bool(data, "include_access_check", False))
        include_purview_classification = _request_bool(
            data,
            "purview_classification",
            _request_bool(data, "include_purview_classification", True),
        )
        graph_drive_id = str(data.get("graph_drive_id") or data.get("drive_id") or "").strip()
        graph_sync_root = str(data.get("graph_sync_root") or data.get("sync_root") or "").strip()
        opts = _folder_scan_options(data)
        plan = build_folder_scan_plan(folder_path, **opts)
        results = _scan_folder(
            folder_path,
            ignore_xlent=ignore_xlent,
            language=language,
            scan_profile=scan_profile,
            pdf_mode=pdf_mode,
            categories=categories,
            include_access_check=include_access_check,
            include_purview_classification=include_purview_classification,
            graph_drive_id=graph_drive_id or None,
            graph_sync_root=graph_sync_root or None,
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
            result_path = Path(result.source_path) if result.source_path else Path(folder_path) / (result.relative_path or result.file_name)
            _record_folder_scan_audit(result, result_path)
            summary.append(folder_result_row(result))
        return jsonify({
            "files": summary,
            "total": len(summary),
            "folder_count": plan["folder_count"],
            "truncated": plan["truncated"],
            "max_files": plan["max_files"],
            "max_depth": plan["max_depth"],
            "recursive": plan["recursive"],
            "modified_before": plan["modified_before"],
            "age_excluded_count": plan["age_excluded_count"],
            "metadata_error_count": plan["metadata_error_count"],
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
        pdf_mode = data.get("scan_mode", data.get("pdf_mode", "auto"))
        categories = data.get("categories") if isinstance(data.get("categories"), list) else None
        include_access_check = _request_bool(data, "access_check", _request_bool(data, "include_access_check", False))
        include_purview_classification = _request_bool(
            data,
            "purview_classification",
            _request_bool(data, "include_purview_classification", True),
        )
        graph_drive_id = str(data.get("graph_drive_id") or data.get("drive_id") or "").strip()
        graph_sync_root = str(data.get("graph_sync_root") or data.get("sync_root") or "").strip()
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
            "modified_before": (
                opts["modified_before"].date().isoformat()
                if opts["modified_before"] else ""
            ),
            "age_excluded_count": 0,
            "metadata_error_count": 0,
            "cancel_requested": False,
            "error": "",
            "files": [],
        })
        threading.Thread(
            target=_run_folder_scan_job,
            args=(
                job_id, folder_path, ignore_xlent, language, scan_profile, pdf_mode,
                categories, include_access_check, include_purview_classification,
                graph_drive_id, graph_sync_root, opts,
            ),
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
        data = request.get_json(force=True) or {}
        job_id, job = folder_job_from_request(data)
        language = normalize_ui_language(data.get("lang"))
        payload = {
            "job_id": job_id,
            "folder": job.get("folder", ""),
            "status": job.get("status", ""),
            "recursive": job.get("recursive", False),
            "total": job.get("total", 0),
            "completed": job.get("completed", 0),
            "truncated": job.get("truncated", False),
            "modified_before": job.get("modified_before", ""),
            "age_excluded_count": job.get("age_excluded_count", 0),
            "metadata_error_count": job.get("metadata_error_count", 0),
            "files": _folder_export_rows(job, language),
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


def _unique_redacted_sibling(source: Path) -> Path:
    """Return a non-overwriting redacted filename beside the original file."""
    candidate = source.with_name(f"{source.stem}-redacted{source.suffix}")
    counter = 1
    while candidate.exists():
        candidate = source.with_name(f"{source.stem}-redacted-{counter}{source.suffix}")
        counter += 1
    return candidate


def _atomic_patch_file(
    source: Path,
    replacements: list,
    output: Path,
    *,
    strip_annotations: bool,
) -> None:
    """Patch beside the target and publish only a complete output file."""
    temporary = output.with_name(
        f".{output.stem}.tmp-{uuid.uuid4().hex}{output.suffix}"
    )
    try:
        _patch_file(
            source,
            replacements,
            temporary,
            strip_annotations=strip_annotations,
        )
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


@folders_bp.post("/folder-export/csv")
def folder_export_csv_endpoint():
    try:
        data = request.get_json(force=True) or {}
        job_id, job = folder_job_from_request(data)
        rows = _folder_export_rows(job, normalize_ui_language(data.get("lang")))
        buf = io.StringIO()
        fieldnames = [
            "relative_path", "risk_level", "scan_status", "finding_count",
            "file_size", "text_length", "purview_status", "purview_classification",
            "purview_label_id", "purview_source", "purview_error", "access_status", "sharepoint_access_status",
            "sharepoint_identities", "error", "warning", "top_findings",
            "filter_modified_before", "filter_age_excluded_count",
            "filter_metadata_error_count",
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
        data = request.get_json(force=True) or {}
        job_id, job = folder_job_from_request(data)
        out = _unique_download_path(f"xlent-folder-audit-{job_id[:8]}", ".html")
        out.write_text(
            _folder_audit_html(job_id, job, normalize_ui_language(data.get("lang"))),
            encoding="utf-8",
        )
        if data.get("open") is True:
            _open_path(out)
        return jsonify({"ok": True, "path": str(out)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/folder-audit/pdf")
def folder_audit_pdf_endpoint():
    try:
        data = request.get_json(force=True) or {}
        job_id, job = folder_job_from_request(data)
        language = normalize_ui_language(data.get("lang"))
        lines = [
            "XLENT mappeskann-rapport",
            f"Jobb: {job_id}",
            f"Mappe: {job.get('folder', '')}",
            f"Status: {job.get('status', '')}",
            f"Sist endret før: {job.get('modified_before') or 'Alle filer'}",
            f"Utelatt på grunn av dato: {job.get('age_excluded_count', 0)}",
            f"Utelatt på grunn av metadatafeil: {job.get('metadata_error_count', 0)}",
            f"Filer: {job.get('completed', 0)} / {job.get('total', 0)}",
            "",
        ]
        line_colors: dict[str, tuple[float, float, float]] = {}
        for row in _folder_export_rows(job, language):
            lines.append(f"{row['risk_level'].upper()} | {row['relative_path']} | {row['finding_count']} funn")
            classification = {
                "status": row["purview_status"],
                "display_name": row["purview_classification"],
            }
            purview_line = (
                f"  {purview_translation('folder_title', language)}: "
                f"{classification_display_text(classification, language)}"
            )
            lines.append(purview_line)
            line_colors[purview_line] = classification_pdf_color(classification)
            lines.append(
                f"  Lokal tilgang: {row['access_status']} | SharePoint: {row['sharepoint_access_status']}"
            )
            if row["top_findings"]:
                lines.append(f"  Toppfunn: {row['top_findings']}")
            if row["error"]:
                lines.append(f"  Feil: {row['error']}")
            lines.append("")
        out = _unique_download_path(f"xlent-folder-audit-{job_id[:8]}", ".pdf")
        write_text_pdf(
            "\n".join(lines),
            out,
            title="XLENT mappeskann-rapport",
            line_colors=line_colors,
        )
        if data.get("open") is True:
            _open_path(out)
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
                out = _unique_redacted_sibling(source)
                _atomic_patch_file(
                    source,
                    replacements,
                    out,
                    strip_annotations=strip_annotations,
                )
                audit = record_redaction(
                    out,
                    result,
                    findings,
                    method="folder_scan",
                    store_finding_details=False,
                )
                app_state.last_anonymized_path = out
                outputs.append({
                    "file": result.relative_path or result.file_name,
                    "path": str(out),
                    "history_id": audit["id"],
                    "verification": audit["verification"],
                })
            except PermissionError:
                errors.append({
                    "file": result.relative_path or result.file_name,
                    "error": "Ingen skrivetilgang til mappen. Kontroller fil- og mapperettigheter.",
                })
            except Exception as exc:
                errors.append({"file": report_id, "error": str(exc)})
        output_folder = str(Path(outputs[0]["path"]).parent) if len(outputs) == 1 else ""
        return jsonify({"ok": bool(outputs), "folder": output_folder, "outputs": outputs, "errors": errors})
    except Exception as exc:
        LOGGER.error("folder-redact failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.post("/folder-delete")
def folder_delete_endpoint():
    """Permanently delete explicitly confirmed files from the active folder scan."""
    try:
        data = request.get_json(force=True) or {}
        if data.get("confirmed") is not True:
            return jsonify({"ok": False, "error": "Sletting må bekreftes."})

        job_id, job = folder_job_from_request(data)
        if job.get("status") == "running":
            return jsonify({"ok": False, "error": "Vent til mappeskanningen er ferdig eller avbrutt før filer slettes."})
        report_ids = [str(value) for value in data.get("report_ids") or [] if str(value)]
        if not report_ids:
            return jsonify({"ok": False, "error": "Ingen filer valgt."})

        active_ids = {
            str(row.get("report_id") or "")
            for row in job.get("files", [])
            if row.get("report_id")
        }
        unknown_ids = [report_id for report_id in report_ids if report_id not in active_ids]
        if unknown_ids:
            return jsonify({"ok": False, "error": "En eller flere filer tilhører ikke den aktive mappeskanningen."})

        deleted = []
        errors = []
        for report_id in dict.fromkeys(report_ids):
            try:
                result = folder_result_for_report_id(report_id)
                path = Path(result.source_path)
                if not path.exists():
                    errors.append({"file": result.relative_path or result.file_name, "error": "Filen finnes ikke lenger."})
                    continue
                if not path.is_file():
                    errors.append({"file": result.relative_path or result.file_name, "error": "Målet er ikke en vanlig fil."})
                    continue
                path.unlink()
                deleted.append({"report_id": report_id, "file": result.relative_path or result.file_name})
                add_history_entry(
                    file_name=result.file_name,
                    risk_level=result.risk_level,
                    finding_count=len(result.findings),
                    file_size=result.file_size,
                    source="deleted",
                )
                with app_state.folder_scan_lock:
                    app_state.folder_scan_results.pop(report_id, None)
            except Exception as exc:
                errors.append({"file": report_id, "error": str(exc)})

        deleted_ids = {entry["report_id"] for entry in deleted}
        if deleted_ids:
            with app_state.folder_job_manager.mutate(job_id) as active_job:
                if active_job is not None:
                    active_job["files"] = [
                        row for row in active_job.get("files", [])
                        if str(row.get("report_id") or "") not in deleted_ids
                    ]
        return jsonify({"ok": bool(deleted), "deleted": deleted, "errors": errors})
    except Exception as exc:
        LOGGER.error("folder-delete failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@folders_bp.get("/folder-report/<report_id>")
def folder_report(report_id: str):
    with app_state.folder_scan_lock:
        result = app_state.folder_scan_results.get(report_id)
    if result is None:
        return "Ingen rapport tilgjengelig for denne filen.", 404
    language = normalize_ui_language(request.args.get("lang"))
    report_html = generate_html(
        result,
        api_base=f"http://127.0.0.1:{app_state.port}",
        ai_findings=[],
        language=language,
    )
    return report_html, 200, {"Content-Type": "text/html; charset=utf-8"}
