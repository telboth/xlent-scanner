"""Embedded Flask-server + PyWebView-vindu.

Flask kjører i en bakgrunnstråd og eksponerer:
  GET  /          – returnerer index.html med port injisert
  POST /scan      – scanner en fil, returnerer JSON
  POST /open-dialog – åpner OS-filvelger, returnerer valgt sti
"""
from __future__ import annotations

import faulthandler
import html
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import mimetypes
import urllib.parse
import urllib.request
import warnings
import webbrowser
import zipfile
from pathlib import Path

import webview
from flask import Flask, jsonify, request, send_file

from xlent_scanner import __version__
from xlent_scanner.app_state import app_state
from xlent_scanner.blacklist import (
    get_blacklist_entries,
)
from xlent_scanner.paths import app_data_dir
from xlent_scanner.ignore import (
    get_ignore_toml_text,
)
from xlent_scanner.detectors.ner_names import preload_model_async
from xlent_scanner.patch import patch_file
from xlent_scanner.routes.api import (
    api_key_configured as _api_key_configured,
    create_api_blueprint,
    validate_api_bind as _validate_api_bind,
)
from xlent_scanner.routes.background import background_bp
from xlent_scanner.routes.diagnostics import create_diagnostics_blueprint
from xlent_scanner.routes.folders import (
    create_folders_blueprint,
    folder_job_from_request as _folder_job_from_request,
    folder_result_for_report_id as _folder_result_for_report_id,
    folder_result_row as _folder_result_row,  # noqa: F401
)
from xlent_scanner.routes.microsoft import create_microsoft_blueprint
from xlent_scanner.routes.ollama import create_ollama_blueprint
from xlent_scanner.routes.reports import reports_bp
from xlent_scanner.routes.scanning import scanning_bp
from xlent_scanner.routes.settings import settings_bp
from xlent_scanner.scanner import (
    scan_file,
    scan_folder,
    scan_text,
)
from xlent_scanner.scan_categories import SCAN_CATEGORIES
from xlent_scanner.utils import open_path
from xlent_scanner.whitelist import (
    get_whitelist_entries,
)

# Docling gir UserWarning for bilder i PPTX-filer som mangler innebygd bildedata.
# Dette er støy vi ikke kan gjøre noe med – demp det.
warnings.filterwarnings(
    "ignore",
    message="Skipping malformed picture shape",
    category=UserWarning,
    module=r"docling\..+",
)

flask_app = Flask(__name__, static_folder=None)
flask_app.register_blueprint(settings_bp)
flask_app.register_blueprint(background_bp)
flask_app.register_blueprint(scanning_bp)
flask_app.register_blueprint(reports_bp)
_web_dir = Path(__file__).parent / "web"
_API_DEFAULT_PORT = 51291
_API_DEFAULT_HOST = "127.0.0.1"
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
        _ = fitz
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
    html = html.replace("__API_BASE__", f"http://127.0.0.1:{app_state.port}")
    html = html.replace("__APP_VERSION__", __version__)
    html = html.replace("__APP_STARTED__", datetime.now().strftime("%d.%m.%Y %H:%M"))
    html = html.replace('"__LOG_PATH__"', json.dumps(str(LOG_PATH)))
    html = html.replace('"__APP_PLATFORM__"', json.dumps(sys.platform))
    return html, 200, {"Content-Type": "text/html; charset=utf-8", **_NO_CACHE}


def _downloads_dir() -> Path:
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home() / "Desktop"
    return downloads


def _quick_action_log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "XLENTScannerQuickAction.log"


def _quick_action_path() -> Path:
    return Path.home() / "Library" / "Services" / "Skann med XLENT.workflow"


def _health_check() -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    data_dir = app_data_dir()
    downloads = _downloads_dir()
    add("app_data_writable", os.access(str(data_dir), os.W_OK), str(data_dir))
    add("downloads_writable", downloads.exists() and os.access(str(downloads), os.W_OK), str(downloads))
    add("log_file", LOG_PATH.exists(), str(LOG_PATH))

    try:
        import fitz  # noqa: F401, PLC0415
        add("pymupdf", True, "fitz import ok")
    except Exception as exc:
        add("pymupdf", False, str(exc))

    try:
        import docx  # noqa: F401, PLC0415
        add("python_docx", True, "docx import ok")
    except Exception as exc:
        add("python_docx", False, str(exc))

    try:
        import rapidocr  # noqa: F401, PLC0415
        import onnxruntime  # noqa: F401, PLC0415
        image_ocr_ok = True
        image_ocr_detail = "rapidocr + onnxruntime import ok"
    except Exception as exc:
        image_ocr_ok = False
        image_ocr_detail = f"image OCR engine missing: {exc}"

    try:
        from docling.document_converter import DocumentConverter  # noqa: F401, PLC0415
        docling_ok = True
        docling_detail = "docling import ok"
    except Exception as exc:
        docling_ok = False
        docling_detail = f"docling/PDF OCR unavailable: {exc}"

    if image_ocr_ok and docling_ok:
        add("ocr", True, f"{docling_detail}; {image_ocr_detail}")
    elif image_ocr_ok:
        add("ocr", True, f"{image_ocr_detail}; {docling_detail}")
    else:
        add("ocr", False, f"{image_ocr_detail}; {docling_detail}")

    try:
        from xlent_scanner.model_manager import models_status  # noqa: PLC0415
        status = models_status()
        installed = sum(1 for m in status.get("models", []) if m.get("installed"))
        total = len(status.get("models", []))
        add("spacy_models", installed == total and total > 0, f"{installed}/{total} installed")
    except Exception as exc:
        add("spacy_models", False, str(exc))

    try:
        from xlent_scanner.deep_scanner import ollama_status  # noqa: PLC0415
        status = ollama_status()
        models = status.get("models") or []
        add("ollama", bool(status.get("running")) and bool(models), f"running={status.get('running')} models={len(models)}")
    except Exception as exc:
        add("ollama", False, str(exc))

    if sys.platform == "darwin":
        binary = _mac_app_binary_path()
        qa_path = _quick_action_path()
        workflow = qa_path / "Contents" / "document.wflow"
        runner = qa_path / "Contents" / "run_xlent_scanner.sh"
        add("mac_app_binary", binary.exists() and os.access(str(binary), os.X_OK), str(binary))
        add("mac_quick_action", qa_path.exists(), str(qa_path))
        add("mac_quick_action_runner", runner.exists() and os.access(str(runner), os.X_OK), str(runner))
        add("mac_quick_action_workflow", workflow.exists(), str(workflow))
        if runner.exists():
            try:
                runner_text = runner.read_text(encoding="utf-8", errors="replace")
                robust_runner = (
                    "/usr/bin/open -n" in runner_text
                    and "note=no_arguments_trying_stdin" in runner_text
                    and "nohup" in runner_text
                )
                add("mac_quick_action_runner_mode", robust_runner, "open --args with stdin/nohup fallback")
            except Exception as exc:
                add("mac_quick_action_runner_mode", False, str(exc))
        if workflow.exists():
            try:
                workflow_text = workflow.read_text(encoding="utf-8", errors="replace")
                has_runner = "run_xlent_scanner.sh" in workflow_text and '"$@"' in workflow_text
                add("mac_quick_action_command", has_runner, "passes Finder input as shell arguments")
            except Exception as exc:
                add("mac_quick_action_command", False, str(exc))
        qa_log = _quick_action_log_path()
        add("mac_quick_action_log", qa_log.exists(), str(qa_log))
    elif sys.platform.startswith("win"):
        add("windows_context_menu", True, "not validated by health check")

    failed = [c for c in checks if not c["ok"]]
    return {
        "ok": not failed,
        "version": __version__,
        "platform": sys.platform,
        "system": platform.platform(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "app_data_dir": str(data_dir),
        "log_path": str(LOG_PATH),
        "quick_action_log_path": str(_quick_action_log_path()),
        "checks": checks,
    }


def _write_debug_package() -> Path:
    from datetime import datetime  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    out_dir = _downloads_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"xlent-scanner-debug-{stamp}.zip"
    counter = 1
    while out.exists():
        out = out_dir / f"xlent-scanner-debug-{stamp}-{counter}.zip"
        counter += 1

    health = _health_check()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("health.json", _json.dumps(health, ensure_ascii=False, indent=2))
        zf.writestr("version.txt", f"XLENT Scanner {__version__}\n{platform.platform()}\n{sys.executable}\n")

        for label, path in [
            ("logs/app.log", LOG_PATH),
            ("logs/faulthandler.log", LOG_PATH.parent / "faulthandler.log"),
            ("logs/quick-action.log", _quick_action_log_path()),
        ]:
            try:
                if path.exists():
                    zf.write(path, label)
            except Exception as exc:
                zf.writestr(f"{label}.error.txt", str(exc))

        for label, text_getter in [
            ("config/whitelist.txt", lambda: "\n".join(get_whitelist_entries())),
            ("config/blacklist.txt", lambda: "\n".join(get_blacklist_entries())),
            ("config/ignore.toml", get_ignore_toml_text),
        ]:
            try:
                zf.writestr(label, text_getter())
            except Exception as exc:
                zf.writestr(f"{label}.error.txt", str(exc))
    return out


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
    # NSMessage MÅ være «runWorkflowAsService» for Quick Actions — med
    # «runWorkflow» svarer ikke Automator-runneren når menyvalget klikkes.
    (contents_dir / "Info.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSBackgroundColorName</key>
      <string>background</string>
      <key>NSIconName</key>
      <string>NSActionTemplate</string>
      <key>NSMenuItem</key>
      <dict>
        <key>default</key>
        <string>Skann med XLENT</string>
      </dict>
      <key>NSMessage</key>
      <string>runWorkflowAsService</string>
      <key>NSRequiredContext</key>
      <dict>
        <key>NSApplicationIdentifier</key>
        <string>com.apple.finder</string>
      </dict>
      <key>NSSendFileTypes</key>
      <array>
        <string>public.item</string>
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
APP_BUNDLE="${APP_BINARY%/Contents/MacOS/XLENTScanner}"

mkdir -p "${LOG_DIR}"

{
  echo "---- $(date '+%Y-%m-%d %H:%M:%S') ----"
  echo "user=$(id -un 2>/dev/null || echo unknown)"
  echo "pwd=$(pwd)"
  echo "app_binary=${APP_BINARY}"
  echo "app_bundle=${APP_BUNDLE}"
  echo "arg_count=$#"

  if [[ ! -x "${APP_BINARY}" ]]; then
    echo "error=app_binary_not_executable"
    exit 1
  fi

  inputs=("$@")
  if [[ "${#inputs[@]}" -eq 0 ]]; then
    echo "note=no_arguments_trying_stdin"
    while IFS= read -r line; do
      [[ -n "${line}" ]] && inputs+=("${line}")
    done
  fi

  if [[ "${#inputs[@]}" -eq 0 ]]; then
    echo "error=no_input_files"
    exit 0
  fi

  for f in "${inputs[@]}"; do
    echo "input=${f}"
    if [[ "${f}" != file://* && ! -e "${f}" ]]; then
      echo "warning=input_missing path=${f}"
    fi
    if [[ -d "${APP_BUNDLE}" ]]; then
      /usr/bin/open -n "${APP_BUNDLE}" --args "${f}" >>"${LOG_FILE}" 2>&1
      open_status=$?
      echo "open_status=${open_status} path=${f}"
      if [[ "${open_status}" -eq 0 ]]; then
        continue
      fi
    fi
    nohup "${APP_BINARY}" "${f}" </dev/null >>"${LOG_FILE}" 2>&1 &
    echo "started_direct pid=$! path=${f}"
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
    <key>inputTypeIdentifier</key><string>com.apple.Automator.fileSystemObject</string>
    <key>outputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
    <key>presentationMode</key><integer>11</integer>
    <key>processesInput</key><integer>0</integer>
    <key>serviceInputTypeIdentifier</key><string>com.apple.Automator.fileSystemObject</string>
    <key>serviceOutputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
    <key>serviceProcessesInput</key><integer>0</integer>
    <key>systemImageName</key><string>NSActionTemplate</string>
    <key>useAutomaticInputType</key><integer>0</integer>
    <key>workflowTypeIdentifier</key><string>com.apple.Automator.servicesMenu</string>
  </dict>
</dict>
</plist>
""",
        encoding="utf-8",
    )

    subprocess.run(["/System/Library/CoreServices/pbs", "-flush"], check=False)
    subprocess.run(["killall", "Finder"], check=False)
    return service_path


flask_app.register_blueprint(create_folders_blueprint(
    downloads_dir=lambda: _downloads_dir(),
    open_path=lambda path: open_path(path),
    scan_file_fn=lambda *args, **kwargs: scan_file(*args, **kwargs),
    scan_folder_fn=lambda *args, **kwargs: scan_folder(*args, **kwargs),
    patch_file_fn=lambda *args, **kwargs: patch_file(*args, **kwargs),
))

flask_app.register_blueprint(create_microsoft_blueprint(
    folder_job_from_request=_folder_job_from_request,
    folder_result_for_report_id=_folder_result_for_report_id,
))


# ── Stabilt API-lag for eksterne frontender / Power Apps ─────────────────────
# Disse endepunktene er additive og bruker separat scan-state. De skal ikke sette
# app_state.last_result/app_state.last_path, siden det ville påvirket desktop/web-GUI.

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
    suppressed_finding_schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "example": "telefonnummer"},
            "text": {"type": "string", "example": "pp. 4662-4666"},
            "context": {"type": "string"},
            "reason": {"type": "string", "example": "bibliografisk DOI/ISBN/ISSN/sidekontekst"},
            "source": {"type": "string", "example": "Regelbasert"},
        },
    }
    scan_profile_property = {
        "type": "string",
        "enum": ["normal", "technical", "auto"],
        "default": "auto",
        "description": "auto velger normal eller technical basert på tekstsignaler; technical strammer inn postfiltre for tekniske/akademiske dokumenter.",
    }
    scan_categories_property = {
        "type": "array",
        "items": {
            "type": "string",
            "enum": [category.key for category in SCAN_CATEGORIES],
        },
        "description": "Valgte regelbaserte scan-kategorier. Utelat feltet for å skanne alle kategorier.",
    }
    scan_mode_property = {
        "type": "string",
        "enum": ["fast", "auto", "advanced"],
        "default": "auto",
        "description": "Scan-modus: fast=PyMuPDF for PDF/RapidOCR for bilder, auto=Docling ved lite PDF-tekst eller tabell-/layoutsignaler, advanced=Docling for PDF og bildefiler for bedre struktur/layout.",
    }
    pdf_mode_property = {
        **scan_mode_property,
        "description": "Bakoverkompatibelt alias for scan_mode.",
        "deprecated": True,
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
            "scan_status": {"type": "string", "enum": ["success", "partial", "failed"]},
            "risk_summary": {"type": "string"},
            "recommended_action": {"type": "string"},
            "language": {"type": "string"},
            "warning": {"type": "string", "nullable": True},
            "microsoft_tags": {"type": "object"},
            "policy_warning": {"type": "string", "nullable": True},
            "policy_warning_level": {"type": "string", "nullable": True},
            "error": {"type": "string", "nullable": True},
            "scan_timings": {
                "type": "object",
                "description": "Sekunder brukt på ekstraksjon, språkdeteksjon, detektorer og total scan.",
            },
            "findings": {"type": "array", "items": finding_schema},
            "suppressed_findings": {"type": "array", "items": suppressed_finding_schema},
            "text_preview": {"type": "string"},
        },
        "required": ["ok", "scan_id", "file_name", "scan_status", "findings"],
    }
    graph_item_request_schema = {
        "type": "object",
        "required": ["drive_id", "item_id"],
        "properties": {
            "drive_id": {"type": "string"},
            "item_id": {"type": "string"},
        },
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
                "SuppressedFinding": suppressed_finding_schema,
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
            "/microsoft/graph/status": {
                "get": {
                    "summary": "Sjekk Microsoft Graph-konfigurasjon",
                    "responses": {
                        "200": {"description": "Graph-konfigurasjon", "content": {"application/json": {"schema": {"type": "object"}}}},
                    },
                }
            },
            "/microsoft/graph/tags": {
                "post": {
                    "summary": "Les Microsoft 365-labels og SharePoint-felt for et driveItem",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": graph_item_request_schema}}},
                    "responses": {
                        "200": {"description": "Dokumentmerking og policyvarsel", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel eller manglende Graph-token", "content": {"application/json": {"schema": error_schema}}},
                        "502": {"description": "Graph-feil", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/microsoft/graph/resolve-local-file": {
                "post": {
                    "summary": "Map lokal OneDrive/SharePoint-fil til Graph driveItem",
                    "requestBody": {
                        "required": False,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "local_path": {"type": "string"},
                                "drive_id": {"type": "string"},
                                "sync_root": {"type": "string"},
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Graph driveItem funnet", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel eller manglende Graph-konfigurasjon", "content": {"application/json": {"schema": error_schema}}},
                        "502": {"description": "Graph-feil", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/microsoft/graph/tags-for-local-file": {
                "post": {
                    "summary": "Les Microsoft 365-labels for sist skannet eller oppgitt lokal fil",
                    "requestBody": {
                        "required": False,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "local_path": {"type": "string"},
                                "drive_id": {"type": "string"},
                                "sync_root": {"type": "string"},
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Dokumentmerking og policyvarsel", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel eller manglende Graph-konfigurasjon", "content": {"application/json": {"schema": error_schema}}},
                        "502": {"description": "Graph-feil", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/microsoft/graph/assign-sensitivity": {
                "post": {
                    "summary": "Sett Microsoft sensitivity label på et driveItem",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "allOf": [
                                graph_item_request_schema,
                                {"type": "object", "required": ["sensitivity_label_id"], "properties": {
                                    "sensitivity_label_id": {"type": "string"},
                                    "assignment_method": {"type": "string", "default": "standard"},
                                    "justification_text": {"type": "string"},
                                }},
                            ]
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Label-operasjon sendt", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel eller manglende Graph-token", "content": {"application/json": {"schema": error_schema}}},
                        "502": {"description": "Graph-feil", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/microsoft/graph/set-retention": {
                "post": {
                    "summary": "Sett retention label på et driveItem",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "allOf": [
                                graph_item_request_schema,
                                {"type": "object", "required": ["retention_label_name"], "properties": {
                                    "retention_label_name": {"type": "string"},
                                }},
                            ]
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Retention label satt", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel eller manglende Graph-token", "content": {"application/json": {"schema": error_schema}}},
                        "502": {"description": "Graph-feil", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/microsoft/graph/write-scan-metadata": {
                "post": {
                    "summary": "Skriv XLENT scan-metadata til SharePoint-felt",
                    "description": "Krever at feltene finnes i dokumentbiblioteket: XLENTScanStatus, XLENTRiskLevel, XLENTFindingCount, XLENTSuggestedLabel og XLENTLastScanned.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "allOf": [
                                graph_item_request_schema,
                                {"type": "object", "properties": {
                                    "suggested_label": {"type": "string"},
                                    "status": {"type": "string", "default": "Scanned"},
                                    "fields": {"type": "object"},
                                }},
                            ]
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Metadata skrevet", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel, manglende scan eller manglende Graph-token", "content": {"application/json": {"schema": error_schema}}},
                        "502": {"description": "Graph-feil", "content": {"application/json": {"schema": error_schema}}},
                    },
                }
            },
            "/microsoft/graph/write-folder-metadata": {
                "post": {
                    "summary": "Skriv scan-metadata til SharePoint-felt for filer i en mappeskann",
                    "description": "Mapper lokale filer via driveId + sync_root og skriver XLENTScanStatus, XLENTRiskLevel, XLENTFindingCount, XLENTSuggestedLabel og XLENTLastScanned per fil.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "job_id": {"type": "string"},
                                "report_ids": {"type": "array", "items": {"type": "string"}},
                                "drive_id": {"type": "string"},
                                "sync_root": {"type": "string"},
                                "status": {"type": "string", "default": "Scanned"},
                                "fields": {"type": "object"},
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "Batch-resultat per fil", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "400": {"description": "Ugyldig forespørsel eller manglende Graph-konfigurasjon", "content": {"application/json": {"schema": error_schema}}},
                        "502": {"description": "Graph-feil", "content": {"application/json": {"schema": error_schema}}},
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
                                        "scan_profile": scan_profile_property,
                                        "categories": scan_categories_property,
                                        "include_preview": {"type": "boolean", "default": False},
                                        "include_suppressed": {"type": "boolean", "default": False},
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
                                        "scan_profile": scan_profile_property,
                                        "categories": scan_categories_property,
                                        "scan_mode": scan_mode_property,
                                        "pdf_mode": pdf_mode_property,
                                        "ignore_xlent": {"type": "boolean", "default": False},
                                        "ocr": {
                                            "type": "boolean",
                                            "default": False,
                                            "description": "Kjør OCR ved skanning av bildebasert PDF der dette er tilgjengelig.",
                                        },
                                        "include_preview": {"type": "boolean", "default": False},
                                        "include_suppressed": {"type": "boolean", "default": False},
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
                        {"name": "include_suppressed", "in": "query", "required": False, "schema": {"type": "boolean"}},
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


flask_app.register_blueprint(create_api_blueprint(
    scan_text_fn=lambda *args, **kwargs: scan_text(*args, **kwargs),
    scan_file_fn=lambda *args, **kwargs: scan_file(*args, **kwargs),
    openapi_spec_fn=_api_openapi_spec,
))


@flask_app.route("/startup-file", methods=["GET"])
def startup_file():
    """Returnerer filen som ble sendt via OS-kontekstmeny/Finder (sys.argv)."""
    return jsonify({"path": app_state.initial_file})


@flask_app.route("/logo.svg")
def logo_svg():
    logo_dir = app_data_dir() / "logo"
    logo_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        logo_dir / "logo.svg",
        logo_dir / "logo.png",
        logo_dir / "logo.jpg",
        logo_dir / "logo.jpeg",
        logo_dir / "logo.webp",
        Path(__file__).parent / "web" / "logo.svg",
    ]
    logo_path = next((path for path in candidates if path.is_file()), None)
    if logo_path is None:
        return "", 404
    mimetype = mimetypes.guess_type(str(logo_path))[0] or "image/svg+xml"
    response = send_file(logo_path, mimetype=mimetype, max_age=0)
    response.cache_control.no_store = True
    return response


flask_app.register_blueprint(create_ollama_blueprint(
    patch_file_fn=lambda *args, **kwargs: patch_file(*args, **kwargs),
))


def _start_flask(port: int, host: str = "127.0.0.1") -> None:
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    LOGGER.info("Starting Flask on %s:%s", host, port)
    flask_app.run(host=host, port=port, threaded=True, use_reloader=False)


def _start_ner_preload() -> None:
    try:
        preload_model_async("nb")
        LOGGER.info("Started background preload for nb spaCy model")
    except Exception:
        LOGGER.warning("Could not start background NER preload", exc_info=True)


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


flask_app.register_blueprint(create_diagnostics_blueprint(
    log_path=LOG_PATH,
    health_check=_health_check,
    write_debug_package=_write_debug_package,
    download_update_script=_download_update_script,
    launch_update_script=_launch_update_script,
    launch_web_mode_process=_launch_web_mode_process,
    install_mac_quick_action=_install_mac_quick_action,
    open_path=open_path,
))


def _run_web_mode() -> None:
    """Kjør lokal web-modus (Flask + standard nettleser), uten PyWebView."""
    _validate_runtime_dependencies()
    app_state.port = _free_port()
    url = f"http://127.0.0.1:{app_state.port}"
    LOGGER.info("Starting WEB mode on %s", url)
    _start_ner_preload()

    def _open_browser() -> None:
        time.sleep(0.5)
        try:
            webbrowser.open(url)
        except Exception:
            LOGGER.warning("Could not open browser automatically for %s", url)

    threading.Thread(target=_open_browser, daemon=True, name="web-mode-browser").start()
    _start_flask(app_state.port)


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


def _format_startup_file_args(paths: list[str]) -> str:
    return "\n".join(p for p in paths if p)


def _run_api_mode() -> None:
    """Kjør bare lokal API-server for eksterne frontender, uten GUI."""
    _validate_runtime_dependencies()
    raw_port = _arg_value("--port", str(_API_DEFAULT_PORT))
    host = _arg_value("--host", _API_DEFAULT_HOST).strip() or _API_DEFAULT_HOST
    try:
        app_state.port = int(raw_port)
    except ValueError:
        raise RuntimeError(f"Ugyldig port: {raw_port!r}") from None
    _validate_api_bind(host)
    LOGGER.info(
        "Starting API mode on http://%s:%s api_key_configured=%s",
        host,
        app_state.port,
        _api_key_configured(),
    )
    _start_ner_preload()
    _start_flask(app_state.port, host=host)


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

    exit_code = (
        4
        if result.scan_status == "failed"
        else {"grønn": 0, "gul": 1, "rød": 2, "svart": 3}.get(result.risk_level, 0)
    )
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
            s.sendall((_format_startup_file_args([file_path]) + "\n").encode("utf-8"))
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
                    if data and app_state.window:
                        LOGGER.info("IPC: mottok filsti: %s", data)
                        path_js = json.dumps(data)
                        app_state.window.evaluate_js(
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
    # ── CLI-modus ──────────────────────────────────────────────────────────
    if "--scan" in sys.argv:
        _cli_scan()
        return

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
        app_state.initial_file = startup_file
        LOGGER.info("Startup file from argv: %s", app_state.initial_file)
        # Enkel-instans: hvis en instans allerede kjører, send filen dit
        _ipc_send_and_exit(app_state.initial_file)
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

    app_state.port = _free_port()
    t = threading.Thread(target=_start_flask, args=(app_state.port,), daemon=True)
    t.start()
    _wait_for_flask(app_state.port)
    LOGGER.info("Flask is reachable on 127.0.0.1:%s", app_state.port)
    _start_ner_preload()

    webview_cache = tempfile.mkdtemp(prefix="xlent-scanner-wv-")
    fresh_url = f"http://127.0.0.1:{app_state.port}/?_v={int(time.time())}"

    # Etter at vinduet er synlig, tving en reload til en URL med unikt tidsstempel.
    # Dette sikrer at WebView2 alltid gjør en ekte HTTP-forespørsel mot Flask
    # og aldri viser en cachet side – uavhengig av WebView2 sin interne cache-konfigurasjon.
    def _force_fresh_load():
        if app_state.window.events.shown.wait(timeout=10):
            app_state.window.load_url(fresh_url)

    app_state.window = webview.create_window(
        title="XLENT Compliance-scanner",
        url=f"http://127.0.0.1:{app_state.port}",
        width=900,
        height=700,
        min_size=(700, 500),
        background_color="#eef2f6",
    )
    threading.Thread(target=_force_fresh_load, daemon=True).start()
    LOGGER.info("Window created. API base: http://127.0.0.1:%s", app_state.port)
    webview.start(debug=False, storage_path=webview_cache)


if __name__ == "__main__":
    main()
