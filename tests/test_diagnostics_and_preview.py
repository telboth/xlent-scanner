from __future__ import annotations

import zipfile
from pathlib import Path

from xlent_scanner import app as app_module
from xlent_scanner.models import Finding, ScanResult


def _scan_result() -> ScanResult:
    return ScanResult(
        file_name="test.docx",
        file_size=123,
        text_length=42,
        text_preview="preview",
        findings=[
            Finding(
                category="e-post",
                text="person@example.com",
                context="Kontakt person@example.com",
                severity="gul",
                raw_text="person@example.com",
            ),
            Finding(
                category="⚠ system",
                text="warning",
                context="",
                severity="gul",
                raw_text="warning",
            ),
        ],
        risk_level="gul",
        risk_summary="Funn",
        recommended_action="Kontroller",
        original_text="Kontakt person@example.com",
        language="nb",
    )


def test_redaction_preview_uses_same_replacement_logic():
    app_module._last_result = _scan_result()
    app_module._last_path = Path("test.docx")
    client = app_module.flask_app.test_client()

    response = client.post("/redaction/preview", json={"indices": [0]})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["selected_count"] == 1
    assert data["replacement_count"] == 1
    assert data["preview"] == [{"original": "person@example.com", "replacement": "<Epost 1>"}]


def test_diagnostics_health_returns_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module, "_downloads_dir", lambda: tmp_path)
    client = app_module.flask_app.test_client()

    response = client.get("/diagnostics/health")

    assert response.status_code == 200
    data = response.get_json()
    assert "checks" in data
    assert data["version"]
    assert data["app_data_dir"] == str(tmp_path)
    assert any(check["name"] == "ocr" for check in data["checks"])


def test_diagnostics_health_reports_macos_quick_action_details(monkeypatch, tmp_path):
    app_binary = tmp_path / "XLENTScanner"
    app_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    app_binary.chmod(0o755)
    qa_path = tmp_path / "Skann med XLENT.workflow"
    contents = qa_path / "Contents"
    contents.mkdir(parents=True)
    runner = contents / "run_xlent_scanner.sh"
    runner.write_text(
        '#!/bin/bash\nnote=no_arguments_trying_stdin\n/usr/bin/open -n "${APP_BUNDLE}" --args "${f}"\nnohup "${APP_BINARY}" "${f}"\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)
    (contents / "document.wflow").write_text(
        'XLENT_SCANNER_APP_BINARY="/Applications/XLENTScanner.app/Contents/MacOS/XLENTScanner" '
        '"run_xlent_scanner.sh" "$@"',
        encoding="utf-8",
    )
    qa_log = tmp_path / "XLENTScannerQuickAction.log"
    qa_log.write_text("arg_count=1\ninput=/tmp/test.pdf\n", encoding="utf-8")

    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module, "_downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module, "_mac_app_binary_path", lambda: app_binary)
    monkeypatch.setattr(app_module, "_quick_action_path", lambda: qa_path)
    monkeypatch.setattr(app_module, "_quick_action_log_path", lambda: qa_log)

    data = app_module._health_check()
    checks = {check["name"]: check for check in data["checks"]}

    assert checks["mac_app_binary"]["ok"] is True
    assert checks["mac_quick_action"]["ok"] is True
    assert checks["mac_quick_action_runner"]["ok"] is True
    assert checks["mac_quick_action_runner_mode"]["ok"] is True
    assert checks["mac_quick_action_workflow"]["ok"] is True
    assert checks["mac_quick_action_command"]["ok"] is True
    assert checks["mac_quick_action_log"]["ok"] is True


def test_diagnostics_export_writes_package_without_document_text(monkeypatch, tmp_path):
    app_module._last_result = _scan_result()
    monkeypatch.setattr(app_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module, "_downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module, "get_whitelist_entries", lambda: ["safe@example.com"])
    monkeypatch.setattr(app_module, "get_blacklist_entries", lambda: ["always-secret"])
    monkeypatch.setattr(app_module, "get_ignore_toml_text", lambda: "[ignore]\n")
    client = app_module.flask_app.test_client()

    response = client.post("/diagnostics/export")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    zip_path = Path(data["path"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "health.json" in names
        assert "version.txt" in names
        assert "config/whitelist.txt" in names
        combined = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in names
            if not name.endswith(".log")
        )
    assert "Kontakt person@example.com" not in combined
    assert "safe@example.com" in combined


def test_scan_text_clears_previous_ai_findings(monkeypatch):
    app_module._last_ai_findings = [{"category": "🤖 Fødselsnummer", "text": "01019750023", "context": ""}]
    app_module._last_ai_findings_file["name"] = "old.docx"
    monkeypatch.setattr(
        app_module,
        "scan_text",
        lambda text, language="auto": ScanResult(
            file_name="Power Apps tekst",
            file_size=len(text),
            text_length=len(text),
            text_preview=text,
            findings=[],
            risk_level="grønn",
            risk_summary="Ingen funn",
            recommended_action="OK",
            original_text=text,
            language=language,
        ),
    )
    client = app_module.flask_app.test_client()

    response = client.post("/scan-text", json={"text": "Kun ufarlig tekst", "language": "nb"})

    assert response.status_code == 200
    assert app_module._last_ai_findings == []
    assert app_module._last_ai_findings_file["name"] == ""
