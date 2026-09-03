import hashlib
import hmac
import json
import sqlite3
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xlent_scanner import __version__
from xlent_scanner.audit_trail import AuditTrail, _canonical


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
    named_events = trail.query_events(path_mode="name")
    full_events = trail.query_events(path_mode="full")
    stored = (tmp_path / "audit.db").read_bytes()

    assert events == [recorded]
    assert recorded["event_type"] == "scan_completed"
    assert recorded["document_id"]
    assert recorded["metadata"] == {
        "source": "file",
        "category_counts": {"email": 2, "medical": 1},
    }
    assert "lønnsliste".encode() not in stored
    assert str(secret_path).encode() not in stored
    assert "Kari Nordmann".encode() not in stored
    assert "document_name" not in events[0]
    assert named_events[0]["document_name"] == "lønnsliste.docx"
    assert "document_path" not in named_events[0]
    assert full_events[0]["document_name"] == "lønnsliste.docx"
    assert full_events[0]["document_path"] == str(secret_path.resolve())
    with sqlite3.connect(tmp_path / "audit.db") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_query_events_filters_scan_log_without_changing_stored_events(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path)
    now = datetime.now(timezone.utc)
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

    entries = trail.query_events(
        limit=10_000,
        event_types=("scan_completed", "ai_scan_completed"),
        since=now - timedelta(days=30),
        scan_mode="ai_deep",
        risk_level="rød",
        outcome="partial",
        path_mode="name",
    )

    assert [entry["event_type"] for entry in entries] == ["ai_scan_completed"]
    assert entries[0]["document_name"] == "recent.docx"
    assert len(trail.query_events(limit=10_000)) == 3


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
    source = tmp_path / "Kunde Alfa" / "lønnsliste.docx"
    trail.record_event(
        "scan_completed",
        document_path=source,
        outcome="success",
        risk_level="grønn",
    )
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
    assert payload["events"][0]["document_name"] == "lønnsliste.docx"
    assert "document_path" not in payload["events"][0]
    assert str(source.parent) not in json.dumps(payload, ensure_ascii=False)
    assert "lønnsliste.docx" in html
    assert str(source.parent) not in html
    assert "Lokal skannelogg" in html


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


def test_v1_database_migrates_without_breaking_existing_hash_chain(
    tmp_path: Path,
) -> None:
    trail = AuditTrail(tmp_path)
    event = {
        "id": "legacy-event",
        "occurred_at": "2026-01-01T12:00:00+00:00",
        "event_type": "scan_completed",
        "scanner_version": __version__,
        "document_id": "legacy-document",
        "scan_mode": "standard",
        "outcome": "success",
        "risk_level": "grønn",
        "finding_count": 0,
        "metadata": {},
    }
    event_hash = hmac.new(trail._key(), _canonical(event), hashlib.sha256).hexdigest()
    with sqlite3.connect(trail.db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                scanner_version TEXT NOT NULL,
                document_id TEXT NOT NULL,
                scan_mode TEXT NOT NULL,
                outcome TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                finding_count INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL
            );
            CREATE TABLE audit_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO audit_meta VALUES ('schema_version', '1');
            """
        )
        connection.execute(
            """
            INSERT INTO audit_events (
                id, occurred_at, event_type, scanner_version, document_id,
                scan_mode, outcome, risk_level, finding_count, metadata_json,
                previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["id"],
                event["occurred_at"],
                event["event_type"],
                event["scanner_version"],
                event["document_id"],
                event["scan_mode"],
                event["outcome"],
                event["risk_level"],
                event["finding_count"],
                "{}",
                "",
                event_hash,
            ),
        )

    events = trail.query_events(path_mode="full")

    assert len(events) == 1
    assert "document_path" not in events[0]
    assert trail.verify_integrity()["ok"] is True
    with sqlite3.connect(trail.db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
        version = connection.execute(
            "SELECT value FROM audit_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert "document_path_encrypted" in columns
    assert version == "2"
