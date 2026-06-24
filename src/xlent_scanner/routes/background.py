"""Ruter for lokale bakgrunnstjenester og språkmodelladministrasjon."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from xlent_scanner.clipboard_guard import guard
from xlent_scanner.folder_watch import watcher
from xlent_scanner.model_manager import (
    _MODEL_VERSIONS,
    download_model_async,
    models_status,
)

LOGGER = logging.getLogger("xlent_scanner")
background_bp = Blueprint("background", __name__)


@background_bp.get("/clipboard-guard/status")
def clipboard_guard_status():
    return jsonify({"ok": True, **guard.status()})


@background_bp.post("/clipboard-guard/start")
def clipboard_guard_start():
    started = guard.start()
    LOGGER.info("clipboard-guard start (started=%s)", started)
    return jsonify({"ok": True, "started": started, **guard.status()})


@background_bp.post("/clipboard-guard/stop")
def clipboard_guard_stop():
    stopped = guard.stop()
    LOGGER.info("clipboard-guard stop (stopped=%s)", stopped)
    return jsonify({"ok": True, "stopped": stopped})


@background_bp.get("/folder-watch/status")
def folder_watch_status():
    return jsonify({"ok": True, **watcher.status()})


@background_bp.post("/folder-watch/start")
def folder_watch_start():
    data = request.get_json(force=True)
    folder = str(data.get("folder") or "").strip()
    if not folder:
        return jsonify({"ok": False, "error": "Ingen mappe oppgitt."})
    result = watcher.start(
        folder,
        ignore_xlent=bool(data.get("ignore_xlent", False)),
        language=str(data.get("language") or "auto"),
    )
    LOGGER.info("folder-watch start folder=%s ok=%s", folder, result.get("ok"))
    if not result.get("ok"):
        return jsonify(result)
    return jsonify({**result, **watcher.status()})


@background_bp.post("/folder-watch/stop")
def folder_watch_stop():
    data = request.get_json(silent=True) or {}
    folder = str(data.get("folder") or "").strip() or None
    stopped = watcher.stop(folder)
    LOGGER.info("folder-watch stop (stopped=%s)", stopped)
    return jsonify({"ok": True, "stopped": stopped})


@background_bp.get("/models/status")
def models_status_endpoint():
    return jsonify(models_status())


@background_bp.post("/models/download")
def models_download_endpoint():
    data = request.get_json(force=True)
    model = (data.get("model") or "").strip()
    if not model or model not in _MODEL_VERSIONS:
        return jsonify({"ok": False, "error": f"Ukjent modell: {model!r}"})
    started = download_model_async(model)
    LOGGER.info("models/download model=%s started=%s", model, started)
    return jsonify({"ok": True, "model": model, "started": started})
