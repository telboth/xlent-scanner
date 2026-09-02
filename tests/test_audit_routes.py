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
