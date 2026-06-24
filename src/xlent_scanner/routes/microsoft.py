"""Microsoft Graph-ruter for dokumentmerking og SharePoint-metadata."""
from __future__ import annotations

import logging
import os
import secrets
import traceback
from collections.abc import Callable

from flask import Blueprint, jsonify, request

from xlent_scanner.app_state import app_state
from xlent_scanner.microsoft_graph import (
    GraphConfigError,
    GraphRequestError,
    assign_sensitivity_label,
    graph_status,
    policy_warning_for_tags,
    read_document_tags,
    read_document_tags_for_local_path,
    resolve_local_drive_item,
    scan_metadata_fields,
    set_retention_label,
    suggested_label_for_risk,
    update_sharepoint_fields,
)
from xlent_scanner.models import ScanResult

LOGGER = logging.getLogger("xlent_scanner")


def _error_response(exc: Exception, status: int = 400):
    code = "graph_error"
    if isinstance(exc, GraphConfigError):
        code = "graph_not_configured"
    elif isinstance(exc, GraphRequestError):
        status = 502
    return jsonify({"ok": False, "error": str(exc), "error_code": code}), status


def _access_error():
    expected = os.environ.get("XLENT_SCANNER_API_KEY", "").strip()
    if expected:
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

    remote = (request.remote_addr or "").strip().lower()
    host = (request.host or "").split(":", 1)[0].strip().lower()
    local_hosts = {"127.0.0.1", "::1", "localhost"}
    if remote not in local_hosts and host not in local_hosts:
        return jsonify({
            "ok": False,
            "error": "Microsoft 365-endepunkter krever XLENT_SCANNER_API_KEY ved nettverkstilgang.",
            "error_code": "api_key_required",
        }), 403
    return None


def _attach_tags(tags: dict) -> None:
    if app_state.last_result is None:
        return
    app_state.last_result.microsoft_tags = tags
    warning = policy_warning_for_tags(tags)
    app_state.last_result.policy_warning = warning or None
    app_state.last_result.policy_warning_level = "rød" if warning else None


def _scan_metadata(
    result: ScanResult,
    suggested_label: str | None = None,
    status: str = "Scanned",
) -> tuple[dict, dict]:
    suggestion = suggested_label_for_risk(result.risk_level)
    fields = scan_metadata_fields(
        result.risk_level,
        len([finding for finding in result.findings if not finding.category.startswith("⚠")]),
        suggested_label or suggestion["name"],
        status,
    )
    return fields, suggestion


def create_microsoft_blueprint(
    *,
    folder_job_from_request: Callable[[dict | None], tuple[str, dict]],
    folder_result_for_report_id: Callable[[str], ScanResult],
) -> Blueprint:
    bp = Blueprint("microsoft", __name__)

    @bp.get("/microsoft/graph/status")
    def microsoft_graph_status_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        return jsonify({"ok": True, **graph_status()})

    @bp.post("/microsoft/graph/tags")
    def microsoft_graph_tags_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        try:
            data = request.get_json(force=True) or {}
            tags = read_document_tags(
                str(data.get("drive_id") or "").strip(),
                str(data.get("item_id") or "").strip(),
            )
            _attach_tags(tags)
            suggestion = suggested_label_for_risk(
                app_state.last_result.risk_level if app_state.last_result else "grønn"
            )
            return jsonify({
                "ok": True,
                "tags": tags,
                "policy_warning": tags.get("policy_warning") or "",
                "suggested_label": suggestion,
            })
        except (GraphConfigError, GraphRequestError, ValueError) as exc:
            return _error_response(exc)
        except Exception as exc:
            LOGGER.error("microsoft/graph/tags failed: %s", traceback.format_exc())
            return _error_response(exc, 500)

    @bp.post("/microsoft/graph/resolve-local-file")
    def microsoft_graph_resolve_local_file_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        try:
            data = request.get_json(force=True) or {}
            local_path = str(data.get("local_path") or "").strip()
            if not local_path and app_state.last_path is not None:
                local_path = str(app_state.last_path)
            if not local_path:
                return jsonify({
                    "ok": False,
                    "error": "Ingen lokal filsti oppgitt.",
                    "error_code": "missing_local_path",
                }), 400
            resolved = resolve_local_drive_item(
                local_path,
                drive_id=str(data.get("drive_id") or "").strip() or None,
                sync_root=str(data.get("sync_root") or "").strip() or None,
            )
            return jsonify({"ok": True, "resolved": resolved})
        except (GraphConfigError, GraphRequestError, ValueError) as exc:
            return _error_response(exc)
        except Exception as exc:
            LOGGER.error("microsoft/graph/resolve-local-file failed: %s", traceback.format_exc())
            return _error_response(exc, 500)

    @bp.post("/microsoft/graph/tags-for-local-file")
    def microsoft_graph_tags_for_local_file_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        try:
            data = request.get_json(force=True) or {}
            local_path = str(data.get("local_path") or "").strip()
            if not local_path and app_state.last_path is not None:
                local_path = str(app_state.last_path)
            if not local_path:
                return jsonify({
                    "ok": False,
                    "error": "Ingen lokal filsti oppgitt.",
                    "error_code": "missing_local_path",
                }), 400
            tags = read_document_tags_for_local_path(
                local_path,
                drive_id=str(data.get("drive_id") or "").strip() or None,
                sync_root=str(data.get("sync_root") or "").strip() or None,
            )
            _attach_tags(tags)
            suggestion = suggested_label_for_risk(
                app_state.last_result.risk_level if app_state.last_result else "grønn"
            )
            return jsonify({
                "ok": True,
                "tags": tags,
                "resolved": tags.get("resolved", {}),
                "policy_warning": tags.get("policy_warning") or "",
                "suggested_label": suggestion,
            })
        except (GraphConfigError, GraphRequestError, ValueError) as exc:
            return _error_response(exc)
        except Exception as exc:
            LOGGER.error("microsoft/graph/tags-for-local-file failed: %s", traceback.format_exc())
            return _error_response(exc, 500)

    @bp.post("/microsoft/graph/assign-sensitivity")
    def microsoft_graph_assign_sensitivity_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        try:
            data = request.get_json(force=True) or {}
            result = assign_sensitivity_label(
                str(data.get("drive_id") or "").strip(),
                str(data.get("item_id") or "").strip(),
                str(data.get("sensitivity_label_id") or "").strip(),
                str(data.get("assignment_method") or "standard").strip(),
                str(data.get("justification_text") or "Set by XLENT Scanner").strip(),
            )
            return jsonify({"ok": True, "result": result})
        except (GraphConfigError, GraphRequestError, ValueError) as exc:
            return _error_response(exc)
        except Exception as exc:
            LOGGER.error("microsoft/graph/assign-sensitivity failed: %s", traceback.format_exc())
            return _error_response(exc, 500)

    @bp.post("/microsoft/graph/set-retention")
    def microsoft_graph_set_retention_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        try:
            data = request.get_json(force=True) or {}
            result = set_retention_label(
                str(data.get("drive_id") or "").strip(),
                str(data.get("item_id") or "").strip(),
                str(data.get("retention_label_name") or "").strip(),
            )
            return jsonify({"ok": True, "result": result})
        except (GraphConfigError, GraphRequestError, ValueError) as exc:
            return _error_response(exc)
        except Exception as exc:
            LOGGER.error("microsoft/graph/set-retention failed: %s", traceback.format_exc())
            return _error_response(exc, 500)

    @bp.post("/microsoft/graph/write-scan-metadata")
    def microsoft_graph_write_scan_metadata_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        try:
            if app_state.last_result is None:
                return jsonify({
                    "ok": False,
                    "error": "Ingen scan tilgjengelig.",
                    "error_code": "missing_scan",
                }), 400
            data = request.get_json(force=True) or {}
            fields, _suggestion = _scan_metadata(
                app_state.last_result,
                suggested_label=str(data.get("suggested_label") or "").strip() or None,
                status=str(data.get("status") or "Scanned"),
            )
            extra_fields = data.get("fields")
            if isinstance(extra_fields, dict):
                fields.update(extra_fields)
            result = update_sharepoint_fields(
                str(data.get("drive_id") or "").strip(),
                str(data.get("item_id") or "").strip(),
                fields,
            )
            return jsonify({"ok": True, "fields": fields, "result": result})
        except (GraphConfigError, GraphRequestError, ValueError) as exc:
            return _error_response(exc)
        except Exception as exc:
            LOGGER.error("microsoft/graph/write-scan-metadata failed: %s", traceback.format_exc())
            return _error_response(exc, 500)

    @bp.post("/microsoft/graph/write-folder-metadata")
    def microsoft_graph_write_folder_metadata_endpoint():
        access_error = _access_error()
        if access_error:
            return access_error
        try:
            data = request.get_json(force=True) or {}
            job_id, job = folder_job_from_request(data)
            report_ids = {str(value) for value in data.get("report_ids") or [] if str(value)}
            drive_id = str(data.get("drive_id") or "").strip() or None
            sync_root = str(data.get("sync_root") or "").strip() or None
            status_value = str(data.get("status") or "Scanned")
            extra_fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}

            written: list[dict] = []
            skipped: list[dict] = []
            errors: list[dict] = []
            for row in job.get("files", []):
                report_id = str(row.get("report_id") or "")
                if report_ids and report_id not in report_ids:
                    continue
                try:
                    result = folder_result_for_report_id(report_id)
                    if result.error:
                        skipped.append({
                            "report_id": report_id,
                            "file": result.relative_path or result.file_name,
                            "reason": result.error,
                        })
                        continue
                    source_path = str(result.source_path or "").strip()
                    if not source_path:
                        skipped.append({
                            "report_id": report_id,
                            "file": result.relative_path or result.file_name,
                            "reason": "Mangler lokal filsti.",
                        })
                        continue
                    resolved = resolve_local_drive_item(
                        source_path,
                        drive_id=drive_id,
                        sync_root=sync_root,
                    )
                    fields, suggestion = _scan_metadata(result, status=status_value)
                    fields.update(extra_fields)
                    update_result = update_sharepoint_fields(
                        resolved["drive_id"],
                        resolved["item_id"],
                        fields,
                    )
                    written.append({
                        "report_id": report_id,
                        "file": result.relative_path or result.file_name,
                        "drive_id": resolved["drive_id"],
                        "item_id": resolved["item_id"],
                        "suggested_label": suggestion["name"],
                        "fields": fields,
                        "result": update_result,
                    })
                except Exception as exc:
                    errors.append({
                        "report_id": report_id,
                        "file": row.get("relative_path") or row.get("file_name") or "",
                        "error": str(exc),
                    })

            return jsonify({
                "ok": bool(written) and not errors,
                "job_id": job_id,
                "written": written,
                "skipped": skipped,
                "errors": errors,
                "written_count": len(written),
                "error_count": len(errors),
                "skipped_count": len(skipped),
            })
        except (GraphConfigError, GraphRequestError, ValueError) as exc:
            return _error_response(exc)
        except Exception as exc:
            LOGGER.error("microsoft/graph/write-folder-metadata failed: %s", traceback.format_exc())
            return _error_response(exc, 500)

    return bp
