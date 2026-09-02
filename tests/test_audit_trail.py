import json
import sqlite3
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from xlent_scanner.audit_trail import AuditTrail


def test_recorded_event_is_retrievable_without_sensitive_content(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path)
    secret_path = tmp_path / "Kunde Alfa" / "lønnsliste.docx"

    recorded = trail.record_event(
        "scan_completed",
        document_path=secret_path,
        scan_mode="standard",
        outcome="success",
        risk_level="rød",
        finding_count=3,
        metadata={
            "source": "file",
            "category_counts": {"medical": 1, "email": 2},
            "text": "Kari Nordmann har diabetes",
            "path": str(secret_path),
        },
    )

    events = trail.query_events()
    stored = (tmp_path / "audit.db").read_bytes()

    assert events == [recorded]
    assert recorded["event_type"] == "scan_completed"
    assert recorded["document_id"]
    assert recorded["metadata"] == {
        "source": "file",
        "category_counts": {"email": 2, "medical": 1},
    }
    assert "lønnsliste".encode() not in stored
    assert "Kari Nordmann".encode() not in stored
    with sqlite3.connect(tmp_path / "audit.db") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_integrity_check_detects_modified_event(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path)
    trail.record_event("scan_completed", outcome="success", finding_count=1)
    trail.record_event("redaction_created", outcome="passed", finding_count=0)

    assert trail.verify_integrity() == {"ok": True, "events": 2, "broken_at": None}

    with sqlite3.connect(tmp_path / "audit.db") as connection:
        connection.execute(
            "UPDATE audit_events SET outcome = 'forged' WHERE sequence = 1"
        )

    verification = trail.verify_integrity()
    assert verification["ok"] is False
    assert verification["broken_at"] == 1


def test_retention_keeps_audited_chain_valid(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path)
    for index in range(5):
        trail.record_event(
            "scan_completed",
            outcome="success",
            metadata={"source": f"source-{index}"},
        )

    result = trail.enforce_retention(max_events=3)
    events = trail.query_events(limit=10)

    assert result["removed"] == 3
    assert len(events) == 3
    assert events[-1]["event_type"] == "retention_applied"
    assert trail.verify_integrity()["ok"] is True


def test_export_bundle_contains_signed_json_and_readable_html(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path)
    trail.record_event("scan_completed", outcome="success", risk_level="grønn")
    output = tmp_path / "audit-export.zip"

    result = trail.export_bundle(output)

    assert result == output
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"audit.json", "audit.html"}
        payload = json.loads(archive.read("audit.json"))
        html = archive.read("audit.html").decode("utf-8")
    assert payload["integrity"]["ok"] is True
    assert len(payload["signature"]) == 64
    assert payload["events"][0]["event_type"] == "scan_completed"
    assert "Revisjonsspor" in html


def test_windows_audit_key_is_dpapi_protected(tmp_path: Path) -> None:
    if sys.platform != "win32":
        return
    trail = AuditTrail(tmp_path)

    trail.record_event("scan_completed")

    stored_key = (tmp_path / "audit.key").read_bytes()
    assert stored_key.startswith(b"DPAPI1")
    assert len(stored_key) > 38


def test_concurrent_writers_preserve_all_events_and_integrity(tmp_path: Path) -> None:
    def write(index: int) -> None:
        AuditTrail(tmp_path).record_event(
            "scan_completed",
            outcome="success",
            finding_count=index,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(20)))

    trail = AuditTrail(tmp_path)
    assert len(trail.query_events(limit=100)) == 20
    assert trail.verify_integrity()["ok"] is True
