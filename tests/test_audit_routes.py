from datetime import datetime, timedelta, timezone
from pathlib import Path

from xlent_scanner import app as app_module
from xlent_scanner import audit_trail
from xlent_scanner.audit_trail import AuditTrail
from xlent_scanner.routes import audit as audit_routes


def test_audit_endpoints_list_verify_and_export(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(audit_trail, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(audit_routes, "_downloads_dir", lambda: tmp_path)
    AuditTrail(tmp_path).record_event(
        "scan_completed",
        document_path=tmp_path / "Kunde Alfa" / "plan.docx",
        scan_mode="standard",
        outcome="success",
        risk_level="grønn",
    )
    client = app_module.flask_app.test_client()

    listing = client.get("/audit/events?path_mode=full").get_json()
    named_listing = client.get("/audit/events?path_mode=name").get_json()
    verification = client.get("/audit/verify").get_json()
    exported = client.post("/audit/export").get_json()

    assert listing["ok"] is True
    assert listing["entries"][0]["event_type"] == "scan_completed"
    assert listing["entries"][0]["document_name"] == "plan.docx"
    expected_path = str((tmp_path / "Kunde Alfa" / "plan.docx").resolve())
    assert listing["entries"][0]["document_path"] == expected_path
    assert named_listing["entries"][0]["document_name"] == "plan.docx"
    assert "document_path" not in named_listing["entries"][0]
    assert listing["integrity"]["ok"] is True
    assert verification["integrity"]["ok"] is True
    assert exported["ok"] is True
    assert Path(exported["path"]).is_file()


def test_audit_events_supports_local_scan_log_filters(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(audit_trail, "app_data_dir", lambda: tmp_path)
    now = datetime.now(timezone.utc)
    trail = AuditTrail(tmp_path)
    trail.record_event(
        "scan_completed",
        document_path=tmp_path / "old.docx",
        scan_mode="standard",
        outcome="success",
        risk_level="grønn",
        occurred_at=(now - timedelta(days=45)).isoformat(),
    )
    trail.record_event(
        "redaction_created",
        document_path=tmp_path / "recent.docx",
        scan_mode="standard",
        outcome="success",
        risk_level="grønn",
        occurred_at=now.isoformat(),
    )
    trail.record_event(
        "ai_scan_completed",
        document_path=tmp_path / "recent.docx",
        scan_mode="ai_deep",
        outcome="partial",
        risk_level="rød",
        occurred_at=now.isoformat(),
    )
    client = app_module.flask_app.test_client()

    response = client.get(
        "/audit/events?event_scope=scans&days=30&scan_mode=ai_deep"
        "&risk_level=r%C3%B8d&outcome=partial&path_mode=name&limit=10000"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert [entry["event_type"] for entry in payload["entries"]] == [
        "ai_scan_completed"
    ]
    assert payload["entries"][0]["document_name"] == "recent.docx"
    assert client.get("/audit/events?days=31").status_code == 400
    assert client.get("/audit/events?event_scope=unknown").status_code == 400
