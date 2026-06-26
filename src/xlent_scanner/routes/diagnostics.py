"""Ruter for dialoger, historikk, oppdatering, logger og diagnostikk."""
from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from pathlib import Path

import webview
from flask import Blueprint, jsonify, request

from xlent_scanner import __version__
from xlent_scanner.app_state import app_state
from xlent_scanner.history import clear_history, load_history
from xlent_scanner.update_check import check_for_update, fetch_platform_install_script

LOGGER = logging.getLogger("xlent_scanner")


def create_diagnostics_blueprint(
    *,
    log_path: Path,
    health_check: Callable[[], dict],
    write_debug_package: Callable[[], Path],
    download_update_script: Callable[[str, str], Path],
    launch_update_script: Callable[[Path], object],
    launch_web_mode_process: Callable[[], object],
    install_mac_quick_action: Callable[[], Path],
    open_path: Callable[[Path], None],
) -> Blueprint:
    bp = Blueprint("diagnostics", __name__)

    @bp.post("/open-dialog")
    def open_dialog():
        if app_state.window is None:
            return jsonify({"path": None})
        result = app_state.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                "Dokumenter og bilder (*.pdf;*.docx;*.pptx;*.xlsx;*.txt;*.md;*.html;*.csv;*.eml;*.rtf;*.odt;*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff;*.webp)",
                "Alle filer (*.*)",
            ),
        )
        return jsonify({"path": result[0] if result else None})

    @bp.post("/open-folder-dialog")
    def open_folder_dialog():
        if app_state.window is None:
            return jsonify({"path": None})
        result = app_state.window.create_file_dialog(
            webview.FOLDER_DIALOG,
            allow_multiple=False,
        )
        return jsonify({"path": result[0] if result else None})

    @bp.get("/history/get")
    def history_get():
        try:
            entries = load_history()
            return jsonify({"ok": True, "entries": list(reversed(entries))})
        except Exception as exc:
            return jsonify({"ok": False, "entries": [], "error": str(exc)})

    @bp.post("/history/clear")
    def history_clear():
        try:
            clear_history()
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)})

    @bp.post("/update-check")
    def update_check_endpoint():
        data = request.get_json(silent=True) or {}
        return jsonify(check_for_update(
            current_version=__version__,
            force=bool(data.get("force", False)),
        ))

    @bp.post("/updates/install-script/run")
    def update_install_script_run():
        try:
            script_info = fetch_platform_install_script()
            script_path = download_update_script(
                script_info["script_url"],
                script_info["script_name"],
            )
            process = launch_update_script(script_path)
            LOGGER.info(
                "update install script started name=%s version=%s path=%s pid=%s",
                script_info["script_name"],
                script_info["latest_version"],
                script_path,
                process.pid,
            )
            return jsonify({
                "ok": True,
                "latest_version": script_info["latest_version"],
                "release_url": script_info["release_url"],
                "script_name": script_info["script_name"],
                "script_path": str(script_path),
                "pid": process.pid,
            })
        except Exception as exc:
            LOGGER.error("updates/install-script/run failed: %s", traceback.format_exc())
            return jsonify({"ok": False, "error": str(exc)})

    @bp.post("/web-mode/start")
    def web_mode_start():
        try:
            process = launch_web_mode_process()
            return jsonify({"ok": True, "pid": process.pid})
        except Exception as exc:
            LOGGER.error("web-mode/start failed: %s", traceback.format_exc())
            return jsonify({"ok": False, "error": str(exc)})

    @bp.post("/mac/quick-action/install")
    def mac_quick_action_install():
        try:
            service_path = install_mac_quick_action()
            LOGGER.info("mac quick action installed path=%s", service_path)
            return jsonify({"ok": True, "path": str(service_path)})
        except Exception as exc:
            LOGGER.error("mac quick action install failed: %s", traceback.format_exc())
            return jsonify({"ok": False, "error": str(exc)})

    @bp.get("/logs/get")
    def logs_get():
        try:
            max_bytes = int(request.args.get("max_bytes", "50000"))
            max_bytes = max(1000, min(max_bytes, 500000))
            if not log_path.exists():
                return jsonify({"ok": True, "path": str(log_path), "text": ""})
            data = log_path.read_bytes()
            text = data[-max_bytes:].decode("utf-8", errors="replace")
            return jsonify({"ok": True, "path": str(log_path), "text": text})
        except Exception as exc:
            LOGGER.error("logs/get failed: %s", traceback.format_exc())
            return jsonify({"ok": False, "error": str(exc)})

    @bp.post("/logs/open")
    def logs_open():
        try:
            open_path(log_path)
            return jsonify({"ok": True, "path": str(log_path)})
        except Exception as exc:
            LOGGER.error("logs/open failed: %s", traceback.format_exc())
            return jsonify({"ok": False, "error": str(exc)})

    @bp.get("/diagnostics")
    def diagnostics():
        return jsonify({
            "ok": True,
            "log_path": str(log_path),
            "version": __version__,
        })

    @bp.get("/diagnostics/health")
    def diagnostics_health():
        try:
            return jsonify(health_check())
        except Exception as exc:
            LOGGER.error("diagnostics/health failed: %s", traceback.format_exc())
            return jsonify({"ok": False, "error": str(exc), "checks": []})

    @bp.post("/diagnostics/export")
    def diagnostics_export():
        try:
            out = write_debug_package()
            LOGGER.info("diagnostics package exported path=%s", out)
            return jsonify({"ok": True, "path": str(out)})
        except Exception as exc:
            LOGGER.error("diagnostics/export failed: %s", traceback.format_exc())
            return jsonify({"ok": False, "error": str(exc)})

    return bp
