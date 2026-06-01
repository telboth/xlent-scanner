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
from xlent_scanner.paths import app_data_dir
from xlent_scanner.ignore import (
    get_ignore_toml_text,
    ignore_path_str,
    save_ignore_toml_text,
)
from xlent_scanner.models import Finding
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES, patch_file
from xlent_scanner.report import generate_html
from xlent_scanner.history import add_history_entry, load_history, clear_history
from xlent_scanner.scanner import reset_ignore_cache, scan_file, scan_text, scan_folder
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
_last_ai_findings: list[dict] = []   # AI-dybdeskann-funn for sist skannede fil (vises i rapport)
_last_ai_findings_file: dict = {"name": ""}   # filnavnet AI-funnene tilhører

_window: webview.Window | None = None
_initial_file: str | None = None     # fil sendt via Windows kontekstmeny (sys.argv[1])
flask_app = Flask(__name__, static_folder=None)
_web_dir = Path(__file__).parent / "web"
_port: int = 0

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _setup_logging() -> tuple[logging.Logger, Path]:
    log_dir = app_data_dir() / "logs"
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
    from datetime import datetime  # noqa: PLC0415
    html = html.replace("__API_BASE__", f"http://127.0.0.1:{_port}")
    html = html.replace("__APP_VERSION__", __version__)
    html = html.replace("__APP_STARTED__", datetime.now().strftime("%d.%m.%Y %H:%M"))
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
        add_history_entry(
            file_name=result.file_name,
            risk_level=result.risk_level,
            finding_count=len(result.findings),
            file_size=result.file_size,
            source="file",
        )
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
        add_history_entry(
            file_name=result.file_name,
            risk_level=result.risk_level,
            finding_count=len(result.findings),
            file_size=result.file_size,
            source="file",
        )
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


@flask_app.route("/scan-text", methods=["POST"])
def scan_text_endpoint():
    """Skann tekst limt inn direkte (uten fil)."""
    global _last_result, _last_path
    try:
        data = request.get_json(force=True)
        text = data.get("text", "")
        language = data.get("language", "auto")
        LOGGER.info("scan-text request len=%d lang=%s", len(text), language)
        result = scan_text(text, language=language)
        _last_result = result
        _last_path = None
        add_history_entry(
            file_name=result.file_name,
            risk_level=result.risk_level,
            finding_count=len(result.findings),
            file_size=result.file_size,
            source="text",
        )
        LOGGER.info("scan-text result findings=%d", len(result.findings))
        return jsonify(asdict(result))
    except Exception as exc:
        LOGGER.error("scan-text endpoint failed: %s", traceback.format_exc())
        return jsonify({"error": f"Klarte ikke å skanne tekst: {exc}"})


@flask_app.route("/scan-folder", methods=["POST"])
def scan_folder_endpoint():
    """Skann alle støttede filer i en mappe (batch)."""
    try:
        data = request.get_json(force=True)
        folder_path = data.get("folder_path", "")
        ignore_xlent = bool(data.get("ignore_xlent", False))
        language = data.get("language", "auto")
        LOGGER.info("scan-folder request path=%s", folder_path)
        results = scan_folder(folder_path, ignore_xlent=ignore_xlent, language=language)
        summary = []
        for r in results:
            add_history_entry(
                file_name=r.file_name,
                risk_level=r.risk_level,
                finding_count=len(r.findings),
                file_size=r.file_size,
                source="batch",
            )
            summary.append({
                "file_name": r.file_name,
                "risk_level": r.risk_level,
                "finding_count": len(r.findings),
                "error": r.error,
                "file_size": r.file_size,
            })
        LOGGER.info("scan-folder result files=%d", len(summary))
        return jsonify({"files": summary, "total": len(summary)})
    except Exception as exc:
        LOGGER.error("scan-folder endpoint failed: %s", traceback.format_exc())
        return jsonify({"error": str(exc)})


@flask_app.route("/diagnostics", methods=["GET"])
def diagnostics():
    return jsonify({
        "ok": True,
        "log_path": str(LOG_PATH),
        "version": __version__,
    })


@flask_app.route("/startup-file", methods=["GET"])
def startup_file():
    """Returnerer filen som ble sendt via Windows høyreklikk-kontekstmeny (sys.argv[1])."""
    return jsonify({"path": _initial_file})


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


@flask_app.route("/report/ai-findings", methods=["POST"])
def set_ai_findings():
    """Lagrer AI-dybdeskann-funn for sist skannede fil slik at de kan
    inkluderes i rapporten. Knyttes til filnavn for å unngå utdaterte funn."""
    global _last_ai_findings
    data = request.get_json(force=True) or {}
    findings = data.get("findings") or []
    file_name = data.get("file_name") or ""
    if isinstance(findings, list):
        _last_ai_findings = [
            {"category": str(f.get("category", "")), "text": str(f.get("text", "")),
             "context": str(f.get("context", ""))}
            for f in findings if isinstance(f, dict)
        ]
        _last_ai_findings_file["name"] = file_name
    return jsonify({"ok": True, "count": len(_last_ai_findings)})


def _ai_findings_for_report() -> list[dict]:
    """Returnerer AI-funn kun hvis de tilhører sist skannede fil."""
    if _last_result is None:
        return []
    if _last_ai_findings_file.get("name") and _last_result.file_name != _last_ai_findings_file["name"]:
        return []
    return _last_ai_findings


@flask_app.route("/report")
def report():
    if _last_result is None:
        return "Ingen rapport tilgjengelig.", 404
    html = generate_html(
        _last_result,
        api_base=f"http://127.0.0.1:{_port}",
        ai_findings=_ai_findings_for_report(),
    )
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


def _write_text_pdf(text: str, out_path: Path, title: str = "") -> None:
    """Skriver ren tekst til en enkel, lesbar PDF (A4, ordbrytning) via pymupdf."""
    import fitz  # noqa: PLC0415

    doc = fitz.open()
    margin, width, height = 54, 595, 842
    max_width = width - 2 * margin
    fontsize, line_h = 10, 14
    fontname = "helv"

    def _new_page():
        return doc.new_page(width=width, height=height), margin

    page, y = _new_page()
    if title:
        page.insert_text((margin, y), title[:90], fontsize=14, fontname="hebo", color=(0.1, 0.2, 0.5))
        y += 22

    # Enkel ordbryting per linje basert på estimert tegnbredde
    char_w = fontsize * 0.5
    max_chars = max(20, int(max_width / char_w))
    for raw_line in text.split("\n"):
        if not raw_line.strip():
            y += line_h // 2
            continue
        words, cur = raw_line.split(" "), ""
        for w in words:
            test = (cur + " " + w).strip()
            if len(test) > max_chars:
                page.insert_text((margin, y), cur, fontsize=fontsize, fontname=fontname, color=(0.1, 0.1, 0.1))
                y += line_h
                cur = w
                if y > height - margin:
                    page, y = _new_page()
            else:
                cur = test
        if cur:
            page.insert_text((margin, y), cur, fontsize=fontsize, fontname=fontname, color=(0.1, 0.1, 0.1))
            y += line_h
            if y > height - margin:
                page, y = _new_page()

    doc.save(str(out_path), garbage=4, deflate=True)
    doc.close()


@flask_app.route("/report/pdf", methods=["GET"])
def report_pdf():
    """Generer og last ned PDF-rapport."""
    if _last_result is None:
        return "Ingen rapport tilgjengelig.", 404
    try:
        import fitz  # noqa: PLC0415
        from datetime import datetime  # noqa: PLC0415

        RISK_COLORS = {
            "grønn": (0.18, 0.69, 0.31),
            "gul":   (0.85, 0.60, 0.15),
            "rød":   (0.87, 0.22, 0.22),
            "svart": (0.61, 0.15, 0.69),
        }
        SEV_COLORS = RISK_COLORS

        doc = fitz.open()

        def _new_page():
            p = doc.new_page(width=595, height=842)
            return p, 54

        page, y = _new_page()

        def _text(pg, yp, txt, size=10, color=(0.85, 0.88, 0.93), bold=False):
            fn = "hebo" if bold else "helv"   # hebo = Helvetica-Bold (base-14)
            rc = pg.insert_text((54, yp), txt, fontsize=size, fontname=fn, color=color)
            return yp + size + 4

        # Header
        y = _text(page, y, "XLENT Compliance-scanner", 18, (0.31, 0.56, 1.0), bold=True)
        y = _text(page, y, f"Fil: {_last_result.file_name}", 11)
        y = _text(page, y, f"Dato: {datetime.now().strftime('%d.%m.%Y  %H:%M')}", 9, (0.55, 0.62, 0.72))
        y += 6

        # Risk level
        rc_color = RISK_COLORS.get(_last_result.risk_level, (0.85, 0.88, 0.93))
        y = _text(page, y, f"Risikonivå: {_last_result.risk_level.upper()}  –  {_last_result.risk_summary}", 12, rc_color, bold=True)
        y = _text(page, y, _last_result.recommended_action, 9, (0.72, 0.77, 0.85))
        y += 10

        # Divider
        page.draw_line((54, y), (541, y), color=(0.22, 0.31, 0.44), width=0.5)
        y += 8

        # Findings
        if not _last_result.findings:
            y = _text(page, y, "Ingen sensitive funn oppdaget.", 10, (0.18, 0.69, 0.31))
        else:
            y = _text(page, y, f"Funn ({len(_last_result.findings)})", 11, (0.85, 0.88, 0.93), bold=True)
            y += 4
            for f in _last_result.findings:
                if y > 800:
                    page, y = _new_page()
                    y = _text(page, y, "(fortsetter…)", 8, (0.55, 0.62, 0.72))
                    y += 4
                sev_c = SEV_COLORS.get(f.severity, (0.72, 0.77, 0.85))
                line = f"[{f.category}]  {f.text[:120]}"
                y = _text(page, y, line, 9, sev_c)
                if f.context:
                    ctx_line = f"    {f.context[:140]}"
                    y = _text(page, y, ctx_line, 7.5, (0.50, 0.57, 0.68))
                y += 1

        # AI-dybdeskann-funn (egen seksjon)
        from xlent_scanner.report import ai_severity  # noqa: PLC0415
        ai_findings = _ai_findings_for_report()
        if ai_findings:
            if y > 770:
                page, y = _new_page()
            y += 8
            page.draw_line((54, y), (541, y), color=(0.22, 0.31, 0.44), width=0.5)
            y += 8
            y = _text(page, y, f"AI-dybdeskann-funn ({len(ai_findings)})", 11, (0.85, 0.88, 0.93), bold=True)
            y += 4
            for f in ai_findings:
                if y > 800:
                    page, y = _new_page()
                cat = str(f.get("category", ""))
                sev_c = SEV_COLORS.get(ai_severity(cat), (0.72, 0.77, 0.85))
                y = _text(page, y, f"[{cat}]  {str(f.get('text',''))[:120]}", 9, sev_c)
                ctx = str(f.get("context", ""))
                if ctx:
                    y = _text(page, y, f"    {ctx[:140]}", 7.5, (0.50, 0.57, 0.68))
                y += 1

        pdf_bytes = doc.tobytes()
        doc.close()

        stem = Path(_last_result.file_name).stem
        filename = f"{stem}-rapport.pdf"
        return pdf_bytes, 200, {
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
    except Exception as exc:
        LOGGER.error("report/pdf failed: %s", traceback.format_exc())
        return f"PDF-generering feilet: {exc}", 500


@flask_app.route("/anonymize", methods=["POST"])
def anonymize():
    if _last_result is None:
        return jsonify({"error": "Ingen rapport tilgjengelig."})
    if not _last_result.original_text:
        return jsonify({"error": "Originaltekst ikke tilgjengelig. Re-skann filen."})
    data = request.get_json(force=True)
    indices = data.get("indices", [])
    ai_texts_raw = data.get("ai_texts", [])
    selected = [
        _last_result.findings[i]
        for i in indices
        if isinstance(i, int) and 0 <= i < len(_last_result.findings)
    ]
    ai_texts: list[str] = []
    if isinstance(ai_texts_raw, list):
        ai_texts = [str(t).strip() for t in ai_texts_raw if isinstance(t, str) and str(t).strip()]
    if ai_texts:
        selected.extend(
            Finding(category="🤖 AI-funn", text=t, context="", severity="gul", raw_text=t)
            for t in ai_texts
        )
    cleaned = anonymize_text(_last_result.original_text, selected)
    fmt = (data.get("format") or "md").lower()
    if fmt not in ("md", "pdf"):
        fmt = "md"

    stem = Path(_last_result.file_name).stem
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"
    out = downloads / f"{stem}-anonymisert.{fmt}"
    counter = 1
    while out.exists():
        out = downloads / f"{stem}-anonymisert-{counter}.{fmt}"
        counter += 1

    if fmt == "pdf":
        try:
            _write_text_pdf(cleaned, out, title=f"{stem} – anonymisert")
        except Exception as exc:
            LOGGER.error("anonymize pdf failed: %s", traceback.format_exc())
            return jsonify({"error": f"PDF-generering feilet: {exc}"})
    else:
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
    ai_texts_raw = data.get("ai_texts", [])
    selected = [
        _last_result.findings[i]
        for i in indices
        if isinstance(i, int) and 0 <= i < len(_last_result.findings)
    ]
    ai_texts: list[str] = []
    if isinstance(ai_texts_raw, list):
        ai_texts = [str(t).strip() for t in ai_texts_raw if isinstance(t, str) and str(t).strip()]
    if ai_texts:
        selected.extend(
            Finding(category="🤖 AI-funn", text=t, context="", severity="gul", raw_text=t)
            for t in ai_texts
        )
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
            "Dokumenter (*.pdf;*.docx;*.pptx;*.xlsx;*.txt;*.md;*.html;*.csv;*.eml;*.rtf;*.odt)",
            "Alle filer (*.*)",
        ),
    )
    path = result[0] if result else None
    return jsonify({"path": path})


@flask_app.route("/history/get", methods=["GET"])
def history_get():
    """Hent persistent scan-historikk."""
    try:
        entries = load_history()
        return jsonify({"ok": True, "entries": list(reversed(entries))})
    except Exception as exc:
        return jsonify({"ok": False, "entries": [], "error": str(exc)})


@flask_app.route("/history/clear", methods=["POST"])
def history_clear():
    """Slett all scan-historikk."""
    try:
        clear_history()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@flask_app.route("/open-folder-dialog", methods=["POST"])
def open_folder_dialog():
    """Åpne mappe-velger-dialog."""
    if _window is None:
        return jsonify({"path": None})
    result = _window.create_file_dialog(
        webview.FOLDER_DIALOG,
        allow_multiple=False,
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


@flask_app.route("/ollama/hardware-info", methods=["GET"])
def ollama_hardware_info_endpoint():
    """Returner GPU/CPU-info for pågående Ollama-modell via /api/ps."""
    from xlent_scanner.deep_scanner import ollama_hardware_info  # noqa: PLC0415
    return jsonify(ollama_hardware_info())


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
    min_confidence = (data.get("min_confidence") or "medium").strip().lower()
    if min_confidence not in ("high", "medium", "low"):
        min_confidence = "medium"
    job_id = start_deep_scan(text, model, lang, categories=categories, min_confidence=min_confidence)
    LOGGER.info("ollama/deep-scan started job=%s model=%s cats=%s", job_id, model, categories)
    return jsonify({"ok": True, "job_id": job_id})


@flask_app.route("/ollama/anonymize-findings", methods=["POST"])
def ollama_anonymize_findings():
    """Anonymiser valgte AI-funn og lagre til fil.

    Produserer samme filformat som kilden (docx→docx, pptx→pptx, xlsx→xlsx, pdf→pdf).
    Faller tilbake til .txt hvis formatet ikke støttes eller kildefilen mangler.
    """
    if _last_result is None:
        return jsonify({"error": "Ingen fil skannet."})
    data = request.get_json(force=True) or {}
    texts_to_remove = [str(t).strip() for t in (data.get("texts") or []) if t and str(t).strip()]
    if not texts_to_remove:
        return jsonify({"error": "Ingen tekst valgt for anonymisering."})

    stem = Path(_last_result.file_name).stem if _last_result.file_name else "dokument"
    suffix = _last_path.suffix.lower() if _last_path else ""
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"

    # Bruk patch_file for støttede filformater når kildefilen er tilgjengelig
    if _last_path and _last_path.exists() and suffix in SUPPORTED_PATCH_SUFFIXES:
        replacements = {t: "[ANONYMISERT]" for t in texts_to_remove}
        out = downloads / f"{stem}-ai-anonymisert{suffix}"
        counter = 1
        while out.exists():
            out = downloads / f"{stem}-ai-anonymisert-{counter}{suffix}"
            counter += 1
        try:
            patch_file(_last_path, replacements, out)
            LOGGER.info("ollama/anonymize-findings patch: wrote %s (%d replacements)", out, len(texts_to_remove))
            return jsonify({"ok": True, "path": str(out)})
        except Exception as exc:
            LOGGER.warning("patch_file feilet, faller tilbake til .txt: %s", exc)

    # Fallback: teksterstatning i originalstreng → .txt
    text = getattr(_last_result, "original_text", "") or ""
    if not text.strip():
        return jsonify({"error": "Originaltekst ikke tilgjengelig. Re-skann filen."})
    result_text = text
    for t_str in texts_to_remove:
        result_text = result_text.replace(t_str, "[ANONYMISERT]")
    out = downloads / f"{stem}-ai-anonymisert.txt"
    counter = 1
    while out.exists():
        out = downloads / f"{stem}-ai-anonymisert-{counter}.txt"
        counter += 1
    out.write_text(result_text, encoding="utf-8")
    LOGGER.info("ollama/anonymize-findings txt: wrote %s (%d replacements)", out, len(texts_to_remove))
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


# ── CLI-modus ─────────────────────────────────────────────────────────────────

def _cli_scan() -> None:
    """Kommandolinje-modus: skann en fil og skriv ut funn uten GUI.

    Bruk:
      xlent-scanner --scan FIL [--json] [--lang nb|sv|en|auto]

    Exit-kode: 0 = rent, 1 = gul, 2 = rød, 3 = svart.
    """
    import argparse
    from dataclasses import asdict

    parser = argparse.ArgumentParser(
        prog="xlent-scanner",
        description="XLENT Compliance-scanner — skann fil for sensitiv informasjon",
    )
    parser.add_argument("--scan", required=True, metavar="FIL", help="Fil som skal skannes")
    parser.add_argument("--json", action="store_true", help="Skriv funn som JSON på stdout")
    parser.add_argument("--lang", default="auto", metavar="LANG",
                        help="Språk: nb / sv / en / auto (standard: auto)")
    args = parser.parse_args()

    result = scan_file(args.scan, language=args.lang)

    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        level_icon = {"grønn": "✅", "gul": "⚠️", "rød": "🚫", "svart": "⛔"}.get(
            result.risk_level, "?"
        )
        print(f"{level_icon}  {result.file_name}  [{result.risk_level.upper()}]")
        print(f"   {result.risk_summary}")
        if result.error:
            print(f"   Feil: {result.error}")
        for f in result.findings:
            sev_icon = {"svart": "⛔", "rød": "🚫", "gul": "⚠️", "grønn": "✅"}.get(
                f.severity, "•"
            )
            print(f"   {sev_icon} [{f.category}] {f.text}")

    exit_code = {"grønn": 0, "gul": 1, "rød": 2, "svart": 3}.get(result.risk_level, 0)
    sys.exit(exit_code)


# ── Enkel-instans IPC ──────────────────────────────────────────────────────────
# Brukes når appen åpnes fra Windows kontekstmeny:
# - Første instans: bind IPC-socket og kjør GUI
# - Etterfølgende instanser: send filsti til første instans og avslutt

_IPC_PORT = 51290   # fast lokal port for xlent-scanner IPC


def _ipc_send_and_exit(file_path: str) -> None:
    """Send filsti til en eksisterende instans og avslutt."""
    try:
        with socket.create_connection(("127.0.0.1", _IPC_PORT), timeout=1.0) as s:
            s.sendall((file_path + "\n").encode("utf-8"))
        LOGGER.info("IPC: filsti sendt til eksisterende instans: %s", file_path)
        sys.exit(0)
    except OSError:
        pass  # Ingen eksisterende instans — fortsett som ny


def _ipc_start_server() -> None:
    """Start IPC-lytter som mottar filstier fra nye instanser.

    Når en ny filsti ankommer, trigger vi scanPath() i det kjørende vinduet
    via evaluate_js — ingen sidelasting nødvendig.
    """
    def _listen() -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", _IPC_PORT))
            srv.listen(5)
            LOGGER.info("IPC-server lytter på port %s", _IPC_PORT)
            while True:
                conn, addr = srv.accept()
                try:
                    data = conn.recv(4096).decode("utf-8").strip()
                    if data and _window:
                        LOGGER.info("IPC: mottok filsti: %s", data)
                        path_js = json.dumps(data)
                        _window.evaluate_js(
                            f"(function(){{"
                            f"  document.querySelector('[data-tab=\"scanner\"]')?.click();"
                            f"  scanPath({path_js});"
                            f"}})()"
                        )
                finally:
                    conn.close()
        except Exception as exc:
            LOGGER.warning("IPC-server feilet: %s", exc)

    t = threading.Thread(target=_listen, daemon=True, name="ipc-server")
    t.start()


def main() -> None:
    global _window, _port, _initial_file

    # ── CLI-modus ──────────────────────────────────────────────────────────
    if "--scan" in sys.argv:
        _cli_scan()
        return  # _cli_scan kaller sys.exit, men for type-checker:
        return  # noqa: unreachable

    # ── Fil fra Windows kontekstmeny (argv[1]) ──────────────────────────────
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        _initial_file = sys.argv[1]
        LOGGER.info("Startup file from argv: %s", _initial_file)
        # Enkel-instans: hvis en instans allerede kjører, send filen dit
        _ipc_send_and_exit(_initial_file)
        # Kommer hit: vi er første instans

    LOGGER.info("App starting version=%s", __version__)
    LOGGER.info(
        "Runtime python=%s executable=%s platform=%s",
        sys.version.split()[0],
        sys.executable,
        platform.platform(),
    )
    LOGGER.info("PyWebView version=%s", getattr(webview, "__version__", "unknown"))
    _validate_runtime_dependencies()

    # Start IPC-server (enkel-instans-støtte for kontekstmeny-åpning)
    _ipc_start_server()

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
