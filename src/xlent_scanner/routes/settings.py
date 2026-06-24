"""Ruter for lokale regelsett og import/eksport av innstillinger."""
from __future__ import annotations

import logging
import re
import time

from flask import Blueprint, jsonify, request

from xlent_scanner import __version__
from xlent_scanner.blacklist import (
    blacklist_path_str,
    get_blacklist_entries,
    save_blacklist_entries,
)
from xlent_scanner.detectors.custom_patterns import (
    custom_patterns_path_str,
    get_custom_patterns_text,
    save_custom_patterns_text,
    validate_custom_patterns_text,
)
from xlent_scanner.ignore import (
    get_ignore_toml_text,
    ignore_path_str,
    save_ignore_toml_text,
)
from xlent_scanner.scanner import reset_ignore_cache
from xlent_scanner.whitelist import (
    get_whitelist_entries,
    save_whitelist_entries,
    whitelist_path_str,
)

LOGGER = logging.getLogger("xlent_scanner")
settings_bp = Blueprint("settings", __name__)


@settings_bp.post("/whitelist/get")
def whitelist_get():
    return jsonify({
        "ok": True,
        "path": whitelist_path_str(),
        "texts": get_whitelist_entries(),
    })


@settings_bp.post("/whitelist/save")
def whitelist_save():
    data = request.get_json(force=True)
    texts = data.get("texts", [])
    if not isinstance(texts, list):
        return jsonify({"ok": False, "error": "Ugyldig format for whitelist."})
    save_whitelist_entries([str(text) for text in texts])
    return jsonify({
        "ok": True,
        "path": whitelist_path_str(),
        "texts": get_whitelist_entries(),
    })


@settings_bp.post("/blacklist/get")
def blacklist_get():
    return jsonify({
        "ok": True,
        "path": blacklist_path_str(),
        "texts": get_blacklist_entries(),
    })


@settings_bp.post("/blacklist/save")
def blacklist_save():
    data = request.get_json(force=True)
    texts = data.get("texts", [])
    if not isinstance(texts, list):
        return jsonify({"ok": False, "error": "Ugyldig format for blacklist."})
    save_blacklist_entries([str(text) for text in texts])
    return jsonify({
        "ok": True,
        "path": blacklist_path_str(),
        "texts": get_blacklist_entries(),
    })


@settings_bp.post("/custom-patterns/get")
def custom_patterns_get():
    try:
        return jsonify({
            "ok": True,
            "path": custom_patterns_path_str(),
            "content": get_custom_patterns_text(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@settings_bp.post("/custom-patterns/save")
def custom_patterns_save():
    data = request.get_json(force=True)
    content = data.get("content", "")
    if not isinstance(content, str):
        return jsonify({"ok": False, "error": "Ugyldig format for custom_patterns.toml."})
    try:
        patterns = validate_custom_patterns_text(content)
        save_custom_patterns_text(content)
        LOGGER.info("custom-patterns lagret: %d mønstre", len(patterns))
        return jsonify({
            "ok": True,
            "path": custom_patterns_path_str(),
            "content": get_custom_patterns_text(),
            "pattern_count": len(patterns),
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except Exception as exc:
        LOGGER.exception("custom-patterns save failed")
        return jsonify({"ok": False, "error": str(exc)})


@settings_bp.post("/custom-patterns/test")
def custom_patterns_test():
    data = request.get_json(force=True) or {}
    regex = str(data.get("regex") or "")
    sample = str(data.get("sample") or "")
    ignore_case = bool(data.get("ignore_case", True))
    if not regex:
        return jsonify({"ok": False, "error": "Regex mangler."})
    try:
        flags = re.IGNORECASE if ignore_case else 0
        pattern = re.compile(regex, flags)
        matches = [
            {"text": match.group(0), "start": match.start(), "end": match.end()}
            for _, match in zip(range(20), pattern.finditer(sample))
        ]
        return jsonify({"ok": True, "matches": matches, "match_count": len(matches)})
    except re.error as exc:
        return jsonify({"ok": False, "error": f"Ugyldig regex: {exc}"})


@settings_bp.post("/settings/export")
def settings_export():
    data = request.get_json(silent=True) or {}
    browser_settings = data.get("browser_settings")
    if not isinstance(browser_settings, dict):
        browser_settings = {}
    return jsonify({
        "ok": True,
        "format": "xlent-scanner-settings",
        "format_version": 1,
        "app_version": __version__,
        "exported_at": int(time.time()),
        "browser_settings": browser_settings,
        "whitelist": get_whitelist_entries(),
        "blacklist": get_blacklist_entries(),
        "ignore_toml": get_ignore_toml_text(),
        "custom_patterns_toml": get_custom_patterns_text(),
    })


@settings_bp.post("/settings/import")
def settings_import():
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict) or data.get("format") != "xlent-scanner-settings":
            return jsonify({"ok": False, "error": "Ugyldig innstillingsfil."})

        whitelist = data.get("whitelist", [])
        if whitelist is not None:
            if not isinstance(whitelist, list):
                return jsonify({"ok": False, "error": "whitelist må være en liste."})
            save_whitelist_entries([str(text) for text in whitelist])

        blacklist = data.get("blacklist", [])
        if blacklist is not None:
            if not isinstance(blacklist, list):
                return jsonify({"ok": False, "error": "blacklist må være en liste."})
            save_blacklist_entries([str(text) for text in blacklist])

        ignore_toml = data.get("ignore_toml")
        if ignore_toml is not None:
            if not isinstance(ignore_toml, str):
                return jsonify({"ok": False, "error": "ignore_toml må være tekst."})
            save_ignore_toml_text(ignore_toml)
            reset_ignore_cache()

        custom_patterns_toml = data.get("custom_patterns_toml")
        if custom_patterns_toml is not None:
            if not isinstance(custom_patterns_toml, str):
                return jsonify({"ok": False, "error": "custom_patterns_toml må være tekst."})
            save_custom_patterns_text(custom_patterns_toml)

        browser_settings = data.get("browser_settings")
        if not isinstance(browser_settings, dict):
            browser_settings = {}

        return jsonify({
            "ok": True,
            "browser_settings": browser_settings,
            "whitelist": get_whitelist_entries(),
            "blacklist": get_blacklist_entries(),
            "ignore_toml": get_ignore_toml_text(),
            "custom_patterns_toml": get_custom_patterns_text(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@settings_bp.post("/ignore/get")
def ignore_get():
    try:
        return jsonify({
            "ok": True,
            "path": ignore_path_str(),
            "content": get_ignore_toml_text(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@settings_bp.post("/ignore/save")
def ignore_save():
    data = request.get_json(force=True)
    content = data.get("content", "")
    if not isinstance(content, str):
        return jsonify({"ok": False, "error": "Ugyldig format for ignore.toml."})
    try:
        save_ignore_toml_text(content)
        reset_ignore_cache()
        return jsonify({
            "ok": True,
            "path": ignore_path_str(),
            "content": get_ignore_toml_text(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})
