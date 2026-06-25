"""Ollama-status, modellhåndtering og GUI-dybdeskann."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request

from xlent_scanner.ai_findings import (
    as_model_findings,
    findings_from_payload,
    replacement_texts,
)
from xlent_scanner.app_state import app_state
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES
from xlent_scanner.redaction_audit import record_redaction

LOGGER = logging.getLogger("xlent_scanner")
_patch_file: Callable

ollama_bp = Blueprint("ollama", __name__)


def create_ollama_blueprint(*, patch_file_fn: Callable) -> Blueprint:
    global _patch_file
    _patch_file = patch_file_fn
    return ollama_bp


@ollama_bp.get("/ollama/status")
def ollama_status_endpoint():
    from xlent_scanner.deep_scanner import ollama_status
    return jsonify(ollama_status())


@ollama_bp.get("/ollama/hardware-info")
def ollama_hardware_info_endpoint():
    from xlent_scanner.deep_scanner import ollama_hardware_info
    return jsonify(ollama_hardware_info())


@ollama_bp.post("/ollama/model/stop")
def ollama_model_stop_endpoint():
    from xlent_scanner.deep_scanner import stop_ollama_model

    data = request.get_json(force=True) or {}
    model = (data.get("model") or "").strip()
    result = stop_ollama_model(model)
    LOGGER.info("ollama/model/stop model=%s ok=%s", model, result.get("ok"))
    return jsonify(result)


@ollama_bp.post("/ollama/model/pull")
def ollama_model_pull_endpoint():
    from xlent_scanner.deep_scanner import pull_ollama_model

    data = request.get_json(force=True) or {}
    model = (data.get("model") or "").strip() or None
    result = pull_ollama_model(model)
    LOGGER.info("ollama/model/pull model=%s ok=%s", model, result.get("ok"))
    return jsonify(result)


@ollama_bp.get("/ollama/model/pull/status")
def ollama_model_pull_status_endpoint():
    from xlent_scanner.deep_scanner import get_ollama_pull_status

    status = get_ollama_pull_status()
    status["ok"] = True
    return jsonify(status)


@ollama_bp.get("/ollama/last-file-info")
def ollama_last_file_info():
    if app_state.last_result is None or getattr(app_state.last_result, "error", None):
        return jsonify({"available": False})
    text = getattr(app_state.last_result, "original_text", "") or ""
    return jsonify({
        "available": bool(text.strip()),
        "file_name": app_state.last_result.file_name or "",
        "text_length": app_state.last_result.text_length or 0,
    })


@ollama_bp.post("/ollama/deep-scan")
def ollama_deep_scan_endpoint():
    from xlent_scanner.deep_scanner import start_deep_scan

    if app_state.last_result is None:
        return jsonify({"ok": False, "error": "Ingen fil er skannet ennå."})
    text = getattr(app_state.last_result, "original_text", "") or ""
    if not text.strip():
        return jsonify({"ok": False, "error": "Ingen tekst å analysere i sist skannede fil."})
    data = request.get_json(force=True)
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"ok": False, "error": "Ingen Ollama-modell oppgitt."})
    categories = data.get("categories") or None
    min_confidence = (data.get("min_confidence") or "medium").strip().lower()
    if min_confidence not in ("high", "medium", "low"):
        min_confidence = "medium"
    app_state.last_ai_scan_metadata = {
        "model": model,
        "categories": list(categories or []),
        "min_confidence": min_confidence,
        "language": getattr(app_state.last_result, "language", "en") or "en",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    job_id = start_deep_scan(
        text,
        model,
        getattr(app_state.last_result, "language", "en") or "en",
        categories=categories,
        min_confidence=min_confidence,
    )
    LOGGER.info(
        "ollama/deep-scan started job=%s model=%s cats=%s",
        job_id,
        model,
        categories,
    )
    return jsonify({"ok": True, "job_id": job_id})


@ollama_bp.post("/ollama/anonymize-findings")
def ollama_anonymize_findings():
    if app_state.last_result is None:
        return jsonify({"error": "Ingen fil skannet."})
    data = request.get_json(force=True) or {}
    texts_to_remove = [
        str(text).strip()
        for text in (data.get("texts") or [])
        if text and str(text).strip()
    ]
    ai_findings = findings_from_payload(data)
    for text in replacement_texts(ai_findings):
        if text not in texts_to_remove:
            texts_to_remove.append(text)
    strip_annotations = bool(data.get("strip_annotations", False))
    if not texts_to_remove:
        return jsonify({"error": "Ingen tekst valgt for anonymisering."})
    if not ai_findings:
        ai_findings = [
            {"text": text, "category": "🤖 AI-funn", "context": ""}
            for text in texts_to_remove
        ]

    stem = (
        Path(app_state.last_result.file_name).stem
        if app_state.last_result.file_name
        else "dokument"
    )
    suffix = app_state.last_path.suffix.lower() if app_state.last_path else ""
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"

    if (
        app_state.last_path
        and app_state.last_path.exists()
        and suffix in SUPPORTED_PATCH_SUFFIXES
    ):
        replacements = {
            text: "[ANONYMISERT]"
            for text in replacement_texts(ai_findings)
        }
        out = _unique_output(downloads, f"{stem}-ai-anonymisert", suffix)
        try:
            _patch_file(
                app_state.last_path,
                replacements,
                out,
                strip_annotations=strip_annotations,
            )
            LOGGER.info(
                "ollama/anonymize-findings patch: wrote %s (%d replacements)",
                out,
                len(texts_to_remove),
            )
            selected = as_model_findings(ai_findings)
            audit = record_redaction(
                out,
                app_state.last_result,
                selected,
                ai_findings=ai_findings,
                method=f"ai_patch_{suffix.lstrip('.')}",
                ai_metadata=app_state.last_ai_scan_metadata,
            )
            app_state.last_anonymized_path = out
            return jsonify({
                "ok": True,
                "path": str(out),
                "verification": audit["verification"],
                "history_entry": audit,
            })
        except Exception as exc:
            LOGGER.warning("patch_file feilet, faller tilbake til .txt: %s", exc)

    text = getattr(app_state.last_result, "original_text", "") or ""
    if not text.strip():
        return jsonify({"error": "Originaltekst ikke tilgjengelig. Re-skann filen."})
    result_text = text
    for text_to_remove in texts_to_remove:
        result_text = result_text.replace(text_to_remove, "[ANONYMISERT]")
    out = _unique_output(downloads, f"{stem}-ai-anonymisert", ".txt")
    out.write_text(result_text, encoding="utf-8")
    LOGGER.info(
        "ollama/anonymize-findings txt: wrote %s (%d replacements)",
        out,
        len(texts_to_remove),
    )
    selected = as_model_findings(ai_findings)
    audit = record_redaction(
        out,
        app_state.last_result,
        selected,
        ai_findings=ai_findings,
        method="ai_text",
        ai_metadata=app_state.last_ai_scan_metadata,
    )
    app_state.last_anonymized_path = out
    return jsonify({
        "ok": True,
        "path": str(out),
        "verification": audit["verification"],
        "history_entry": audit,
    })


def _unique_output(directory: Path, stem: str, suffix: str) -> Path:
    out = directory / f"{stem}{suffix}"
    counter = 1
    while out.exists():
        out = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return out


@ollama_bp.get("/ollama/deep-scan/status")
def ollama_deep_scan_status_endpoint():
    from xlent_scanner.deep_scanner import get_deep_scan_status
    return jsonify(get_deep_scan_status())


@ollama_bp.get("/ollama/deep-scan/status/<job_id>")
def ollama_deep_scan_status_for_job_endpoint(job_id: str):
    from xlent_scanner.deep_scanner import get_deep_scan_status

    status = get_deep_scan_status(job_id)
    if not status:
        return jsonify({"ok": False, "error": "Ukjent job_id."}), 404
    status["ok"] = True
    return jsonify(status)


@ollama_bp.post("/ollama/deep-scan/cancel")
def ollama_deep_scan_cancel_endpoint():
    from xlent_scanner.deep_scanner import cancel_deep_scan
    cancel_deep_scan()
    return jsonify({"ok": True})


@ollama_bp.post("/ollama/deep-scan/cancel/<job_id>")
def ollama_deep_scan_cancel_for_job_endpoint(job_id: str):
    from xlent_scanner.deep_scanner import cancel_deep_scan, get_deep_scan_status

    if not get_deep_scan_status(job_id):
        return jsonify({"ok": False, "error": "Ukjent job_id."}), 404
    cancel_deep_scan(job_id)
    return jsonify({"ok": True, "job_id": job_id})
