"""Embedded Flask-server + PyWebView-vindu.

Flask kjører i en bakgrunnstråd og eksponerer:
  GET  /          – returnerer index.html med port injisert
  POST /scan      – scanner en fil, returnerer JSON
  POST /open-dialog – åpner OS-filvelger, returnerer valgt sti
"""
from __future__ import annotations

import faulthandler
import base64
import binascii
import html
import json
import logging
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
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
from xlent_scanner.blacklist import (
    blacklist_path_str,
    get_blacklist_entries,
    save_blacklist_entries,
)
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
from xlent_scanner.update_check import check_for_update, fetch_platform_install_script
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
_api_scan_results: dict[str, dict] = {}  # Separat state for eksternt API; påvirker ikke GUI-state.
_api_scan_lock = threading.Lock()

_window: webview.Window | None = None
_initial_file: str | None = None     # fil sendt via Windows kontekstmeny (sys.argv[1])
flask_app = Flask(__name__, static_folder=None)
_web_dir = Path(__file__).parent / "web"
_port: int = 0
_API_SCAN_TTL_SECONDS = 60 * 60
_API_MAX_SCAN_RESULTS = 50
_API_DEFAULT_PORT = 51291
_API_DEFAULT_HOST = "127.0.0.1"
_API_ALLOWED_LANGUAGES = {"auto", "nb", "sv", "en", "de", "fr", "es"}
_LOCAL_API_HOSTS = {"127.0.0.1", "localhost", "::1"}

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

_AI_FINANCIAL_MARKERS = (
    "budsjett",
    "finans",
    "financial",
    "monetary",
    "pengebel",
    "penning",
    "money",
    "cost",
    "amount",
    "price",
    "total",
    "budget",
    "revenue",
    "fee",
    "rate",
    "invoice",
)


def _ai_category_is_financial(category: str) -> bool:
    cat = category.replace("🤖", "").strip().casefold()
    return any(marker in cat for marker in _AI_FINANCIAL_MARKERS)


def _append_unique(values: list[str], seen: set[str], value: str) -> None:
    value = str(value or "").strip()
    if not value:
        return
    key = value.casefold()
    if key not in seen:
        seen.add(key)
        values.append(value)


def _financial_values_from_ai_snippet(text: str) -> list[str]:
    """Utled konkrete tallceller fra AI-funn som beskriver en finansiell tabellrad.

    LLM-er returnerer noen ganger hele Markdown-tabellrader, mens DOCX-kilden har
    de samme verdiene som separate Word-tabellceller. Da matcher ikke hele raden.
    """
    if "|" not in text:
        return []
    values: list[str] = []
    seen: set[str] = set()

    try:
        from xlent_scanner.deep_scanner import (  # noqa: PLC0415
            _find_tabular_financial_values,
            _looks_like_financial_amount_cell,
        )
        for finding in _find_tabular_financial_values(text):
            _append_unique(values, seen, str(finding.get("text") or ""))
        for line in text.splitlines():
            if "|" not in line:
                continue
            for cell in line.strip().strip("|").split("|"):
                cell = cell.strip()
                if _looks_like_financial_amount_cell(cell):
                    _append_unique(values, seen, cell)
    except Exception as exc:
        LOGGER.warning("Klarte ikke å utlede finansielle AI-tabellverdier: %s", exc)
    return values


def _ai_findings_from_payload(data: dict) -> list[dict]:
    findings: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for raw in data.get("ai_findings") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        category = str(raw.get("category") or "🤖 AI-funn").strip()
        context = str(raw.get("context") or "").strip()
        key = (text.casefold(), category.casefold(), context.casefold())
        if key in seen:
            continue
        seen.add(key)
        findings.append({"text": text, "category": category, "context": context})

    # Bakoverkompatibel fallback for eldre frontend-kall.
    for text in data.get("ai_texts") or []:
        text = str(text or "").strip()
        if not text:
            continue
        key = (text.casefold(), "🤖 ai-funn", "")
        if key in seen:
            continue
        seen.add(key)
        findings.append({"text": text, "category": "🤖 AI-funn", "context": ""})

    return findings


def _ai_replacement_texts(ai_findings: list[dict]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for finding in ai_findings:
        text = str(finding.get("text") or "").strip()
        category = str(finding.get("category") or "")
        context = str(finding.get("context") or "").strip()
        _append_unique(values, seen, text)
        if _ai_category_is_financial(category):
            for source in (text, context, f"{context}\n{text}" if context else text):
                for value in _financial_values_from_ai_snippet(source):
                    _append_unique(values, seen, value)
    return values


def _ai_findings_as_model_findings(ai_findings: list[dict]) -> list[Finding]:
    return [
        Finding(
            category=str(f.get("category") or "🤖 AI-funn"),
            text=str(f.get("text") or ""),
            context=str(f.get("context") or ""),
            severity="gul",
            raw_text=str(f.get("text") or ""),
        )
        for f in ai_findings
        if str(f.get("text") or "").strip()
    ]


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
    LOGGER.debug("Serving %s (mtime %.0f)", idx, idx.stat().st_mtime)
    html = idx.read_text("utf-8")
    # Injiser port slik at JS kan bruke absolutte URL-er
    from datetime import datetime  # noqa: PLC0415
    html = html.replace("__API_BASE__", f"http://127.0.0.1:{_port}")
    html = html.replace("__APP_VERSION__", __version__)
    html = html.replace("__APP_STARTED__", datetime.now().strftime("%d.%m.%Y %H:%M"))
    html = html.replace('"__LOG_PATH__"', json.dumps(str(LOG_PATH)))
    html = html.replace('"__APP_PLATFORM__"', json.dumps(sys.platform))
    return html, 200, {"Content-Type": "text/html; charset=utf-8", **_NO_CACHE}


def _open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _download_update_script(url: str, name: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc.endswith("github.com"):
        raise RuntimeError("Ugyldig GitHub asset-URL for installasjonsscript.")
    if name not in {"install_windows.ps1", "install_macos.sh"}:
        raise RuntimeError(f"Uventet installasjonsscript: {name}")

    updates_dir = app_data_dir() / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    out = updates_dir / name

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "xlent-scanner-install-script"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError("Nedlastet installasjonsscript var tomt.")
    out.write_bytes(data)
    return out


def _launch_update_script(script_path: Path) -> subprocess.Popen:
    if sys.platform.startswith("win"):
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
        return subprocess.Popen(cmd, cwd=str(script_path.parent))

    if sys.platform == "darwin":
        script_path.chmod(script_path.stat().st_mode | 0o755)
        quoted = str(script_path).replace("\\", "\\\\").replace('"', '\\"')
        # Terminal gjør installasjonen synlig, inkludert eventuelle macOS-prompter.
        return subprocess.Popen([
            "osascript",
            "-e",
            f'tell application "Terminal" to do script "/bin/bash \\"{quoted}\\""',
        ])

    raise RuntimeError("Automatisk installasjonsscript støttes bare på Windows og macOS.")


def _mac_app_binary_path() -> Path:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if exe.name == "XLENTScanner" and exe.parent.name == "MacOS":
            return exe
    return Path("/Applications/XLENTScanner.app/Contents/MacOS/XLENTScanner")


def _mac_app_bundle_path() -> Path:
    binary = _mac_app_binary_path()
    if binary.name == "XLENTScanner" and binary.parent.name == "MacOS":
        return binary.parents[2]
    return Path("/Applications/XLENTScanner.app")


def _install_mac_quick_action() -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("Finder Quick Action kan bare installeres på macOS.")

    app_path = _mac_app_bundle_path()
    binary = app_path / "Contents" / "MacOS" / "XLENTScanner"
    if not binary.exists():
        raise RuntimeError(f"Fant ikke XLENTScanner-binær på: {binary}")

    service_dir = Path.home() / "Library" / "Services"
    service_path = service_dir / "Skann med XLENT.workflow"
    contents_dir = service_path / "Contents"
    contents_dir.mkdir(parents=True, exist_ok=True)

    app_binary_xml = html.escape(str(binary), quote=True)
    runner_script = contents_dir / "run_xlent_scanner.sh"
    runner_script_xml = html.escape(str(runner_script), quote=True)
    (contents_dir / "Info.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key>
      <dict>
        <key>default</key>
        <string>Skann med XLENT</string>
      </dict>
      <key>NSMessage</key>
      <string>runWorkflow</string>
      <key>NSRequiredContext</key>
      <dict>
        <key>NSApplicationIdentifier</key>
        <string>com.apple.finder</string>
      </dict>
      <key>NSSendFileTypes</key>
      <array>
        <string>public.item</string>
        <string>public.content</string>
        <string>public.data</string>
        <string>public.file-url</string>
      </array>
    </dict>
  </array>
</dict>
</plist>
""",
        encoding="utf-8",
    )

    runner_script.write_text(
        """#!/bin/bash
set -u

LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="${LOG_DIR}/XLENTScannerQuickAction.log"
APP_BINARY="${XLENT_SCANNER_APP_BINARY:-/Applications/XLENTScanner.app/Contents/MacOS/XLENTScanner}"

mkdir -p "${LOG_DIR}"

{
  echo "---- $(date '+%Y-%m-%d %H:%M:%S') ----"
  echo "user=$(id -un 2>/dev/null || echo unknown)"
  echo "pwd=$(pwd)"
  echo "app_binary=${APP_BINARY}"
  echo "arg_count=$#"

  if [[ ! -x "${APP_BINARY}" ]]; then
    echo "error=app_binary_not_executable"
    exit 1
  fi

  if [[ "$#" -eq 0 ]]; then
    echo "error=no_input_files"
    exit 0
  fi

  for f in "$@"; do
    echo "input=${f}"
    if [[ ! -e "${f}" ]]; then
      echo "warning=input_missing path=${f}"
      continue
    fi
    "${APP_BINARY}" "${f}" >>"${LOG_FILE}" 2>&1 &
    echo "started pid=$! path=${f}"
  done
} >>"${LOG_FILE}" 2>&1
""",
        encoding="utf-8",
    )
    runner_script.chmod(0o755)

    (contents_dir / "document.wflow").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>AMApplicationBuild</key><string>521.1</string>
  <key>AMApplicationVersion</key><string>2.10</string>
  <key>AMDocumentVersion</key><string>2</string>
  <key>actions</key>
  <array>
    <dict>
      <key>action</key>
      <dict>
        <key>AMAccepts</key>
        <dict>
          <key>Container</key><string>List</string>
          <key>Optional</key><true/>
          <key>Types</key>
          <array>
            <string>com.apple.cocoa.path</string>
            <string>public.file-url</string>
            <string>public.item</string>
            <string>public.content</string>
            <string>public.data</string>
          </array>
        </dict>
        <key>AMActionVersion</key><string>2.0.3</string>
        <key>AMApplication</key><array><string>Automator</string></array>
        <key>AMParameterProperties</key>
        <dict>
          <key>COMMAND_STRING</key><dict/>
          <key>CheckedForUserDefaultShell</key><dict/>
          <key>inputMethod</key><dict/>
          <key>shell</key><dict/>
          <key>source</key><dict/>
        </dict>
        <key>AMProvides</key>
        <dict>
          <key>Container</key><string>List</string>
          <key>Types</key>
          <array>
            <string>com.apple.cocoa.path</string>
            <string>public.file-url</string>
            <string>public.item</string>
            <string>public.content</string>
            <string>public.data</string>
          </array>
        </dict>
        <key>ActionBundlePath</key><string>/System/Library/Automator/Run Shell Script.action</string>
        <key>ActionName</key><string>Run Shell Script</string>
        <key>ActionParameters</key>
        <dict>
          <key>COMMAND_STRING</key>
          <string>XLENT_SCANNER_APP_BINARY="{app_binary_xml}" "{runner_script_xml}" "$@"</string>
          <key>CheckedForUserDefaultShell</key><true/>
          <key>inputMethod</key><integer>1</integer>
          <key>shell</key><string>/bin/bash</string>
          <key>source</key><string></string>
        </dict>
        <key>BundleIdentifier</key><string>com.apple.RunShellScript</string>
        <key>CFBundleVersion</key><string>2.0.3</string>
        <key>CanShowSelectedItemsWhenRun</key><false/>
        <key>CanShowWhenRun</key><true/>
        <key>Category</key><array><string>AMCategoryUtilities</string></array>
        <key>Class Name</key><string>RunShellScriptAction</string>
        <key>InputUUID</key><string>00000000-0000-0000-0000-000000000001</string>
        <key>Keywords</key><array><string>Shell</string><string>Script</string><string>Command</string></array>
        <key>OutputUUID</key><string>00000000-0000-0000-0000-000000000002</string>
        <key>UUID</key><string>00000000-0000-0000-0000-000000000003</string>
        <key>UnlocalizedApplications</key><array><string>Automator</string></array>
        <key>arguments</key>
        <dict>
          <key>0</key>
          <dict>
            <key>default value</key><integer>0</integer>
            <key>name</key><string>inputMethod</string>
            <key>required</key><string>0</string>
            <key>type</key><string>0</string>
            <key>uuid</key><string>0</string>
          </dict>
        </dict>
        <key>isViewVisible</key><true/>
        <key>location</key><string>321.000000:253.000000</string>
        <key>nibPath</key><string>/System/Library/Automator/Run Shell Script.action/Contents/Resources/English.lproj/main.nib</string>
      </dict>
      <key>isViewVisible</key><true/>
    </dict>
  </array>
  <key>connectors</key><dict/>
  <key>workflowMetaData</key>
  <dict>
    <key>serviceInputTypeIdentifier</key><string>com.apple.Automator.fileSystemObject</string>
    <key>serviceOutputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
    <key>serviceProcessesInput</key><integer>1</integer>
    <key>workflowTypeIdentifier</key><string>com.apple.Automator.workflow</string>
  </dict>
</dict>
</plist>
""",
        encoding="utf-8",
    )

    subprocess.run(["/System/Library/CoreServices/pbs", "-flush"], check=False)
    subprocess.run(["killall", "Finder"], check=False)
    return service_path


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
            "warning_code": None,
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
            "warning_code": None,
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


# ── Stabilt API-lag for eksterne frontender / Power Apps ─────────────────────
# Disse endepunktene er additive og bruker separat scan-state. De skal ikke sette
# _last_result/_last_path, siden det ville påvirket eksisterende desktop/web-GUI.

def _api_max_file_bytes() -> int:
    raw = os.environ.get("XLENT_SCANNER_API_MAX_FILE_MB", "25").strip()
    try:
        mb = max(1, int(raw))
    except ValueError:
        mb = 25
    return mb * 1024 * 1024


def _api_key_configured() -> bool:
    return bool(os.environ.get("XLENT_SCANNER_API_KEY", "").strip())


def _is_local_host(host: str) -> bool:
    return host.strip().lower() in _LOCAL_API_HOSTS


def _validate_api_bind(host: str) -> None:
    if _is_local_host(host) or _api_key_configured():
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
        raise ValueError(
            "Ugyldig språk. Bruk auto, nb, sv, en, de, fr eller es."
        )
    return lang


def _api_cleanup_locked(now: float) -> None:
    expired = [
        scan_id for scan_id, entry in _api_scan_results.items()
        if now - float(entry.get("created_at", 0)) > _API_SCAN_TTL_SECONDS
    ]
    for scan_id in expired:
        _api_delete_scan_locked(scan_id)

    while len(_api_scan_results) > _API_MAX_SCAN_RESULTS:
        oldest = min(
            _api_scan_results,
            key=lambda sid: float(_api_scan_results[sid].get("created_at", 0)),
        )
        _api_delete_scan_locked(oldest)


def _api_delete_scan_locked(scan_id: str) -> None:
    entry = _api_scan_results.pop(scan_id, None)
    if not entry:
        return
    path = entry.get("path")
    if entry.get("owns_path") and isinstance(path, Path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _api_store_scan_result(result, path: Path | None = None, owns_path: bool = False) -> str:
    scan_id = str(uuid.uuid4())
    now = time.time()
    with _api_scan_lock:
        _api_cleanup_locked(now)
        _api_scan_results[scan_id] = {
            "result": result,
            "path": path,
            "owns_path": owns_path,
            "created_at": now,
        }
    return scan_id


def _api_get_scan(scan_id: str) -> dict | None:
    now = time.time()
    with _api_scan_lock:
        _api_cleanup_locked(now)
        return _api_scan_results.get(scan_id)


def _api_result_payload(result, scan_id: str, include_preview: bool = False) -> dict:
    payload = {
        "ok": not bool(result.error),
        "scan_id": scan_id,
        "file_name": result.file_name,
        "file_size": result.file_size,
        "text_length": result.text_length,
        "risk_level": result.risk_level,
        "risk_summary": result.risk_summary,
        "recommended_action": result.recommended_action,
        "language": result.language,
        "warning": result.warning,
        "warning_code": getattr(result, "warning_code", None),
        "error": result.error,
        "findings": [
            {
                "category": f.category,
                "text": f.text,
                "context": f.context,
                "severity": f.severity,
            }
            for f in result.findings
        ],
    }
    if include_preview:
        payload["text_preview"] = result.text_preview
    return payload


@flask_app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "ok": True,
        "service": "xlent-scanner",
        "version": __version__,
        "api_key_configured": _api_key_configured(),
        "max_file_mb": _api_max_file_bytes() // (1024 * 1024),
    })


@flask_app.route("/api/version", methods=["GET"])
def api_version():
    return jsonify({"ok": True, "version": __version__})


def _api_openapi_spec() -> dict:
    base_url = request.url_root.rstrip("/")
    error_schema = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "example": False},
            "error": {"type": "string"},
            "error_code": {"type": "string"},
        },
        "required": ["ok", "error"],
    }
    finding_schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "example": "e-post"},
            "text": {"type": "string", "example": "masked@example.com"},
            "context": {"type": "string"},
            "severity": {"type": "string", "enum": ["grønn", "gul", "rød", "svart"]},
        },
    }
    scan_result_schema = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "scan_id": {"type": "string", "format": "uuid"},
            "file_name": {"type": "string"},
            "file_size": {"type": "integer"},
            "text_length": {"type": "integer"},
            "risk_level": {"type": "string", "enum": ["grønn", "gul", "rød", "svart"]},
            "risk_summary": {"type": "string"},
            "recommended_action": {"type": "string"},
            "language": {"type": "string"},
            "warning": {"type": "string", "nullable": True},
            "error": {"type": "string", "nullable": True},
            "findings": {"type": "array", "items": finding_schema},
            "text_preview": {"type": "string"},
        },
        "required": ["ok", "scan_id", "file_name", "findings"],
    }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "XLENT Scanner API",
            "version": __version__,
            "description": (
                "Stabilt lokalt API for XLENT Compliance-scanner. "
                "Dokumentinnhold returneres ikke i API-responsene."
            ),
        },
        "servers": [{"url": base_url, "description": "Denne lokale app-instansen"}],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                    "description": "Påkrevd når XLENT_SCANNER_API_KEY er satt.",
                },
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Alternativ til X-API-Key når XLENT_SCANNER_API_KEY er satt.",
                },
            },
            "schemas": {
                "Finding": finding_schema,
                "ScanResult": scan_result_schema,
                "Error": error_schema,
            },
        },
        "paths": {
            "/api/health": {
                "get": {
                    "summary": "Sjekk API-status",
                    "responses": {
                        "200": {
                            "description": "API er tilgjengelig",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/api/version": {
                "get": {
                    "summary": "Hent appversjon",
                    "responses": {
                        "200": {
                            "description": "Versjonsinformasjon",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/api/scan-text": {
                "post": {
                    "summary": "Skann tekst",
                    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["text"],
                                    "properties": {
                                        "text": {"type": "string"},
                                        "language": {
                                            "type": "string",
                                            "enum": ["auto", "nb", "sv", "en", "de", "fr", "es"],
                                            "default": "auto",
                                        },
                                        "include_preview": {"type": "boolean", "default": False},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Scan-resultat", "content": {"application/json": {"schema": scan_result_schema}}},
                        "400": {"description": "Ugyldig forespørsel", "content": {"application/json": {"schema": error_schema}}},
                        "401": {"description": "Ugyldig API-nøkkel", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/api/scan-file": {
                "post": {
                    "summary": "Skann fil som base64",
                    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file_name", "content_base64"],
                                    "properties": {
                                        "file_name": {"type": "string", "example": "document.docx"},
                                        "content_base64": {"type": "string", "format": "byte"},
                                        "language": {
                                            "type": "string",
                                            "enum": ["auto", "nb", "sv", "en", "de", "fr", "es"],
                                            "default": "auto",
                                        },
                                        "ignore_xlent": {"type": "boolean", "default": False},
                                        "include_preview": {"type": "boolean", "default": False},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Scan-resultat", "content": {"application/json": {"schema": scan_result_schema}}},
                        "400": {"description": "Ugyldig forespørsel", "content": {"application/json": {"schema": error_schema}}},
                        "401": {"description": "Ugyldig API-nøkkel", "content": {"application/json": {"schema": error_schema}}},
                        "413": {"description": "Filen er for stor", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/api/scans/{scan_id}": {
                "get": {
                    "summary": "Hent cached scan-resultat",
                    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
                    "parameters": [
                        {"name": "scan_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "include_preview", "in": "query", "required": False, "schema": {"type": "boolean"}},
                    ],
                    "responses": {
                        "200": {"description": "Scan-resultat", "content": {"application/json": {"schema": scan_result_schema}}},
                        "404": {"description": "Ukjent eller utløpt scan_id", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/api/deep-scan": {
                "post": {
                    "summary": "Start lokal AI-dybdeskann for et scan-resultat",
                    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["scan_id", "model"],
                                    "properties": {
                                        "scan_id": {"type": "string"},
                                        "model": {"type": "string", "example": "llama3.2:3b"},
                                        "categories": {"type": "array", "items": {"type": "string"}},
                                        "min_confidence": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Dybdeskann startet", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel", "content": {"application/json": {"schema": error_schema}}},
                        "404": {"description": "Ukjent scan_id", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/api/deep-scan/{job_id}": {
                "get": {
                    "summary": "Hent status/resultat for AI-dybdeskann",
                    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
                    "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Jobbstatus", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "404": {"description": "Ukjent job_id", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/api/deep-scan/{job_id}/cancel": {
                "post": {
                    "summary": "Avbryt AI-dybdeskann",
                    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
                    "parameters": [{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Kansellert", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "404": {"description": "Ukjent job_id", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
        },
    }


@flask_app.route("/api/openapi.json", methods=["GET"])
def api_openapi_json():
    return jsonify(_api_openapi_spec())


@flask_app.route("/api/docs", methods=["GET"])
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


@flask_app.route("/api/scan-text", methods=["POST"])
def api_scan_text():
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error

    try:
        data = _api_json_body()
        text = str(data.get("text") or "")
        if not text.strip():
            return jsonify({"ok": False, "error": "Mangler tekst.", "error_code": "missing_text"}), 400
        language = _api_language(data.get("language"))
        include_preview = _api_bool(data.get("include_preview"), False)

        result = scan_text(text, language=language, source_name="Power Apps tekst")
        scan_id = _api_store_scan_result(result)
        return jsonify(_api_result_payload(result, scan_id, include_preview=include_preview))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "error_code": "bad_request"}), 400
    except Exception as exc:
        LOGGER.error("api/scan-text failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc), "error_code": "scan_failed"}), 500


@flask_app.route("/api/scan-file", methods=["POST"])
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

        max_bytes = _api_max_file_bytes()
        if len(raw) > max_bytes:
            return jsonify({
                "ok": False,
                "error": f"Filen er for stor. Maks er {max_bytes // (1024 * 1024)} MB.",
                "error_code": "file_too_large",
            }), 413

        language = _api_language(data.get("language"))
        ignore_xlent = _api_bool(data.get("ignore_xlent"), False)
        include_preview = _api_bool(data.get("include_preview"), False)

        suffix = Path(file_name).suffix.lower() or ".txt"
        fd, tmp = tempfile.mkstemp(prefix="xlent-api-", suffix=suffix)
        tmp_path = Path(tmp)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)

        result = scan_file(tmp_path, ignore_xlent=ignore_xlent, language=language)
        result.file_name = file_name
        scan_id = _api_store_scan_result(result, path=tmp_path, owns_path=True)
        tmp_path = None  # Eies nå av API-cache og ryddes derfra.
        return jsonify(_api_result_payload(result, scan_id, include_preview=include_preview))
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


@flask_app.route("/api/scans/<scan_id>", methods=["GET"])
def api_get_scan_result(scan_id: str):
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error

    entry = _api_get_scan(scan_id)
    if not entry:
        return jsonify({"ok": False, "error": "Ukjent eller utløpt scan_id.", "error_code": "not_found"}), 404
    include_preview = _api_bool(request.args.get("include_preview"), False)
    return jsonify(_api_result_payload(entry["result"], scan_id, include_preview=include_preview))


@flask_app.route("/api/deep-scan", methods=["POST"])
def api_deep_scan():
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error

    try:
        from xlent_scanner.deep_scanner import start_deep_scan  # noqa: PLC0415

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

        min_confidence = str(data.get("min_confidence") or "medium").strip().lower()
        if min_confidence not in {"high", "medium", "low"}:
            min_confidence = "medium"
        categories = data.get("categories") or None
        if categories is not None and not isinstance(categories, list):
            return jsonify({"ok": False, "error": "categories må være en liste.", "error_code": "bad_request"}), 400
        lang = getattr(result, "language", "nb") or "nb"

        job_id = start_deep_scan(text, model, lang, categories=categories, min_confidence=min_confidence)
        return jsonify({"ok": True, "job_id": job_id, "scan_id": scan_id})
    except Exception as exc:
        LOGGER.error("api/deep-scan failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc), "error_code": "deep_scan_failed"}), 500


@flask_app.route("/api/deep-scan/<job_id>", methods=["GET"])
def api_deep_scan_status(job_id: str):
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error

    from xlent_scanner.deep_scanner import get_deep_scan_status  # noqa: PLC0415

    status = get_deep_scan_status(job_id)
    if not status:
        return jsonify({"ok": False, "error": "Ukjent job_id.", "error_code": "not_found"}), 404
    status["ok"] = True
    return jsonify(status)


@flask_app.route("/api/deep-scan/<job_id>/cancel", methods=["POST"])
def api_deep_scan_cancel(job_id: str):
    auth_error = _api_auth_error()
    if auth_error:
        return auth_error

    from xlent_scanner.deep_scanner import cancel_deep_scan, get_deep_scan_status  # noqa: PLC0415

    status = get_deep_scan_status(job_id)
    if not status:
        return jsonify({"ok": False, "error": "Ukjent job_id.", "error_code": "not_found"}), 404
    cancel_deep_scan(job_id)
    return jsonify({"ok": True, "job_id": job_id, "status": "cancelled"})


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
    selected = [
        _last_result.findings[i]
        for i in indices
        if isinstance(i, int) and 0 <= i < len(_last_result.findings)
    ]
    selected.extend(_ai_findings_as_model_findings(_ai_findings_from_payload(data)))
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
            return jsonify({
                "error": "PDF-generering feilet. Se loggfil for tekniske detaljer.",
                "error_code": "pdfGenerateFailed",
            })
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
    strip_annotations = bool(data.get("strip_annotations", False))
    selected = [
        _last_result.findings[i]
        for i in indices
        if isinstance(i, int) and 0 <= i < len(_last_result.findings)
    ]
    ai_findings = _ai_findings_from_payload(data)
    selected.extend(_ai_findings_as_model_findings(ai_findings))
    replacements = build_replacements(selected)
    for text in _ai_replacement_texts(ai_findings):
        replacements.setdefault(text, "[ANONYMISERT]")
    if not replacements and not strip_annotations:
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
        patch_file(_last_path, replacements, out, strip_annotations=strip_annotations)
    except Exception as exc:
        LOGGER.error("patch failed suffix=%s path=%s: %s", suffix, _last_path, traceback.format_exc())
        if suffix == ".pdf":
            return jsonify({
                "error": "PDF-anonymisering feilet. Prøv PDF-rapport eller kontakt support med loggfil.",
                "error_code": "pdfPatchFailed",
            })
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


@flask_app.route("/updates/install-script/run", methods=["POST"])
def update_install_script_run():
    """Last ned og start plattformens installasjonsscript fra latest GitHub release."""
    try:
        script_info = fetch_platform_install_script()
        script_path = _download_update_script(
            script_info["script_url"],
            script_info["script_name"],
        )
        proc = _launch_update_script(script_path)
        LOGGER.info(
            "update install script started name=%s version=%s path=%s pid=%s",
            script_info["script_name"],
            script_info["latest_version"],
            script_path,
            proc.pid,
        )
        return jsonify({
            "ok": True,
            "latest_version": script_info["latest_version"],
            "release_url": script_info["release_url"],
            "script_name": script_info["script_name"],
            "script_path": str(script_path),
            "pid": proc.pid,
        })
    except Exception as exc:
        LOGGER.error("updates/install-script/run failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@flask_app.route("/web-mode/start", methods=["POST"])
def web_mode_start():
    """Start web-modus i separat prosess fra desktop-GUI."""
    try:
        proc = _launch_web_mode_process()
        return jsonify({"ok": True, "pid": proc.pid})
    except Exception as exc:
        LOGGER.error("web-mode/start failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@flask_app.route("/mac/quick-action/install", methods=["POST"])
def mac_quick_action_install():
    try:
        service_path = _install_mac_quick_action()
        LOGGER.info("mac quick action installed path=%s", service_path)
        return jsonify({"ok": True, "path": str(service_path)})
    except Exception as exc:
        LOGGER.error("mac quick action install failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@flask_app.route("/logs/get", methods=["GET"])
def logs_get():
    try:
        max_bytes = int(request.args.get("max_bytes", "50000"))
        max_bytes = max(1000, min(max_bytes, 500000))
        if not LOG_PATH.exists():
            return jsonify({"ok": True, "path": str(LOG_PATH), "text": ""})
        data = LOG_PATH.read_bytes()
        text = data[-max_bytes:].decode("utf-8", errors="replace")
        return jsonify({"ok": True, "path": str(LOG_PATH), "text": text})
    except Exception as exc:
        LOGGER.error("logs/get failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


@flask_app.route("/logs/open", methods=["POST"])
def logs_open():
    try:
        _open_path(LOG_PATH)
        return jsonify({"ok": True, "path": str(LOG_PATH)})
    except Exception as exc:
        LOGGER.error("logs/open failed: %s", traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)})


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


@flask_app.route("/blacklist/get", methods=["POST"])
def blacklist_get():
    return jsonify({
        "ok": True,
        "path": blacklist_path_str(),
        "texts": get_blacklist_entries(),
    })


@flask_app.route("/blacklist/save", methods=["POST"])
def blacklist_save():
    data = request.get_json(force=True)
    texts = data.get("texts", [])
    if not isinstance(texts, list):
        return jsonify({"ok": False, "error": "Ugyldig format for blacklist."})
    save_blacklist_entries([str(t) for t in texts])
    return jsonify({
        "ok": True,
        "path": blacklist_path_str(),
        "texts": get_blacklist_entries(),
    })


@flask_app.route("/settings/export", methods=["POST"])
def settings_export():
    """Eksporter lokale brukerinnstillinger uten dokument- eller scan-data."""
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
    })


@flask_app.route("/settings/import", methods=["POST"])
def settings_import():
    """Importer lokale brukerinnstillinger. Validerer ignore.toml før lagring."""
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict) or data.get("format") != "xlent-scanner-settings":
            return jsonify({"ok": False, "error": "Ugyldig innstillingsfil."})

        whitelist = data.get("whitelist", [])
        if whitelist is not None:
            if not isinstance(whitelist, list):
                return jsonify({"ok": False, "error": "whitelist må være en liste."})
            save_whitelist_entries([str(t) for t in whitelist])

        blacklist = data.get("blacklist", [])
        if blacklist is not None:
            if not isinstance(blacklist, list):
                return jsonify({"ok": False, "error": "blacklist må være en liste."})
            save_blacklist_entries([str(t) for t in blacklist])

        ignore_toml = data.get("ignore_toml")
        if ignore_toml is not None:
            if not isinstance(ignore_toml, str):
                return jsonify({"ok": False, "error": "ignore_toml må være tekst."})
            save_ignore_toml_text(ignore_toml)
            reset_ignore_cache()

        browser_settings = data.get("browser_settings")
        if not isinstance(browser_settings, dict):
            browser_settings = {}

        return jsonify({
            "ok": True,
            "browser_settings": browser_settings,
            "whitelist": get_whitelist_entries(),
            "blacklist": get_blacklist_entries(),
            "ignore_toml": get_ignore_toml_text(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})



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


@flask_app.route("/ollama/model/stop", methods=["POST"])
def ollama_model_stop_endpoint():
    """Last ut valgt Ollama-modell uten å stoppe Ollama-tjenesten."""
    from xlent_scanner.deep_scanner import stop_ollama_model  # noqa: PLC0415

    data = request.get_json(force=True) or {}
    model = (data.get("model") or "").strip()
    result = stop_ollama_model(model)
    LOGGER.info("ollama/model/stop model=%s ok=%s", model, result.get("ok"))
    return jsonify(result)


@flask_app.route("/ollama/model/pull", methods=["POST"])
def ollama_model_pull_endpoint():
    """Last ned anbefalt Ollama-modell via lokal Ollama-tjeneste."""
    from xlent_scanner.deep_scanner import pull_ollama_model  # noqa: PLC0415

    data = request.get_json(force=True) or {}
    model = (data.get("model") or "").strip() or None
    result = pull_ollama_model(model)
    LOGGER.info("ollama/model/pull model=%s ok=%s", model, result.get("ok"))
    return jsonify(result)


@flask_app.route("/ollama/model/pull/status", methods=["GET"])
def ollama_model_pull_status_endpoint():
    from xlent_scanner.deep_scanner import get_ollama_pull_status  # noqa: PLC0415

    status = get_ollama_pull_status()
    status["ok"] = True
    return jsonify(status)


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
    ai_findings = _ai_findings_from_payload(data)
    for text in _ai_replacement_texts(ai_findings):
        if text not in texts_to_remove:
            texts_to_remove.append(text)
    strip_annotations = bool(data.get("strip_annotations", False))
    if not texts_to_remove:
        return jsonify({"error": "Ingen tekst valgt for anonymisering."})

    stem = Path(_last_result.file_name).stem if _last_result.file_name else "dokument"
    suffix = _last_path.suffix.lower() if _last_path else ""
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"

    # Bruk patch_file for støttede filformater når kildefilen er tilgjengelig
    if _last_path and _last_path.exists() and suffix in SUPPORTED_PATCH_SUFFIXES:
        if not ai_findings:
            ai_findings = [{"text": t, "category": "🤖 AI-funn", "context": ""} for t in texts_to_remove]
        replacement_texts = _ai_replacement_texts(ai_findings)
        replacements = {t: "[ANONYMISERT]" for t in replacement_texts}
        out = downloads / f"{stem}-ai-anonymisert{suffix}"
        counter = 1
        while out.exists():
            out = downloads / f"{stem}-ai-anonymisert-{counter}{suffix}"
            counter += 1
        try:
            patch_file(_last_path, replacements, out, strip_annotations=strip_annotations)
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


@flask_app.route("/ollama/deep-scan/status/<job_id>", methods=["GET"])
def ollama_deep_scan_status_for_job_endpoint(job_id: str):
    """Hent status / fremdrift / funn for en konkret dybdeskann-jobb."""
    from xlent_scanner.deep_scanner import get_deep_scan_status  # noqa: PLC0415
    status = get_deep_scan_status(job_id)
    if not status:
        return jsonify({"ok": False, "error": "Ukjent job_id."}), 404
    status["ok"] = True
    return jsonify(status)


@flask_app.route("/ollama/deep-scan/cancel", methods=["POST"])
def ollama_deep_scan_cancel_endpoint():
    """Avbryt pågående dybdeskann."""
    from xlent_scanner.deep_scanner import cancel_deep_scan  # noqa: PLC0415
    cancel_deep_scan()
    return jsonify({"ok": True})


@flask_app.route("/ollama/deep-scan/cancel/<job_id>", methods=["POST"])
def ollama_deep_scan_cancel_for_job_endpoint(job_id: str):
    """Avbryt en konkret dybdeskann-jobb."""
    from xlent_scanner.deep_scanner import cancel_deep_scan, get_deep_scan_status  # noqa: PLC0415
    if not get_deep_scan_status(job_id):
        return jsonify({"ok": False, "error": "Ukjent job_id."}), 404
    cancel_deep_scan(job_id)
    return jsonify({"ok": True, "job_id": job_id})


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


def _start_flask(port: int, host: str = "127.0.0.1") -> None:
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    LOGGER.info("Starting Flask on %s:%s", host, port)
    flask_app.run(host=host, port=port, threaded=True, use_reloader=False)


def _web_mode_command() -> list[str]:
    """Kommando for å starte web-modus i ny prosess."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--web"]
    return [sys.executable, "-m", "xlent_scanner.app", "--web"]


def _launch_web_mode_process() -> subprocess.Popen:
    """Start web-modus i separat prosess uten å blokkere desktop-vinduet."""
    cmd = _web_mode_command()
    kwargs: dict = {"close_fds": True}
    if os.name == "nt":
        flags = 0
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _run_web_mode() -> None:
    """Kjør lokal web-modus (Flask + standard nettleser), uten PyWebView."""
    global _port
    _validate_runtime_dependencies()
    _port = _free_port()
    url = f"http://127.0.0.1:{_port}"
    LOGGER.info("Starting WEB mode on %s", url)

    def _open_browser() -> None:
        time.sleep(0.5)
        try:
            webbrowser.open(url)
        except Exception:
            LOGGER.warning("Could not open browser automatically for %s", url)

    threading.Thread(target=_open_browser, daemon=True, name="web-mode-browser").start()
    _start_flask(_port)


def _arg_value(name: str, default: str) -> str:
    try:
        idx = sys.argv.index(name)
    except ValueError:
        return default
    if idx + 1 >= len(sys.argv) or sys.argv[idx + 1].startswith("--"):
        return default
    return sys.argv[idx + 1]


def _startup_file_from_argv(argv: list[str]) -> str | None:
    """Finn filsti sendt fra OS shell/Finder uten å feiltolke macOS -psn_*.

    macOS Finder kan starte bundle-apps med et prosess-serienummer-argument
    som `-psn_0_...`. Ved Finder Open With kan filstien komme senere i argv.
    """
    for arg in argv[1:]:
        if not arg or arg.startswith("--") or arg.startswith("-psn_") or arg.startswith("-"):
            continue
        path_arg = (
            urllib.request.url2pathname(urllib.parse.urlparse(arg).path)
            if arg.startswith("file://")
            else arg
        )
        if Path(path_arg).exists():
            return path_arg
    return None


def _run_api_mode() -> None:
    """Kjør bare lokal API-server for eksterne frontender, uten GUI."""
    global _port
    _validate_runtime_dependencies()
    raw_port = _arg_value("--port", str(_API_DEFAULT_PORT))
    host = _arg_value("--host", _API_DEFAULT_HOST).strip() or _API_DEFAULT_HOST
    try:
        _port = int(raw_port)
    except ValueError:
        raise RuntimeError(f"Ugyldig port: {raw_port!r}") from None
    _validate_api_bind(host)
    LOGGER.info("Starting API mode on http://%s:%s api_key_configured=%s", host, _port, _api_key_configured())
    _start_flask(_port, host=host)


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

    # ── WEB-modus (lokal nettleser, uten desktop-vindu) ────────────────────
    if "--web" in sys.argv:
        _run_web_mode()
        return

    # ── API-modus (lokal REST-server for Power Apps/gateway) ───────────────
    if "--api" in sys.argv:
        _run_api_mode()
        return

    # ── Fil fra OS/Finder/Windows-kontekstmeny ─────────────────────────────
    startup_file = _startup_file_from_argv(sys.argv)
    if startup_file:
        _initial_file = startup_file
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
        background_color="#eef2f6",
    )
    threading.Thread(target=_force_fresh_load, daemon=True).start()
    LOGGER.info("Window created. API base: http://127.0.0.1:%s", _port)
    webview.start(debug=False, storage_path=webview_cache)


if __name__ == "__main__":
    main()
