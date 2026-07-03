"""Ruter for enkeltfil-, upload- og tekstskanning."""
from __future__ import annotations

import logging
import os
import tempfile
import traceback
from dataclasses import asdict
from pathlib import Path

from flask import Blueprint, jsonify, request

from xlent_scanner.app_state import app_state
from xlent_scanner.history import add_history_entry
from xlent_scanner.routes.folders import folder_result_row
from xlent_scanner.scan_categories import categories_payload
from xlent_scanner.scanner import build_folder_scan_plan, scan_file, scan_text
from xlent_scanner.zip_processing import (
    ZIP_LARGE_FILE_COUNT,
    ZIP_LARGE_TOTAL_BYTES,
    ZIP_SUFFIXES,
    extract_zip_to_temp,
)

LOGGER = logging.getLogger("xlent_scanner")
scanning_bp = Blueprint("scanning", __name__)


@scanning_bp.get("/scan-categories")
def scan_categories():
    return jsonify(categories_payload())


def _error_payload(message: str) -> dict:
    return {
        "file_name": "",
        "file_size": 0,
        "text_length": 0,
        "text_preview": "",
        "findings": [],
        "suppressed_findings": [],
        "risk_level": "grønn",
        "risk_summary": "",
        "recommended_action": "",
        "language": "auto",
        "warning": None,
        "warning_code": None,
        "original_text": "",
        "error": message,
        "scan_status": "failed",
    }


def _request_categories(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return None


def _remember_result(result, path: Path | None) -> None:
    app_state.last_result = result
    app_state.last_path = path
    app_state.clear_ai_findings()
    app_state.clear_anonymized_file()
    add_history_entry(
        file_name=result.file_name,
        risk_level=result.risk_level,
        finding_count=len(result.findings),
        file_size=result.file_size,
        source="file" if path is not None else "text",
    )


def _scan_file_compat(*args, scan_profile: str = "normal", **kwargs):
    try:
        return scan_file(*args, scan_profile=scan_profile, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        legacy_kwargs = dict(kwargs)
        legacy_kwargs.pop("categories", None)
        try:
            return scan_file(*args, scan_profile=scan_profile, **legacy_kwargs)
        except TypeError as exc2:
            if "unexpected keyword argument" not in str(exc2):
                raise
            return scan_file(*args, **legacy_kwargs)


def _scan_text_compat(*args, scan_profile: str = "normal", **kwargs):
    try:
        return scan_text(*args, scan_profile=scan_profile, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        legacy_kwargs = dict(kwargs)
        legacy_kwargs.pop("categories", None)
        try:
            return scan_text(*args, scan_profile=scan_profile, **legacy_kwargs)
        except TypeError as exc2:
            if "unexpected keyword argument" not in str(exc2):
                raise
            return scan_text(*args, **legacy_kwargs)


def _scan_zip_upload(
    zip_path: Path,
    original_name: str,
    *,
    ignore_xlent: bool,
    language: str,
    ocr: bool,
    scan_profile: str,
    pdf_mode: str,
    categories: list[str] | None,
) -> dict:
    extracted = extract_zip_to_temp(zip_path)
    plan = build_folder_scan_plan(extracted.root, recursive=True)
    job_id = app_state.folder_job_manager.create({
        "status": "running",
        "folder": f"{original_name} (ZIP)",
        "source": "zip",
        "zip_name": original_name,
        "zip_path": str(zip_path),
        "extracted_folder": str(extracted.root),
        "recursive": True,
        "total": plan["file_count"],
        "completed": 0,
        "folder_count": plan["folder_count"],
        "truncated": plan["truncated"],
        "max_files": plan["max_files"],
        "max_depth": plan["max_depth"],
        "cancel_requested": False,
        "error": "",
        "files": [],
    })
    root = extracted.root
    level_order = {"grønn": 0, "gul": 1, "rød": 2, "svart": 3}
    aggregate_level = "grønn"
    for file_path in plan["files"]:
        result = _scan_file_compat(
            file_path,
            ignore_xlent=ignore_xlent,
            language=language,
            ocr=ocr,
            scan_profile=scan_profile,
            categories=categories,
            pdf_mode=pdf_mode,
        )
        result.relative_path = str(Path(file_path).relative_to(root))
        result.source_path = str(file_path)
        if level_order.get(result.risk_level, 0) > level_order.get(aggregate_level, 0):
            aggregate_level = result.risk_level
        row = folder_result_row(result)
        add_history_entry(
            file_name=f"{original_name}/{result.relative_path or result.file_name}",
            risk_level=result.risk_level,
            finding_count=len(result.findings),
            file_size=result.file_size,
            source="batch",
        )
        with app_state.folder_job_manager.mutate(job_id) as job:
            if job is None:
                break
            job["files"].append(row)
            job["completed"] = len(job["files"])
    app_state.folder_job_manager.update(job_id, status="completed")
    zip_warning = ""
    if (
        extracted.total_files >= ZIP_LARGE_FILE_COUNT
        or extracted.total_uncompressed_bytes >= ZIP_LARGE_TOTAL_BYTES
    ):
        zip_warning = (
            "ZIP-arkivet er stort. Skanning kan ta tid, og store arkiver bør "
            "kontrolleres før anonymisering."
        )
    return {
        "ok": True,
        "zip_scan": True,
        "job_id": job_id,
        "file_name": original_name,
        "folder": f"{original_name} (ZIP)",
        "total_files": extracted.total_files,
        "supported_files": extracted.supported_files,
        "ignored_files": extracted.ignored_files,
        "total_uncompressed_bytes": extracted.total_uncompressed_bytes,
        "skipped": extracted.skipped[:100],
        "warning": zip_warning,
        "files": app_state.folder_job_manager.snapshot(job_id).get("files", []),
        "total": plan["file_count"],
        "folder_count": plan["folder_count"],
        "truncated": plan["truncated"],
        "max_files": plan["max_files"],
        "max_depth": plan["max_depth"],
        "risk_level": aggregate_level,
        "risk_summary": f"ZIP-skann: {plan['file_count']} støttede filer, {extracted.ignored_files} ignorert.",
        "scan_status": "success",
    }


@scanning_bp.post("/scan")
def scan():
    try:
        data = request.get_json(force=True)
        file_path = data.get("file_path", "")
        ignore_xlent = bool(data.get("ignore_xlent", False))
        language = data.get("language", "auto")
        ocr = bool(data.get("ocr", False))
        scan_profile = data.get("scan_profile", "normal")
        pdf_mode = data.get("scan_mode", data.get("pdf_mode", "auto"))
        categories = _request_categories(data.get("categories"))
        LOGGER.info(
            "scan request path=%s lang=%s profile=%s pdf_mode=%s ignore_xlent=%s ocr=%s categories=%s",
            file_path,
            language,
            scan_profile,
            pdf_mode,
            ignore_xlent,
            ocr,
            categories,
        )
        path_obj = Path(file_path) if file_path else None
        if path_obj is not None and path_obj.suffix.lower() in ZIP_SUFFIXES:
            payload = _scan_zip_upload(
                path_obj,
                path_obj.name,
                ignore_xlent=ignore_xlent,
                language=language,
                ocr=ocr,
                scan_profile=scan_profile,
                categories=categories,
                pdf_mode=pdf_mode,
            )
            return jsonify(payload)
        result = _scan_file_compat(
            file_path,
            ignore_xlent=ignore_xlent,
            language=language,
            ocr=ocr,
            scan_profile=scan_profile,
            categories=categories,
            pdf_mode=pdf_mode,
        )
        _remember_result(result, path_obj)
        LOGGER.info(
            "scan result path=%s error=%s findings=%s",
            file_path,
            bool(result.error),
            len(result.findings),
        )
        return jsonify(asdict(result))
    except Exception as exc:
        LOGGER.error("scan endpoint failed: %s", traceback.format_exc())
        return jsonify(_error_payload(f"Klarte ikke å lese fil: {exc}"))


@scanning_bp.post("/scan-upload")
def scan_upload():
    tmp_path: Path | None = None
    try:
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "Ingen fil mottatt.", "scan_status": "failed"})
        ignore_xlent = request.form.get("ignore_xlent", "false").lower() == "true"
        language = request.form.get("language", "auto")
        ocr = request.form.get("ocr", "false").lower() == "true"
        scan_profile = request.form.get("scan_profile", "normal")
        pdf_mode = request.form.get("scan_mode") or request.form.get("pdf_mode", "auto")
        categories = _request_categories(request.form.get("categories"))
        original_name = uploaded.filename or "ukjent"
        suffix = Path(original_name).suffix.lower()
        LOGGER.info(
            "scan-upload request name=%s suffix=%s lang=%s profile=%s pdf_mode=%s ignore_xlent=%s ocr=%s categories=%s",
            original_name,
            suffix,
            language,
            scan_profile,
            pdf_mode,
            ignore_xlent,
            ocr,
            categories,
        )

        if app_state.last_tmp_path and app_state.last_tmp_path.exists():
            try:
                app_state.last_tmp_path.unlink()
            except OSError:
                pass
        app_state.last_tmp_path = None

        fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="xlent-drop-")
        tmp_path = Path(tmp)
        os.close(fd)
        uploaded.save(str(tmp_path))
        if suffix in ZIP_SUFFIXES:
            payload = _scan_zip_upload(
                tmp_path,
                original_name,
                ignore_xlent=ignore_xlent,
                language=language,
                ocr=ocr,
                scan_profile=scan_profile,
                categories=categories,
                pdf_mode=pdf_mode,
            )
            app_state.last_tmp_path = tmp_path
            app_state.last_result = None
            app_state.last_path = None
            app_state.clear_ai_findings()
            app_state.clear_anonymized_file()
            LOGGER.info(
                "scan-upload ZIP result name=%s supported=%s ignored=%s job=%s",
                original_name,
                payload["supported_files"],
                payload["ignored_files"],
                payload["job_id"],
            )
            return jsonify(payload)
        result = _scan_file_compat(
            tmp_path,
            ignore_xlent=ignore_xlent,
            language=language,
            ocr=ocr,
            scan_profile=scan_profile,
            categories=categories,
            pdf_mode=pdf_mode,
        )
        result.file_name = original_name
        app_state.last_tmp_path = tmp_path
        _remember_result(result, tmp_path)
        LOGGER.info(
            "scan-upload result name=%s error=%s findings=%s",
            original_name,
            bool(result.error),
            len(result.findings),
        )
        return jsonify(asdict(result))
    except Exception as exc:
        LOGGER.error("scan-upload endpoint failed: %s", traceback.format_exc())
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return jsonify(_error_payload(f"Klarte ikke å lese fil: {exc}"))


@scanning_bp.post("/scan-text")
def scan_text_endpoint():
    try:
        data = request.get_json(force=True)
        text = data.get("text", "")
        language = data.get("language", "auto")
        scan_profile = data.get("scan_profile", "normal")
        categories = _request_categories(data.get("categories"))
        LOGGER.info(
            "scan-text request len=%d lang=%s profile=%s categories=%s",
            len(text),
            language,
            scan_profile,
            categories,
        )
        result = _scan_text_compat(
            text,
            language=language,
            scan_profile=scan_profile,
            categories=categories,
        )
        _remember_result(result, None)
        LOGGER.info("scan-text result findings=%d", len(result.findings))
        return jsonify(asdict(result))
    except Exception as exc:
        LOGGER.error("scan-text endpoint failed: %s", traceback.format_exc())
        return jsonify({
            "error": f"Klarte ikke å skanne tekst: {exc}",
            "scan_status": "failed",
        })
