"""Lokale ruter for det personvernminimerte revisjonssporet."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from xlent_scanner.audit_trail import AuditTrail

audit_bp = Blueprint("audit", __name__)


def _downloads_dir() -> Path:
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


@audit_bp.get("/audit/events")
def audit_events():
    limit = request.args.get("limit", 200, type=int) or 200
    event_type = str(request.args.get("event_type") or "")
    event_scope = str(request.args.get("event_scope") or "")
    days = str(request.args.get("days") or "")
    scan_mode = str(request.args.get("scan_mode") or "")
    risk_level = str(request.args.get("risk_level") or "")
    outcome = str(request.args.get("outcome") or "")
    path_mode = str(request.args.get("path_mode") or "name")
    if path_mode not in {"none", "name", "full"}:
        return jsonify({"ok": False, "error": "Ugyldig path_mode."}), 400
    if event_scope not in {"", "scans"}:
        return jsonify({"ok": False, "error": "Ugyldig event_scope."}), 400
    if days not in {"", "7", "30", "90", "all"}:
        return jsonify({"ok": False, "error": "Ugyldig days."}), 400
    if scan_mode not in {"", "standard", "ai_deep"}:
        return jsonify({"ok": False, "error": "Ugyldig scan_mode."}), 400
    if risk_level not in {"", "grønn", "gul", "rød", "svart"}:
        return jsonify({"ok": False, "error": "Ugyldig risk_level."}), 400
    if outcome not in {"", "success", "partial", "failed"}:
        return jsonify({"ok": False, "error": "Ugyldig outcome."}), 400
    since = None
    if days and days != "all":
        since = datetime.now(timezone.utc) - timedelta(days=int(days))
    trail = AuditTrail()
    entries = trail.query_events(
        limit=limit,
        event_type=event_type,
        event_types=("scan_completed", "ai_scan_completed")
        if event_scope == "scans" else (),
        since=since,
        scan_mode=scan_mode,
        risk_level=risk_level,
        outcome=outcome,
        path_mode=path_mode,
    )
    return jsonify({
        "ok": True,
        "entries": list(reversed(entries)),
        "integrity": trail.verify_integrity(),
    })


@audit_bp.get("/audit/verify")
def audit_verify():
    return jsonify({"ok": True, "integrity": AuditTrail().verify_integrity()})


@audit_bp.post("/audit/export")
def audit_export():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = _downloads_dir() / f"xlent-audit-{stamp}.zip"
    suffix = 1
    while output.exists():
        output = _downloads_dir() / f"xlent-audit-{stamp}-{suffix}.zip"
        suffix += 1
    AuditTrail().export_bundle(output)
    return jsonify({"ok": True, "path": str(output)})
