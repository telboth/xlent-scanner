"""Lokale ruter for det personvernminimerte revisjonssporet."""
from __future__ import annotations

from datetime import datetime
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
    path_mode = str(request.args.get("path_mode") or "name")
    if path_mode not in {"none", "name", "full"}:
        return jsonify({"ok": False, "error": "Ugyldig path_mode."}), 400
    trail = AuditTrail()
    entries = trail.query_events(
        limit=limit,
        event_type=event_type,
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
