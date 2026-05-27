"""Embedded Flask-server + PyWebView-vindu.

Flask kjører i en bakgrunnstråd og eksponerer:
  GET  /          – returnerer index.html med port injisert
  POST /scan      – scanner en fil, returnerer JSON
  POST /open-dialog – åpner OS-filvelger, returnerer valgt sti
"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
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

from xlent_scanner.anonymize import anonymize_text, build_replacements
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES, patch_file
from xlent_scanner.report import generate_html
from xlent_scanner.scanner import scan_file
from xlent_scanner.whitelist import add_to_whitelist

_last_result = None
_last_path: Path | None = None

_window: webview.Window | None = None
flask_app = Flask(__name__, static_folder=None)
_web_dir = Path(__file__).parent / "web"
_port: int = 0

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


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
    return html, 200, {"Content-Type": "text/html; charset=utf-8", **_NO_CACHE}


@flask_app.route("/scan", methods=["POST"])
def scan():
    global _last_result, _last_path
    data = request.get_json(force=True)
    file_path = data.get("file_path", "")
    ignore_xlent = bool(data.get("ignore_xlent", False))
    language = data.get("language", "auto")
    result = scan_file(file_path, ignore_xlent=ignore_xlent, language=language)
    _last_result = result
    _last_path = Path(file_path) if file_path else None
    return jsonify(asdict(result))


@flask_app.route("/scan-upload", methods=["POST"])
def scan_upload():
    """Mottar fil som multipart-upload (brukes av drag-drop fallback)."""
    global _last_result, _last_path
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Ingen fil mottatt."})
    ignore_xlent = request.form.get("ignore_xlent", "false").lower() == "true"
    language = request.form.get("language", "auto")
    original_name = f.filename or "ukjent"
    suffix = Path(original_name).suffix.lower()

    # Lagre til midlertidig fil med riktig suffiks
    fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="xlent-drop-")
    tmp_path = Path(tmp)
    try:
        os.close(fd)
        f.save(str(tmp_path))
        result = scan_file(tmp_path, ignore_xlent=ignore_xlent, language=language)
        result.file_name = original_name   # vis originalt filnavn, ikke temp-sti
        _last_result = result
        _last_path = tmp_path              # brukes av /patch hvis aktuelt
        return jsonify(asdict(result))
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        return jsonify({"error": str(exc)})


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


def _start_flask(port: int) -> None:
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
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

    _port = _free_port()
    t = threading.Thread(target=_start_flask, args=(_port,), daemon=True)
    t.start()
    _wait_for_flask(_port)

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
    webview.start(debug=False, storage_path=webview_cache)


if __name__ == "__main__":
    main()
