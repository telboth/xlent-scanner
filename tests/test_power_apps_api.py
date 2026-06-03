from __future__ import annotations

import base64

from xlent_scanner import app as app_module
from xlent_scanner.models import Finding, ScanResult


def _fake_result() -> ScanResult:
    return ScanResult(
        file_name="Power Apps tekst",
        file_size=0,
        text_length=42,
        text_preview="PREVIEW_SECRET_NOT_RETURNED",
        findings=[
            Finding(
                category="e-post",
                text="masked@example.com",
                context="kort kontekst",
                severity="gul",
                raw_text="RAW_SECRET_NOT_RETURNED",
            )
        ],
        risk_level="gul",
        risk_summary="Funn oppdaget",
        recommended_action="Kontroller funnene.",
        original_text="FULL_SECRET_NOT_RETURNED",
        language="nb",
    )


def test_api_scan_text_uses_separate_state_and_omits_original_text(monkeypatch):
    monkeypatch.delenv("XLENT_SCANNER_API_KEY", raising=False)
    monkeypatch.setattr(app_module, "scan_text", lambda *args, **kwargs: _fake_result())
    app_module._api_scan_results.clear()
    sentinel = object()
    app_module._last_result = sentinel

    client = app_module.flask_app.test_client()
    response = client.post("/api/scan-text", json={"text": "test", "language": "nb"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["scan_id"]
    assert "original_text" not in data
    assert "text_preview" not in data
    assert "FULL_SECRET_NOT_RETURNED" not in str(data)
    assert "RAW_SECRET_NOT_RETURNED" not in str(data)
    assert app_module._last_result is sentinel


def test_api_scan_text_requires_key_when_configured(monkeypatch):
    monkeypatch.setenv("XLENT_SCANNER_API_KEY", "secret-key")
    monkeypatch.setattr(app_module, "scan_text", lambda *args, **kwargs: _fake_result())
    app_module._api_scan_results.clear()
    client = app_module.flask_app.test_client()

    missing_key = client.post("/api/scan-text", json={"text": "test"})
    assert missing_key.status_code == 401

    with_key = client.post(
        "/api/scan-text",
        json={"text": "test"},
        headers={"X-API-Key": "secret-key"},
    )
    assert with_key.status_code == 200
    assert with_key.get_json()["ok"] is True


def test_api_scan_file_accepts_base64_and_omits_original_text(monkeypatch):
    monkeypatch.delenv("XLENT_SCANNER_API_KEY", raising=False)
    monkeypatch.setattr(app_module, "scan_file", lambda *args, **kwargs: _fake_result())
    app_module._api_scan_results.clear()
    client = app_module.flask_app.test_client()

    response = client.post(
        "/api/scan-file",
        json={
            "file_name": "kunde.txt",
            "content_base64": base64.b64encode(b"hello").decode("ascii"),
            "language": "nb",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["file_name"] == "kunde.txt"
    assert "original_text" not in data
    assert "FULL_SECRET_NOT_RETURNED" not in str(data)


def test_api_scan_file_rejects_invalid_base64(monkeypatch):
    monkeypatch.delenv("XLENT_SCANNER_API_KEY", raising=False)
    client = app_module.flask_app.test_client()

    response = client.post(
        "/api/scan-file",
        json={"file_name": "kunde.txt", "content_base64": "not base64!!!"},
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_base64"
