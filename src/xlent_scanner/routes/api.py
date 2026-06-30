"""Stabilt lokalt API for eksterne frontender og Power Apps."""
from __future__ import annotations

import base64
import binascii
import logging
import os
import secrets
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request

from xlent_scanner import __version__
from xlent_scanner.app_state import app_state

LOGGER = logging.getLogger("xlent_scanner")
_API_SCAN_TTL_SECONDS = 60 * 60
_API_MAX_SCAN_RESULTS = 50
_API_ALLOWED_LANGUAGES = {"auto", "nb", "sv", "en", "de", "fr", "es"}
_API_ALLOWED_SCAN_PROFILES = {"normal", "technical", "academic"}
_LOCAL_API_HOSTS = {"127.0.0.1", "localhost", "::1"}
_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

_scan_text: Callable
_scan_file: Callable
_openapi_spec: Callable[[], dict]

api_bp = Blueprint("api", __name__)


def create_api_blueprint(
    *,
    scan_text_fn: Callable,
    scan_file_fn: Callable,
    openapi_spec_fn: Callable[[], dict],
) -> Blueprint:
    global _scan_text, _scan_file, _openapi_spec
    _scan_text = scan_text_fn
    _scan_file = scan_file_fn
    _openapi_spec = openapi_spec_fn
    return api_bp


def api_max_file_bytes() -> int:
    raw = os.environ.get("XLENT_SCANNER_API_MAX_FILE_MB", "25").strip()
    try:
        mb = max(1, int(raw))
    except ValueError:
        mb = 25
    return mb * 1024 * 1024


def api_key_configured() -> bool:
    return bool(os.environ.get("XLENT_SCANNER_API_KEY", "").strip())


def _is_local_host(host: str) -> bool:
    return host.strip().lower() in _LOCAL_API_HOSTS


def validate_api_bind(host: str) -> None:
    if _is_local_host(host) or api_key_configured():
        return
    raise RuntimeError(
        "API kan ikke bindes til nettverk uten XLENT_SCANNER_API_KEY. "
        "Sett miljøvariabelen eller bruk --host 127.0.0.1."
    )


def _api_auth_error():
    expected = os.environ.get("XLENT_SCANNER_API_KEY", "").strip()
    if not expected:
        return None

    provided = request.headers.get("X-API-Key", "").strip()
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        provided = auth[7:].strip()

    if not secrets.compare_digest(provided, expected):
        return jsonify({
            "ok": False,
            "error": "Ugyldig eller manglende API-nøkkel.",
            "error_code": "unauthorized",
        }), 401
    return None


def _api_json_body() -> dict:
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _api_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ja"}
    return default


def _api_language(value) -> str:
    lang = str(value or "auto").strip().lower()
    if lang not in _API_ALLOWED_LANGUAGES:
        raise ValueError("Ugyldig språk. Bruk auto, nb, sv, en, de, fr eller es.")
    return lang


def _api_scan_profile(value) -> str:
    profile = str(value or "normal").strip().lower()
    if profile not in _API_ALLOWED_SCAN_PROFILES:
        raise ValueError("Ugyldig scan_profile. Bruk normal eller technical.")
    return "technical" if profile == "academic" else profile


def _api_categories(value) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("categories må være en liste.")
    return [str(item) for item in value]


def _api_delete_scan_locked(scan_id: str) -> None:
    entry = app_state.api_scan_results.pop(scan_id, None)
    if not entry:
        return
    path = entry.get("path")
    if entry.get("owns_path") and isinstance(path, Path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _api_cleanup_locked(now: float) -> None:
    expired = [
        scan_id
        for scan_id, entry in app_state.api_scan_results.items()
        if now - float(entry.get("created_at", 0)) > _API_SCAN_TTL_SECONDS
    ]
    for scan_id in expired:
        _api_delete_scan_locked(scan_id)

    while len(app_state.api_scan_results) > _API_MAX_SCAN_RESULTS:
        oldest = min(
            app_state.api_scan_results,
            key=lambda scan_id: float(
                app_state.api_scan_results[scan_id].get("created_at", 0)
            ),
        )
        _api_delete_scan_locked(oldest)


def _api_store_scan_result(
    result,
    path: Path | None = None,
    owns_path: bool = False,
) -> str:
    scan_id = str(uuid.uuid4())
    now = time.time()
    with app_state.api_scan_lock:
        _api_cleanup_locked(now)
        app_state.api_scan_results[scan_id] = {
            "result": result,
            "path": path,
            "owns_path": owns_path,
            "created_at": now,
        }
    return scan_id


def _api_get_scan(scan_id: str) -> dict | None:
    with app_state.api_scan_lock:
        _api_cleanup_locked(time.time())
        return app_state.api_scan_results.get(scan_id)


def _api_result_payload(
    result,
    scan_id: str,
    include_preview: bool = False,
    include_suppressed: bool = False,
) -> dict:
    payload = {
        "ok": result.scan_status != "failed",
        "scan_id": scan_id,
        "file_name": result.file_name,
        "file_size": result.file_size,
        "text_length": result.text_length,
        "risk_level": result.risk_level,
        "scan_status": result.scan_status,
        "risk_summary": result.risk_summary,
        "recommended_action": result.recommended_action,
        "language": result.language,
        "warning": result.warning,
        "warning_code": getattr(result, "warning_code", None),
        "microsoft_tags": getattr(result, "microsoft_tags", {}) or {},
        "policy_warning": getattr(result, "policy_warning", None),
        "policy_warning_level": getattr(result, "policy_warning_level", None),
        "error": result.error,
        "findings": [
            {
                "category": finding.category,
                "text": finding.text,
                "context": finding.context,
                "severity": finding.severity,
            }
            for finding in result.findings
        ],
    }
    if include_preview:
        payload["text_preview"] = result.text_preview
    if include_suppressed:
        payload["suppressed_findings"] = [
            {
                "category": finding.category,
                "text": finding.text,
                "context": finding.context,
                "reason": finding.reason,
                "source": finding.source,
            }
            for finding in getattr(result, "suppressed_findings", []) or []
        ]
    return payload


@api_bp.get("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "service": "xlent-scanner",
        "version": __version__,
        "api_key_configured": api_key_configured(),
        "max_file_mb": api_max_file_bytes() // (1024 * 1024),
    })


@api_bp.get("/api/version")
def api_version():
    return jsonify({"ok": True, "version": __version__})


@api_bp.get("/api/openapi.json")
def api_openapi_json():
    return jsonify(_openapi_spec())


@api_bp.get("/api/docs")
def api_docs():
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>XLENT Scanner API Docs</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>body{margin:0;background:#fafafa}.topbar{display:none}</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => SwaggerUIBundle({
      url: "/api/openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      persistAuthorization: true
    });
  </script>
</body>
</html>""", 200, {"Content-Type": "text/html; charset=utf-8", **_NO_CACHE}


@api_bp.post("/api/scan-text")
def api_scan_text():
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error
    try:
        data = _api_json_body()
        text = str(data.get("text") or "")
        if not text.strip():
            return jsonify({"ok": False, "error": "Mangler tekst.", "error_code": "missing_text"}), 400
        result = _scan_text(
            text,
            language=_api_language(data.get("language")),
            source_name="Power Apps tekst",
            scan_profile=_api_scan_profile(data.get("scan_profile")),
            categories=_api_categories(data.get("categories")),
        )
        scan_id = _api_store_scan_result(result)
        return jsonify(_api_result_payload(
            result,
            scan_id,
            include_preview=_api_bool(data.get("include_preview"), False),
            include_suppressed=_api_bool(data.get("include_suppressed"), False),
        ))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "error_code": "bad_request"}), 400
    except Exception as exc:
        LOGGER.error("api/scan-text failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc), "error_code": "scan_failed"}), 500


@api_bp.post("/api/scan-file")
def api_scan_file():
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error

    tmp_path: Path | None = None
    try:
        data = _api_json_body()
        file_name = Path(str(data.get("file_name") or "document.txt")).name
        content_base64 = str(data.get("content_base64") or "")
        if not content_base64:
            return jsonify({
                "ok": False,
                "error": "Mangler content_base64.",
                "error_code": "missing_file_content",
            }), 400
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except binascii.Error:
            return jsonify({
                "ok": False,
                "error": "content_base64 er ikke gyldig base64.",
                "error_code": "invalid_base64",
            }), 400

        max_bytes = api_max_file_bytes()
        if len(raw) > max_bytes:
            return jsonify({
                "ok": False,
                "error": f"Filen er for stor. Maks er {max_bytes // (1024 * 1024)} MB.",
                "error_code": "file_too_large",
            }), 413

        suffix = Path(file_name).suffix.lower() or ".txt"
        fd, tmp = tempfile.mkstemp(prefix="xlent-api-", suffix=suffix)
        tmp_path = Path(tmp)
        with os.fdopen(fd, "wb") as file_handle:
            file_handle.write(raw)

        result = _scan_file(
            tmp_path,
            ignore_xlent=_api_bool(data.get("ignore_xlent"), False),
            language=_api_language(data.get("language")),
            ocr=_api_bool(data.get("ocr"), False),
            scan_profile=_api_scan_profile(data.get("scan_profile")),
            categories=_api_categories(data.get("categories")),
        )
        result.file_name = file_name
        scan_id = _api_store_scan_result(result, path=tmp_path, owns_path=True)
        tmp_path = None
        return jsonify(_api_result_payload(
            result,
            scan_id,
            include_preview=_api_bool(data.get("include_preview"), False),
            include_suppressed=_api_bool(data.get("include_suppressed"), False),
        ))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "error_code": "bad_request"}), 400
    except Exception as exc:
        LOGGER.error("api/scan-file failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc), "error_code": "scan_failed"}), 500
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


@api_bp.get("/api/scans/<scan_id>")
def api_get_scan_result(scan_id: str):
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error
    entry = _api_get_scan(scan_id)
    if not entry:
        return jsonify({
            "ok": False,
            "error": "Ukjent eller utløpt scan_id.",
            "error_code": "not_found",
        }), 404
    return jsonify(_api_result_payload(
        entry["result"],
        scan_id,
        include_preview=_api_bool(request.args.get("include_preview"), False),
        include_suppressed=_api_bool(request.args.get("include_suppressed"), False),
    ))


@api_bp.post("/api/deep-scan")
def api_deep_scan():
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error
    try:
        from xlent_scanner.deep_scanner import start_deep_scan

        data = _api_json_body()
        scan_id = str(data.get("scan_id") or "").strip()
        model = str(data.get("model") or "").strip()
        if not scan_id:
            return jsonify({"ok": False, "error": "Mangler scan_id.", "error_code": "missing_scan_id"}), 400
        if not model:
            return jsonify({"ok": False, "error": "Mangler Ollama-modell.", "error_code": "missing_model"}), 400
        entry = _api_get_scan(scan_id)
        if not entry:
            return jsonify({"ok": False, "error": "Ukjent eller utløpt scan_id.", "error_code": "not_found"}), 404
        result = entry["result"]
        text = getattr(result, "original_text", "") or ""
        if not text.strip():
            return jsonify({
                "ok": False,
                "error": "Ingen ekstrahert tekst tilgjengelig for scan_id.",
                "error_code": "no_text",
            }), 400

        categories = data.get("categories") or None
        if categories is not None and not isinstance(categories, list):
            return jsonify({"ok": False, "error": "categories må være en liste.", "error_code": "bad_request"}), 400
        min_confidence = str(data.get("min_confidence") or "medium").strip().lower()
        if min_confidence not in {"high", "medium", "low"}:
            min_confidence = "medium"
        job_id = start_deep_scan(
            text,
            model,
            getattr(result, "language", "en") or "en",
            categories=categories,
            min_confidence=min_confidence,
        )
        return jsonify({"ok": True, "job_id": job_id, "scan_id": scan_id})
    except Exception as exc:
        LOGGER.error("api/deep-scan failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc), "error_code": "deep_scan_failed"}), 500


@api_bp.get("/api/deep-scan/<job_id>")
def api_deep_scan_status(job_id: str):
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error
    from xlent_scanner.deep_scanner import get_deep_scan_status

    status = get_deep_scan_status(job_id)
    if not status:
        return jsonify({"ok": False, "error": "Ukjent job_id.", "error_code": "not_found"}), 404
    status["ok"] = True
    return jsonify(status)


@api_bp.post("/api/deep-scan/<job_id>/cancel")
def api_deep_scan_cancel(job_id: str):
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error
    from xlent_scanner.deep_scanner import cancel_deep_scan, get_deep_scan_status

    if not get_deep_scan_status(job_id):
        return jsonify({"ok": False, "error": "Ukjent job_id.", "error_code": "not_found"}), 404
    cancel_deep_scan(job_id)
    return jsonify({"ok": True, "job_id": job_id, "status": "cancelled"})
