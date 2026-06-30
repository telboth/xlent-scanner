from __future__ import annotations

from pathlib import Path

from xlent_scanner import app as app_module
from xlent_scanner import clipboard_guard, folder_watch, scanner
from xlent_scanner.detectors import custom_patterns
from xlent_scanner.models import Finding, ScanResult


def test_custom_patterns_are_validated_detected_and_keep_configured_severity(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(custom_patterns, "app_data_dir", lambda: tmp_path)
    custom_patterns.reset_cache()
    content = """\
[[patterns]]
name = "Prosjektkode"
regex = 'PRJ-\\d{4}'
severity = "rød"
ignore_case = true
"""

    custom_patterns.save_custom_patterns_text(content)
    findings = custom_patterns.detect_custom_patterns("Referanse prj-1234 skal bort.")

    assert len(findings) == 1
    assert findings[0].category == "Egendefinert: Prosjektkode"
    assert findings[0].text == "prj-1234"
    assert findings[0].severity == "rød"

    monkeypatch.setattr(scanner, "detect_custom_patterns", custom_patterns.detect_custom_patterns)
    result = scanner.scan_text("Referanse PRJ-1234 skal bort.", language="nb")
    assert result.risk_level == "rød"
    assert any(f.category == "Egendefinert: Prosjektkode" and f.severity == "rød" for f in result.findings)

    custom_patterns.reset_cache()


def test_custom_patterns_reject_invalid_regex(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(custom_patterns, "app_data_dir", lambda: tmp_path)
    custom_patterns.reset_cache()

    try:
        custom_patterns.validate_custom_patterns_text("""\
[[patterns]]
name = "Broken"
regex = '['
severity = "gul"
""")
    except ValueError as exc:
        assert "ugyldig regex" in str(exc)
    else:
        raise AssertionError("invalid regex was accepted")


def test_custom_patterns_test_endpoint_returns_matches():
    client = app_module.flask_app.test_client()

    response = client.post(
        "/custom-patterns/test",
        json={"regex": r"PRJ-\d{4}", "sample": "PRJ-1234 og PRJ-5678", "ignore_case": True},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["match_count"] == 2
    assert data["matches"][0]["text"] == "PRJ-1234"


def test_clipboard_guard_alerts_without_storing_clipboard_text(monkeypatch):
    alerts: list[tuple[str, str]] = []
    guard = clipboard_guard.ClipboardGuard(notifier=lambda title, msg: alerts.append((title, msg)))

    monkeypatch.setattr(
        clipboard_guard,
        "evaluate_clipboard_text",
        lambda text: {
            "risk_level": "rød",
            "finding_count": 2,
            "categories": ["OpenAI API key"],
            "timestamp": 1.0,
        },
    )

    guard._handle_text("secret clipboard content")

    status = guard.status()
    assert alerts
    assert status["recent_alerts"][0]["risk_level"] == "rød"
    assert "secret clipboard content" not in str(status)


def test_folder_watch_snapshot_changes_and_scan_one(monkeypatch, tmp_path: Path):
    good = tmp_path / "kunde.txt"
    tmp = tmp_path / "kunde.tmp"
    unsupported = tmp_path / "archive.zip"
    good.write_text("hello", encoding="utf-8")
    tmp.write_text("skip", encoding="utf-8")
    unsupported.write_text("skip", encoding="utf-8")

    snap = folder_watch.snapshot_folder(tmp_path)
    assert list(snap) == [str(good)]

    good.write_text("hello again", encoding="utf-8")
    changed = folder_watch.changed_paths(snap, folder_watch.snapshot_folder(tmp_path))
    assert changed == [str(good)]

    result = ScanResult(
        file_name="kunde.txt",
        file_size=10,
        text_length=10,
        text_preview="",
        findings=[Finding(category="OpenAI API key", text="maskert", severity="rød")],
        risk_level="rød",
    )
    notifications: list[tuple[str, str]] = []
    history: list[dict] = []

    monkeypatch.setattr(scanner, "scan_file", lambda *args, **kwargs: result)
    monkeypatch.setattr("xlent_scanner.history.add_history_entry", lambda **kwargs: history.append(kwargs))

    watcher = folder_watch.FolderWatcher(notifier=lambda title, msg: notifications.append((title, msg)))
    watcher._scan_one(str(good))

    status = watcher.status()
    assert status["scanned_count"] == 1
    assert status["recent_results"][0]["risk_level"] == "rød"
    assert notifications
    assert history and history[0]["source"] == "watch"


def test_folder_watch_manager_supports_multiple_folders(tmp_path: Path):
    manager = folder_watch.FolderWatchManager(max_folders=3)
    folders = [tmp_path / f"w{i}" for i in range(3)]
    for folder in folders:
        folder.mkdir()
        assert manager.start(str(folder))["ok"] is True

    status = manager.status()
    assert status["running"] is True
    assert len(status["folders"]) == 3

    extra = tmp_path / "extra"
    extra.mkdir()
    assert manager.start(str(extra))["ok"] is False
    assert manager.stop(str(folders[0])) is True
    assert len(manager.status()["folders"]) == 2
    manager.stop()


def test_folder_watcher_restarts_after_old_thread_has_stopped(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    watcher = folder_watch.FolderWatcher()

    assert watcher.start(str(first))["ok"] is True
    old_thread = watcher._thread
    old_stop_event = watcher._stop_event

    assert watcher.start(str(second))["ok"] is True

    assert old_thread is not None
    assert old_stop_event.is_set()
    assert not old_thread.is_alive()
    assert watcher._stop_event is not old_stop_event
    assert watcher.status()["folder"] == str(second)
    watcher.stop()


def test_scan_file_passes_ocr_flag_to_extract_text(monkeypatch, tmp_path: Path):
    doc = tmp_path / "scan.pdf"
    doc.write_bytes(b"%PDF-1.4")
    seen: dict[str, bool] = {}

    def fake_extract_text(path: Path, ocr: bool = False) -> str:
        seen["ocr"] = ocr
        return "Dette er nok tekst til at OCR-testen ikke gir tomt dokument-varsel."

    monkeypatch.setattr(scanner, "extract_text", fake_extract_text)

    result = scanner.scan_file(doc, language="nb", ocr=True)

    assert result.error is None
    assert seen["ocr"] is True


def test_image_files_are_supported_but_need_ocr_to_extract_text(tmp_path: Path):
    image = tmp_path / "scan.png"
    image.write_bytes(b"synthetic image bytes")

    result = scanner.scan_file(image, language="nb")

    assert ".png" in scanner.SUPPORTED_SUFFIXES
    assert result.error is None
    assert result.warning_code == "no_text_extracted"
    assert result.scan_status == "partial"


def test_image_file_ocr_uses_image_extractor(monkeypatch, tmp_path: Path):
    image = tmp_path / "scan.jpg"
    image.write_bytes(b"synthetic image bytes")
    seen: dict[str, bool] = {}
    extracted = (
        "Ola Nordmann står i denne syntetiske bildefilen, og teksten er lang nok "
        "til at OCR-testen ikke gir varsel om lite tekst."
    )

    def fake_extract_text_image(path: Path, ocr: bool = False, pdf_mode: str = "fast") -> str:
        seen["ocr"] = ocr
        return extracted

    monkeypatch.setattr(scanner, "_extract_text_image", fake_extract_text_image)

    result = scanner.scan_file(image, language="nb", ocr=True)

    assert result.error is None
    assert seen["ocr"] is True
    assert result.original_text == extracted


def test_image_file_advanced_scan_uses_docling_pdf_ocr(monkeypatch, tmp_path: Path):
    image = tmp_path / "scan.jpg"
    image.write_bytes(b"synthetic image bytes")
    tmp_pdf = tmp_path / "image-as-pdf.pdf"
    tmp_pdf.write_bytes(b"%PDF-1.4")
    extracted = (
        "Docling OCR fant strukturert tekst i bildefilen, og teksten er lang nok "
        "til at testen ikke gir varsel om lite tekst."
    )
    seen: dict[str, object] = {}

    monkeypatch.setattr(scanner, "_image_to_temp_pdf", lambda path: tmp_pdf)

    def fake_extract_text_pdf(path: Path, ocr: bool = False, pdf_mode: str = "fast") -> str:
        seen["path"] = path
        seen["ocr"] = ocr
        seen["pdf_mode"] = pdf_mode
        return extracted

    def fail_rapidocr(*_args, **_kwargs):
        raise AssertionError("RapidOCR should not be used in advanced image scan mode")

    monkeypatch.setattr(scanner, "_extract_text_pdf", fake_extract_text_pdf)
    monkeypatch.setattr(scanner, "_get_image_ocr_engine", fail_rapidocr)

    result = scanner.scan_file(image, language="nb", pdf_mode="advanced")

    assert result.error is None
    assert result.ocr_used is True
    assert result.original_text == extracted
    assert seen == {"path": tmp_pdf, "ocr": True, "pdf_mode": "advanced"}
    assert result.scan_timings["scan_mode"] == "advanced"


def test_api_scan_file_accepts_ocr_flag(monkeypatch):
    monkeypatch.delenv("XLENT_SCANNER_API_KEY", raising=False)
    seen: dict[str, bool] = {}

    def fake_scan_file(*args, **kwargs):
        seen["ocr"] = kwargs.get("ocr")
        return ScanResult(
            file_name="api.pdf",
            file_size=1,
            text_length=10,
            text_preview="",
            risk_level="grønn",
            risk_summary="OK",
            recommended_action="OK",
        )

    monkeypatch.setattr(app_module, "scan_file", fake_scan_file)
    app_module.app_state.api_scan_results.clear()
    client = app_module.flask_app.test_client()

    response = client.post(
        "/api/scan-file",
        json={
            "file_name": "api.pdf",
            "content_base64": "aGVsbG8=",
            "ocr": True,
        },
    )

    assert response.status_code == 200
    assert seen["ocr"] is True
