from __future__ import annotations

from xlent_scanner import app as app_module
from xlent_scanner import microsoft_graph as graph
from xlent_scanner.models import Finding, ScanResult


def test_read_document_tags_extracts_labels_and_red_policy_warning(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, path: str, body: dict | None = None):
        calls.append((method, path, body))
        if method == "GET" and "?$select=" in path:
            return {"id": "item1", "name": "doc.docx"}
        if method == "POST" and path.endswith("/extractSensitivityLabels"):
            return {"value": [{"sensitivityLabel": {"id": "lbl1", "name": "Highly Confidential"}}]}
        if method == "GET" and path.endswith("/retentionLabel"):
            return {"name": "Retain 7 years"}
        if method == "GET" and path.endswith("/listItem/fields"):
            return {"XLENTScanStatus": "Scanned"}
        raise AssertionError((method, path, body))

    monkeypatch.setattr(graph, "_graph_request", fake_request)

    tags = graph.read_document_tags("drive 1", "item 1")

    assert tags["item"]["name"] == "doc.docx"
    assert tags["sensitivity"]["labels"][0]["name"] == "Highly Confidential"
    assert tags["retention"]["name"] == "Retain 7 years"
    assert tags["policy_warning"]
    assert calls[0][1].startswith("/drives/drive%201/items/item%201")


def test_graph_write_helpers_send_expected_payloads(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, path: str, body: dict | None = None):
        calls.append((method, path, body))
        return {"ok": True}

    monkeypatch.setattr(graph, "_graph_request", fake_request)

    graph.assign_sensitivity_label("drive", "item", "label-id", justification_text="test")
    graph.set_retention_label("drive", "item", "Retain 7 years")
    graph.update_sharepoint_fields("drive", "item", {"XLENTRiskLevel": "rød"})

    assert calls[0] == (
        "POST",
        "/drives/drive/items/item/assignSensitivityLabel",
        {
            "sensitivityLabelId": "label-id",
            "assignmentMethod": "standard",
            "justificationText": "test",
        },
    )
    assert calls[1] == ("PATCH", "/drives/drive/items/item/retentionLabel", {"name": "Retain 7 years"})
    assert calls[2] == ("PATCH", "/drives/drive/items/item/listItem/fields", {"XLENTRiskLevel": "rød"})


def test_scan_metadata_fields_and_suggested_label():
    suggested = graph.suggested_label_for_risk("rød")
    fields = graph.scan_metadata_fields("rød", 3, suggested["name"])

    assert suggested["name"] == "Highly Confidential"
    assert fields["XLENTScanStatus"] == "Scanned"
    assert fields["XLENTRiskLevel"] == "rød"
    assert fields["XLENTFindingCount"] == 3
    assert fields["XLENTSuggestedLabel"] == "Highly Confidential"
    assert "XLENTLastScanned" in fields


def test_resolve_local_drive_item_maps_sync_root_to_graph_path(monkeypatch, tmp_path):
    calls: list[tuple[str, str, dict | None]] = []
    sync_root = tmp_path / "OneDrive - XLENT"
    local_file = sync_root / "Prosjekt A" / "Kunde doc.docx"
    local_file.parent.mkdir(parents=True)
    local_file.write_text("x", encoding="utf-8")

    def fake_request(method: str, path: str, body: dict | None = None):
        calls.append((method, path, body))
        return {"id": "item-id", "name": "Kunde doc.docx", "webUrl": "https://example.test/doc"}

    monkeypatch.setattr(graph, "_graph_request", fake_request)

    resolved = graph.resolve_local_drive_item(local_file, drive_id="drive-id", sync_root=str(sync_root))

    assert resolved["drive_id"] == "drive-id"
    assert resolved["item_id"] == "item-id"
    assert resolved["relative_path"] == "Prosjekt A/Kunde doc.docx"
    assert calls[0][0] == "GET"
    assert "/drives/drive-id/root:/Prosjekt%20A/Kunde%20doc.docx:" in calls[0][1]


def test_microsoft_tags_endpoint_attaches_red_warning_to_last_result(monkeypatch):
    tags = {
        "sensitivity": {"labels": [{"id": "lbl1", "name": "Highly Confidential"}]},
        "retention": {"name": "Retain 7 years"},
        "policy_warning": "Microsoft 365-label tilsier konfidensielt dokument.",
    }
    monkeypatch.setattr(app_module, "read_document_tags", lambda drive_id, item_id: tags)
    monkeypatch.setattr(
        app_module,
        "_last_result",
        ScanResult(file_name="doc.docx", file_size=1, text_length=1, text_preview=""),
    )

    response = app_module.flask_app.test_client().post(
        "/microsoft/graph/tags",
        json={"drive_id": "drive", "item_id": "item"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["policy_warning"]
    assert app_module._last_result.microsoft_tags is tags
    assert app_module._last_result.policy_warning_level == "rød"


def test_tags_for_local_file_endpoint_resolves_last_path_and_attaches_tags(monkeypatch, tmp_path):
    source = tmp_path / "doc.docx"
    source.write_text("x", encoding="utf-8")
    tags = {
        "sensitivity": {"labels": [{"id": "lbl1", "name": "Highly Confidential"}]},
        "retention": {"name": "Retain 7 years"},
        "policy_warning": "Microsoft 365-label tilsier konfidensielt dokument.",
        "resolved": {"drive_id": "drive", "item_id": "item", "sync_root": str(tmp_path)},
    }
    monkeypatch.setattr(app_module, "read_document_tags_for_local_path", lambda *args, **kwargs: tags)
    monkeypatch.setattr(app_module, "_last_path", source)
    monkeypatch.setattr(
        app_module,
        "_last_result",
        ScanResult(file_name="doc.docx", file_size=1, text_length=1, text_preview="", risk_level="gul"),
    )

    response = app_module.flask_app.test_client().post(
        "/microsoft/graph/tags-for-local-file",
        json={"drive_id": "drive", "sync_root": str(tmp_path)},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["resolved"]["item_id"] == "item"
    assert app_module._last_result.policy_warning_level == "rød"


def test_write_scan_metadata_endpoint_uses_last_result(monkeypatch):
    captured: dict[str, object] = {}

    def fake_update(drive_id: str, item_id: str, fields: dict):
        captured["drive_id"] = drive_id
        captured["item_id"] = item_id
        captured["fields"] = fields
        return {"_status": 200}

    monkeypatch.setattr(app_module, "update_sharepoint_fields", fake_update)
    monkeypatch.setattr(
        app_module,
        "_last_result",
            ScanResult(
                file_name="doc.docx",
                file_size=1,
                text_length=1,
                text_preview="",
                risk_level="gul",
                findings=[Finding(category="e-post", text="a@b.no", severity="gul")],
            ),
    )

    response = app_module.flask_app.test_client().post(
        "/microsoft/graph/write-scan-metadata",
        json={"drive_id": "drive", "item_id": "item", "fields": {"CustomField": "value"}},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert captured["drive_id"] == "drive"
    assert captured["item_id"] == "item"
    fields = captured["fields"]
    assert fields["XLENTRiskLevel"] == "gul"
    assert fields["XLENTFindingCount"] == 1
    assert fields["XLENTSuggestedLabel"] == "Confidential"
    assert fields["CustomField"] == "value"


def test_write_folder_metadata_maps_each_result_and_writes_fields(monkeypatch, tmp_path):
    source = tmp_path / "root.txt"
    source.write_text("secret", encoding="utf-8")
    result = ScanResult(
        file_name="root.txt",
        relative_path="root.txt",
        source_path=str(source),
        file_size=6,
        text_length=6,
        text_preview="secret",
        findings=[Finding(category="hemmelighet", text="secret", severity="rød")],
        risk_level="rød",
    )
    row = app_module._folder_result_row(result, report_id="report-root")
    with app_module._folder_scan_lock:
        app_module._folder_scan_results["report-root"] = result
    with app_module._folder_jobs_lock:
        app_module._folder_jobs["job-m365"] = {
            "status": "completed",
            "folder": str(tmp_path),
            "files": [row],
        }
    monkeypatch.setattr(
        app_module,
        "resolve_local_drive_item",
        lambda path, drive_id=None, sync_root=None: {"drive_id": drive_id, "item_id": "item-root"},
    )
    captured: dict[str, object] = {}

    def fake_update(drive_id: str, item_id: str, fields: dict):
        captured["drive_id"] = drive_id
        captured["item_id"] = item_id
        captured["fields"] = fields
        return {"_status": 200}

    monkeypatch.setattr(app_module, "update_sharepoint_fields", fake_update)

    response = app_module.flask_app.test_client().post(
        "/microsoft/graph/write-folder-metadata",
        json={"job_id": "job-m365", "drive_id": "drive", "sync_root": str(tmp_path)},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["written_count"] == 1
    assert captured["drive_id"] == "drive"
    assert captured["item_id"] == "item-root"
    fields = captured["fields"]
    assert fields["XLENTRiskLevel"] == "rød"
    assert fields["XLENTFindingCount"] == 1
    assert fields["XLENTSuggestedLabel"] == "Highly Confidential"


def test_microsoft_graph_endpoints_require_api_key_for_network_access(monkeypatch):
    monkeypatch.delenv("XLENT_SCANNER_API_KEY", raising=False)
    client = app_module.flask_app.test_client()

    blocked = client.get(
        "/microsoft/graph/status",
        environ_base={"REMOTE_ADDR": "10.0.0.5"},
        headers={"Host": "10.0.0.10:51291"},
    )
    assert blocked.status_code == 403
    assert blocked.get_json()["error_code"] == "api_key_required"

    monkeypatch.setenv("XLENT_SCANNER_API_KEY", "secret")
    unauthorized = client.get(
        "/microsoft/graph/status",
        environ_base={"REMOTE_ADDR": "10.0.0.5"},
        headers={"Host": "10.0.0.10:51291"},
    )
    authorized = client.get(
        "/microsoft/graph/status",
        environ_base={"REMOTE_ADDR": "10.0.0.5"},
        headers={"Host": "10.0.0.10:51291", "X-API-Key": "secret"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.get_json()["ok"] is True
