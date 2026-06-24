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
from xlent_scanner.scanner import scan_file, scan_text

LOGGER = logging.getLogger("xlent_scanner")
scanning_bp = Blueprint("scanning", __name__)


def _error_payload(message: str) -> dict:
    return {
        "file_name": "",
        "file_size": 0,
        "text_length": 0,
        "text_preview": "",
        "findings": [],
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


def _remember_result(result, path: Path | None) -> None:
    app_state.last_result = result
    app_state.last_path = path
    app_state.clear_ai_findings()
    add_history_entry(
        file_name=result.file_name,
        risk_level=result.risk_level,
        finding_count=len(result.findings),
        file_size=result.file_size,
        source="file" if path is not None else "text",
    )


@scanning_bp.post("/scan")
def scan():
    try:
        data = request.get_json(force=True)
        file_path = data.get("file_path", "")
        ignore_xlent = bool(data.get("ignore_xlent", False))
        language = data.get("language", "auto")
        ocr = bool(data.get("ocr", False))
        LOGGER.info(
            "scan request path=%s lang=%s ignore_xlent=%s ocr=%s",
            file_path,
            language,
            ignore_xlent,
            ocr,
        )
        result = scan_file(
            file_path,
            ignore_xlent=ignore_xlent,
            language=language,
            ocr=ocr,
        )
        _remember_result(result, Path(file_path) if file_path else None)
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
        original_name = uploaded.filename or "ukjent"
        suffix = Path(original_name).suffix.lower()
        LOGGER.info(
            "scan-upload request name=%s suffix=%s lang=%s ignore_xlent=%s ocr=%s",
            original_name,
            suffix,
            language,
            ignore_xlent,
            ocr,
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
        result = scan_file(
            tmp_path,
            ignore_xlent=ignore_xlent,
            language=language,
            ocr=ocr,
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
        LOGGER.info("scan-text request len=%d lang=%s", len(text), language)
        result = scan_text(text, language=language)
        _remember_result(result, None)
        LOGGER.info("scan-text result findings=%d", len(result.findings))
        return jsonify(asdict(result))
    except Exception as exc:
        LOGGER.error("scan-text endpoint failed: %s", traceback.format_exc())
        return jsonify({
            "error": f"Klarte ikke å skanne tekst: {exc}",
            "scan_status": "failed",
        })
