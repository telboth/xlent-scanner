from __future__ import annotations

import sys

import pytest

from xlent_scanner import app, scanner
from xlent_scanner.models import ScanResult


def test_missing_file_is_failed(tmp_path):
    result = scanner.scan_file(tmp_path / "missing.pdf")

    assert result.scan_status == "failed"
    assert result.error


def test_empty_text_is_failed():
    result = scanner.scan_text("   ")

    assert result.scan_status == "failed"
    assert result.error


def test_detector_error_marks_scan_partial(monkeypatch):
    monkeypatch.setattr(scanner, "detect_keywords", lambda text: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(scanner, "get_load_error", lambda lang: None)

    result = scanner.scan_text(
        "Dette er en tilstrekkelig lang tekst uten andre relevante funn.",
        language="nb",
    )

    assert result.scan_status == "partial"
    assert any(f.category == "⚠ Detektor-feil" for f in result.findings)


def test_keyboard_interrupt_is_not_swallowed(monkeypatch):
    def interrupt(_text):
        raise KeyboardInterrupt

    monkeypatch.setattr(scanner, "detect_keywords", interrupt)

    with pytest.raises(KeyboardInterrupt):
        scanner.scan_text("Dette er tekst som skal avbrytes.", language="nb")


def test_cli_uses_exit_code_four_for_failed_scan(monkeypatch):
    monkeypatch.setattr(
        app,
        "scan_file",
        lambda *args, **kwargs: ScanResult(
            file_name="missing.pdf",
            file_size=0,
            text_length=0,
            text_preview="",
            error="Fil ikke funnet",
            scan_status="failed",
        ),
    )
    monkeypatch.setattr(sys, "argv", ["xlent-scanner", "--scan", "missing.pdf"])

    with pytest.raises(SystemExit) as exc:
        app._cli_scan()

    assert exc.value.code == 4
