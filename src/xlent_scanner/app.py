"""Embedded Flask-server + PyWebView-vindu.

Flask kjører i en bakgrunnstråd og eksponerer:
  GET  /          – returnerer index.html med port injisert
  POST /scan      – scanner en fil, returnerer JSON
  POST /open-dialog – åpner OS-filvelger, returnerer valgt sti
"""
from __future__ import annotations

import faulthandler
import json
import logging
import os
import platform
import socket
import sys
import tempfile
import threading
import time
import traceback
import warnings
import webbrowser
from dataclasses import asdict
from pathlib import Path

# Docling gir UserWarning for bilder i PPTX-filer som mangler innebygd bildedata.
# Dette er støy vi ikke kan gjøre noe med – demp det.
warnings.filterwarnings(
    "ignore",
    message="Skipping malformed picture shape",
    category=UserWarning,
    module=r"docling\..+",
)

import webview
from flask import Flask, jsonify, request

from xlent_scanner import __version__
from xlent_scanner.anonymize import anonymize_text, build_replacements
from xlent_scanner.ignore import (
    get_ignore_toml_text,
    ignore_path_str,
    save_ignore_toml_text,
)
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES, patch_file
from xlent_scanner.report import generate_html
from xlent_scanner.scanner import reset_ignore_cache, scan_file
from xlent_scanner.update_check import check_for_update
from xlent_scanner.whitelist import (
    add_to_whitelist,
    get_whitelist_entries,
    save_whitelist_entries,
    whitelist_path_str,
)

_last_result = None
_last_path: Path | None = None
_last_tmp_path: Path | None = None   # temp-fil fra forrige upload – ryddes opp ved neste upload

_window: webview.Window | None = None
flask_app = Flask(__name__, static_folder=None)
_web_dir = Path(__file__).parent / "web"
_port: int = 0

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _app_data_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / "Library" / "Application Support"
    d = base / "xlent-scanner"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _setup_logging() -> tuple[logging.Logger, Path]:
    log_dir = _app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    logger = logging.getLogger("xlent_scanner")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(fh)

    try:
        global _FAULT_FILE_HANDLE
        _FAULT_FILE_HANDLE = open(log_dir / "faulthandler.log", "a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE_HANDLE, all_threads=True)
    except Exception:
        _FAULT_FILE_HANDLE = None

    return logger, log_path


LOGGER, LOG_PATH = _setup_logging()


def _log_unhandled(exc_type, exc_value, exc_tb):
    LOGGER.error("UNHANDLED EXCEPTION: %s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _log_thread_exception(args):
    LOGGER.error(
        "THREAD EXCEPTION in %s: %s",
        getattr(args.thread, "name", "unknown"),
        "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
    )


sys.excepthook = _log_unhandled
threading.excepthook = _log_thread_exception


def _validate_runtime_dependencies() -> None:
    """Feil tidlig hvis obligatoriske runtime-avhengigheter mangler."""
    try:
        import fitz  # type: ignore[import-untyped]  # pymupdf
    except Exception as exc:
        raise RuntimeError(
            "Mangler obligatorisk avhengighet: pymupdf (fitz). "
            "Kjør 'uv sync' før oppstart."
        ) from exc


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@flask_app.route("/")
def index():
    idx = _web_dir / "index.html"
    print(f"[flask] Serving {idx}  (mtime {idx.stat().st_mtime:.0f})", flush=True)
    html = idx.read_text("utf-8")
    # Injiser port slik at JS kan bruke absolutte URL-er
    html = html.replace("__API_BASE__", f"http://127.0.0.1:{_port}")
    html = html.replace("__APP_VERSION__", __version__)
    html = html.replace('"__LOG_PATH__"', json.dumps(str(LOG_PATH)))
    return html, 200, {"Content-Type": "text/html; charset=utf-8", **_NO_CACHE}


@flask_app.route("/scan", methods=["POST"])
def scan():
    global _last_result, _last_path
    try:
        data = request.get_json(force=True)
        file_path = data.get("file_path", "")
        ignore_xlent = bool(data.get("ignore_xlent", False))
        language = data.get("language", "auto")
        LOGGER.info("scan request path=%s lang=%s ignore_xlent=%s", file_path, language, ignore_xlent)
        result = scan_file(file_path, ignore_xlent=ignore_xlent, language=language)
        _last_result = result
        _last_path = Path(file_path) if file_path else None
        LOGGER.info("scan result path=%s error=%s findings=%s", file_path, bool(result.error), len(result.findings))
        return jsonify(asdict(result))
    except Exception as exc:
        LOGGER.error("scan endpoint failed: %s", traceback.format_exc())
        return jsonify({
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
            "original_text": "",
            "error": f"Klarte ikke å lese fil: {exc}",
        })


@flask_app.route("/scan-upload", methods=["POST"])
def scan_upload():
    """Mottar fil som multipart-upload (brukes av drag-drop fallback)."""
    global _last_result, _last_path, _last_tmp_path
    try:
        f = request.files.get("file")
        if not f:
            return jsonify({"error": "Ingen fil mottatt."})
        ignore_xlent = request.form.get("ignore_xlent", "false").lower() == "true"
        language = request.form.get("language", "auto")
        original_name = f.filename or "ukjent"
        suffix = Path(original_name).suffix.lower()
        LOGGER.info("scan-upload request name=%s suffix=%s lang=%s ignore_xlent=%s", original_name, suffix, language, ignore_xlent)

        # Rydd opp forrige temp-fil (fra tidligere drag-drop/upload)
        if _last_tmp_path and _last_tmp_path.exists():
            try:
                _last_tmp_path.unlink()
            except OSError:
                pass
        _last_tmp_path = None

        # Lagre til midlertidig fil med riktig suffiks
        fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="xlent-drop-")
        tmp_path = Path(tmp)
        os.close(fd)
        f.save(str(tmp_path))
        result = scan_file(tmp_path, ignore_xlent=ignore_xlent, language=language)
        result.file_name = original_name   # vis originalt filnavn, ikke temp-sti
        _last_result = result
        _last_path = tmp_path              # brukes av /patch hvis aktuelt
        _last_tmp_path = tmp_path          # huskes for opprydding ved neste upload
        LOGGER.info("scan-upload result name=%s error=%s findings=%s", original_name, bool(result.error), len(result.findings))
        return jsonify(asdict(result))
    except Exception as exc:
        LOGGER.error("scan-upload endpoint failed: %s", traceback.format_exc())
        try:
            tmp_path.unlink(missing_ok=True)  # type: ignore[name-defined]
        except Exception:
            pass
        return jsonify({
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
            "original_text": "",
            "error": f"Klarte ikke å lese fil: {exc}",
        })


@flask_app.route("/diagnostics", methods=["GET"])
def diagnostics():
    return jsonify({
        "ok": True,
        "log_path": str(LOG_PATH),
        "version": __version__,
    })


@flask_app.route("/logo.svg")
def logo_svg():
    svg_path = Path(__file__).parent / "web" / "logo.svg"
    if not svg_path.exists():
        return "", 404
    return svg_path.read_text("utf-8"), 200, {"Content-Type": "image/svg+xml"}


@flask_app.route("/add-to-whitelist", methods=["POST"])
def add_to_whitelist_endpoint():
    data = request.get_json(force=True)
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "Ingen tekst oppgitt."})
    add_to_whitelist(text)
    return jsonify({"ok": True})


@flask_app.route("/report")
def report():
    if _last_result is None:
        return "Ingen rapport tilgjengelig.", 404
    html = generate_html(_last_result, api_base=f"http://127.0.0.1:{_port}")
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@flask_app.route("/open-report", methods=["POST"])
def open_report():
    if _last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig ennå."})
    try:
        url = f"http://127.0.0.1:{_port}/report"
        webbrowser.open(url)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)})


@flask_app.route("/anonymize", methods=["POST"])
def anonymize():
    if _last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig."})
    if not _last_result.original_text:
        return jsonify({"error": "Originaltekst ikke tilgjengelig. Re-skann filen."})
    data = request.get_json(force=True)
    indices = data.get("indices", [])
    selected = [
        _last_result.findings[i]
        for i in indices
        if isinstance(i, int) and 0 <= i < len(_last_result.findings)
    ]
    cleaned = anonymize_text(_last_result.original_text, selected)

    stem = Path(_last_result.file_name).stem
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"
    out = downloads / f"{stem}-anonymisert.md"
    counter = 1
    while out.exists():
        out = downloads / f"{stem}-anonymisert-{counter}.md"
        counter += 1
    out.write_text(cleaned, encoding="utf-8")
    return jsonify({"ok": True, "path": str(out)})


@flask_app.route("/patch", methods=["POST"])
def patch():
    if _last_result is None or _last_path is None:
        return jsonify({"error": "Ingen skannet fil tilgjengelig."})
    suffix = _last_path.suffix.lower()
    if suffix not in SUPPORTED_PATCH_SUFFIXES:
        return jsonify({"error": f"In-place anonymisering støttes ikke for {suffix}."})

    data = request.get_json(force=True)
    indices = data.get("indices", [])
    selected = [
        _last_result.findings[i]
        for i in indices
        if isinstance(i, int) and 0 <= i < len(_last_result.findings)
    ]
    replacements = build_replacements(selected)
    if not replacements:
        return jsonify({"error": "Ingen av de valgte funnene kan anonymiseres direkte."})

    stem = _last_path.stem
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"
    out = downloads / f"{stem}-anonymisert{suffix}"
    counter = 1
    while out.exists():
        out = downloads / f"{stem}-anonymisert-{counter}{suffix}"
        counter += 1

    try:
        patch_file(_last_path, replacements, out)
    except Exception as exc:
        return jsonify({"error": str(exc)})

    return jsonify({"ok": True, "path": str(out)})


@flask_app.route("/export/json", methods=["POST"])
def export_json():
    if _last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig."})
    import json as _json
    data = {
        "file_name": _last_result.file_name,
        "scanned_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "risk_level": _last_result.risk_level,
        "risk_summary": _last_result.risk_summary,
        "language": _last_result.language,
        "findings": [
            {
                "severity": f.severity,
                "category": f.category,
                "text": f.text,
                "context": f.context,
            }
            for f in _last_result.findings
        ],
    }
    stem = Path(_last_result.file_name).stem
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"
    out = downloads / f"{stem}-funn.json"
    counter = 1
    while out.exists():
        out = downloads / f"{stem}-funn-{counter}.json"
        counter += 1
    out.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "path": str(out)})


@flask_app.route("/export/csv", methods=["POST"])
def export_csv():
    if _last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig."})
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["severity", "category", "text", "context"])
    for f in _last_result.findings:
        writer.writerow([f.severity, f.category, f.text, f.context])
    stem = Path(_last_result.file_name).stem
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"
    out = downloads / f"{stem}-funn.csv"
    counter = 1
    while out.exists():
        out = downloads / f"{stem}-funn-{counter}.csv"
        counter += 1
    # utf-8-sig gir BOM som Excel på Windows trenger for korrekt visning
    out.write_text(buf.getvalue(), encoding="utf-8-sig")
    return jsonify({"ok": True, "path": str(out)})


@flask_app.route("/open-dialog", methods=["POST"])
def open_dialog():
    if _window is None:
        return jsonify({"path": None})
    result = _window.create_file_dialog(
        webview.OPEN_DIALOG,
        allow_multiple=False,
        file_types=(
            "Dokumenter (*.pdf;*.docx;*.pptx;*.xlsx;*.txt;*.md;*.html)",
            "Alle filer (*.*)",
        ),
    )
    path = result[0] if result else None
    return jsonify({"path": path})


@flask_app.route("/update-check", methods=["POST"])
def update_check():
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force", False))
    return jsonify(check_for_update(current_version=__version__, force=force))


@flask_app.route("/whitelist/get", methods=["POST"])
def whitelist_get():
    return jsonify({
        "ok": True,
        "path": whitelist_path_str(),
        "texts": get_whitelist_entries(),
    })


@flask_app.route("/whitelist/save", methods=["POST"])
def whitelist_save():
    data = request.get_json(force=True)
    texts = data.get("texts", [])
    if not isinstance(texts, list):
        return jsonify({"ok": False, "error": "Ugyldig format for whitelist."})
    save_whitelist_entries([str(t) for t in texts])
    return jsonify({
        "ok": True,
        "path": whitelist_path_str(),
        "texts": get_whitelist_entries(),
    })



@flask_app.route("/ignore/get", methods=["POST"])
def ignore_get():
    try:
        return jsonify({
            "ok": True,
            "path": ignore_path_str(),
            "content": get_ignore_toml_text(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@flask_app.route("/models/status", methods=["GET"])
def models_status_endpoint():
    """Returnerer installasjonsstatus for alle spaCy-modeller."""
    from xlent_scanner.model_manager import models_status  # noqa: PLC0415
    return jsonify(models_status())


@flask_app.route("/models/download", methods=["POST"])
def models_download_endpoint():
    """Starter nedlasting av en spaCy-modell i bakgrunnstråd."""
    from xlent_scanner.model_manager import (  # noqa: PLC0415
        _MODEL_VERSIONS,
        download_model_async,
    )
    data = request.get_json(force=True)
    model = (data.get("model") or "").strip()
    if not model or model not in _MODEL_VERSIONS:
        return jsonify({"ok": False, "error": f"Ukjent modell: {model!r}"})
    started = download_model_async(model)
    LOGGER.info("models/download model=%s started=%s", model, started)
    return jsonify({"ok": True, "model": model, "started": started})


# ── Ollama / dybdeskann ─────────────────────────────────────────────────

@flask_app.route("/ollama/status", methods=["GET"])
def ollama_status_endpoint():
    """Sjekk om Ollama kjører og hent tilgjengelige modeller."""
    from xlent_scanner.deep_scanner import ollama_status  # noqa: PLC0415
    return jsonify(ollama_status())


@flask_app.route("/ollama/last-file-info", methods=["GET"])
def ollama_last_file_info():
    """Returnerer info om sist skannede fil for Dybdeskann-fanen."""
    if _last_result is None or getattr(_last_result, "error", None):
        return jsonify({"available": False})
    text = getattr(_last_result, "original_text", "") or ""
    return jsonify({
        "available": bool(text.strip()),
        "file_name": _last_result.file_name or "",
        "text_length": _last_result.text_length or 0,
    })


@flask_app.route("/ollama/deep-scan", methods=["POST"])
def ollama_deep_scan_endpoint():
    """Start dybdeskanning med Ollama på sist skannede fil."""
    from xlent_scanner.deep_scanner import start_deep_scan  # noqa: PLC0415
    if _last_result is None:
        return jsonify({"ok": False, "error": "Ingen fil er skannet ennå."})
    text = getattr(_last_result, "original_text", "") or ""
    if not text.strip():
        return jsonify({"ok": False, "error": "Ingen tekst å analysere i sist skannede fil."})
    data  = request.get_json(force=True)
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"ok": False, "error": "Ingen Ollama-modell oppgitt."})
    categories = data.get("categories") or None
    lang = getattr(_last_result, "language", "nb") or "nb"
    job_id = start_deep_scan(text, model, lang, categories=categories)
    LOGGER.info("ollama/deep-scan started job=%s model=%s cats=%s", job_id, model, categories)
    return jsonify({"ok": True, "job_id": job_id})


@flask_app.route("/ollama/anonymize-findings", methods=["POST"])
def ollama_anonymize_findings():
    """Anonymiser valgte AI-funn og lagre til fil."""
    if _last_result is None:
        return jsonify({"error": "Ingen fil skannet."})
    text = getattr(_last_result, "original_text", "") or ""
    if not text.strip():
        return jsonify({"error": "Originaltekst ikke tilgjengelig. Re-skann filen."})
    data = request.get_json(force=True) or {}
    texts_to_remove = [t for t in (data.get("texts") or []) if t and str(t).strip()]
    result_text = text
    for t in texts_to_remove:
        result_text = result_text.replace(str(t), "[ANONYMISERT]")
    stem = Path(_last_result.file_name).stem if _last_result.file_name else "dokument"
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"
    out = downloads / f"{stem}-ai-anonymisert.txt"
    counter = 1
    while out.exists():
        out = downloads / f"{stem}-ai-anonymisert-{counter}.txt"
        counter += 1
    out.write_text(result_text, encoding="utf-8")
    LOGGER.info("ollama/anonymize-findings: wrote %s (%d replacements)", out, len(texts_to_remove))
    return jsonify({"ok": True, "path": str(out)})


@flask_app.route("/ollama/deep-scan/status", methods=["GET"])
def ollama_deep_scan_status_endpoint():
    """Hent status / fremdrift / funn for pågående dybdeskann."""
    from xlent_scanner.deep_scanner import get_deep_scan_status  # noqa: PLC0415
    return jsonify(get_deep_scan_status())


@flask_app.route("/ollama/deep-scan/cancel", methods=["POST"])
def ollama_deep_scan_cancel_endpoint():
    """Avbryt pågående dybdeskann."""
    from xlent_scanner.deep_scanner import cancel_deep_scan  # noqa: PLC0415
    cancel_deep_scan()
    return jsonify({"ok": True})


@flask_app.route("/ignore/save", methods=["POST"])
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


def _start_flask(port: int) -> None:
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    LOGGER.info("Starting Flask on 127.0.0.1:%s", port)
    flask_app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)


def _wait_for_flask(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"Flask startet ikke på port {port} innen {timeout}s")


def main() -> None:
    global _window, _port

    LOGGER.info("App starting version=%s", __version__)
    LOGGER.info(
        "Runtime python=%s executable=%s platform=%s",
        sys.version.split()[0],
        sys.executable,
        platform.platform(),
    )
    LOGGER.info("PyWebView version=%s", getattr(webview, "__version__", "unknown"))
    _validate_runtime_dependencies()

    _port = _free_port()
    t = threading.Thread(target=_start_flask, args=(_port,), daemon=True)
    t.start()
    _wait_for_flask(_port)
    LOGGER.info("Flask is reachable on 127.0.0.1:%s", _port)

    webview_cache = tempfile.mkdtemp(prefix="xlent-scanner-wv-")
    fresh_url = f"http://127.0.0.1:{_port}/?_v={int(time.time())}"

    # Etter at vinduet er synlig, tving en reload til en URL med unikt tidsstempel.
    # Dette sikrer at WebView2 alltid gjør en ekte HTTP-forespørsel mot Flask
    # og aldri viser en cachet side – uavhengig av WebView2 sin interne cache-konfigurasjon.
    def _force_fresh_load():
        if _window.events.shown.wait(timeout=10):
            _window.load_url(fresh_url)

    _window = webview.create_window(
        title="XLENT Compliance-scanner",
        url=f"http://127.0.0.1:{_port}",
        width=900,
        height=700,
        min_size=(700, 500),
    )
    threading.Thread(target=_force_fresh_load, daemon=True).start()
    LOGGER.info("Window created. API base: http://127.0.0.1:%s", _port)
    webview.start(debug=False, storage_path=webview_cache)


if __name__ == "__main__":
    main()
