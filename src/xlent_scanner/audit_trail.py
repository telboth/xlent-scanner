"""Personvernminimert, lokalt og manipulasjonspåvisende revisjonsspor."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
import uuid
import zipfile
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Sequence

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from xlent_scanner import __version__
from xlent_scanner.paths import app_data_dir

_SAFE_METADATA_KEYS = {
    "access_status",
    "categories",
    "category_counts",
    "engine_counts",
    "file_extension",
    "file_size",
    "method",
    "model",
    "model_digest",
    "ollama_remote",
    "policy_digest",
    "purview_status",
    "remote_permission_granted",
    "removed_count",
    "retention_reason",
    "scan_status",
    "selected_count",
    "severity_counts",
    "sharepoint_access_status",
    "source",
    "verification_status",
}
_KEY_LOCK = threading.Lock()
_DB_INIT_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[str] = set()
_PATH_ASSOCIATED_DATA = b"xlent-audit-document-path-v1"


def _protect_key(key: bytes) -> bytes:
    if sys.platform != "win32":
        return b"RAW1" + key
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    buffer = ctypes.create_string_buffer(key)
    input_blob = DataBlob(
        len(key), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    output_blob = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "XLENT Scanner audit key",
        None,
        None,
        None,
        0x01,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return b"DPAPI1" + encrypted


def _unprotect_key(stored: bytes) -> bytes:
    if stored.startswith(b"RAW1"):
        return stored[4:]
    if not stored.startswith(b"DPAPI1") or sys.platform != "win32":
        raise RuntimeError("Auditnøkkelen har ukjent eller ugyldig format.")
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    encrypted = stored[6:]
    buffer = ctypes.create_string_buffer(encrypted)
    input_blob = DataBlob(
        len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    output_blob = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0x01, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:256]


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key not in _SAFE_METADATA_KEYS:
            continue
        if isinstance(value, dict):
            cleaned[key] = {
                str(child_key)[:80]: _safe_scalar(child_value)
                for child_key, child_value in sorted(value.items())
            }
        elif isinstance(value, (list, tuple, set)):
            cleaned[key] = [_safe_scalar(item) for item in value][:100]
        else:
            cleaned[key] = _safe_scalar(value)
    return cleaned


class AuditTrail:
    """Lagrer og leser audit-hendelser gjennom ett lite interface."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else app_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "audit.db"
        self.key_path = self.root / "audit.key"

    def _key(self) -> bytes:
        with _KEY_LOCK:
            if self.key_path.is_file():
                return _unprotect_key(self.key_path.read_bytes())
            key = secrets.token_bytes(32)
            self.key_path.write_bytes(_protect_key(key))
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            return key

    def _policy_digest(self) -> str:
        manifest = []
        for name in (
            "blacklist.toml",
            "custom_patterns.toml",
            "ignore.toml",
            "whitelist.toml",
        ):
            path = self.root / name
            content = path.read_bytes() if path.is_file() else b""
            manifest.append({
                "name": name,
                "digest": hmac.new(self._key(), content, hashlib.sha256).hexdigest(),
            })
        return hashlib.sha256(_canonical(manifest)).hexdigest()

    def _encrypt_document_path(self, document_path: str | Path | None) -> str:
        if document_path is None:
            return ""
        absolute_path = os.path.abspath(str(document_path))
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(self._key()).encrypt(
            nonce,
            absolute_path.encode("utf-8"),
            _PATH_ASSOCIATED_DATA,
        )
        return urlsafe_b64encode(nonce + encrypted).decode("ascii")

    def _decrypt_document_path(self, encrypted_path: str) -> str:
        packed = urlsafe_b64decode(encrypted_path.encode("ascii"))
        return AESGCM(self._key()).decrypt(
            packed[:12],
            packed[12:],
            _PATH_ASSOCIATED_DATA,
        ).decode("utf-8")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        database_id = str(self.db_path.resolve())
        with _DB_INIT_LOCK:
            schema_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_events'"
            ).fetchone()
            if database_id not in _INITIALIZED_DATABASES or not schema_exists:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        id TEXT NOT NULL UNIQUE,
                        occurred_at TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        scanner_version TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        document_path_encrypted TEXT NOT NULL DEFAULT '',
                        scan_mode TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        finding_count INTEGER NOT NULL,
                        metadata_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(audit_events)")
                }
                if "document_path_encrypted" not in columns:
                    connection.execute(
                        "ALTER TABLE audit_events ADD COLUMN "
                        "document_path_encrypted TEXT NOT NULL DEFAULT ''"
                    )
                connection.execute(
                    "INSERT OR REPLACE INTO audit_meta (key, value) "
                    "VALUES ('schema_version', '2')"
                )
                connection.commit()
                _INITIALIZED_DATABASES.add(database_id)
        return connection

    @staticmethod
    def _anchor_hash(connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT value FROM audit_meta WHERE key = 'anchor_hash'"
        ).fetchone()
        return str(row["value"]) if row else ""

    def _document_id(self, document_path: str | Path | None) -> str:
        if document_path is None:
            return ""
        normalized = os.path.normcase(os.path.abspath(str(document_path)))
        return hmac.new(self._key(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    def record_event(
        self,
        event_type: str,
        *,
        document_path: str | Path | None = None,
        scan_mode: str = "",
        outcome: str = "",
        risk_level: str = "",
        finding_count: int = 0,
        metadata: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        safe_metadata = _safe_metadata(metadata)
        encrypted_path = self._encrypt_document_path(document_path)
        event = {
            "id": uuid.uuid4().hex,
            "occurred_at": occurred_at or _utc_now(),
            "event_type": str(event_type)[:80],
            "scanner_version": __version__,
            "document_id": self._document_id(document_path),
            "scan_mode": str(scan_mode)[:40],
            "outcome": str(outcome)[:40],
            "risk_level": str(risk_level)[:20],
            "finding_count": max(0, int(finding_count)),
            "metadata": safe_metadata,
        }
        if encrypted_path:
            event["document_path_encrypted"] = encrypted_path
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = str(row["event_hash"]) if row else self._anchor_hash(connection)
            event_hash = hmac.new(
                self._key(),
                previous_hash.encode("ascii") + _canonical(event),
                hashlib.sha256,
            ).hexdigest()
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, occurred_at, event_type, scanner_version, document_id,
                    document_path_encrypted,
                    scan_mode, outcome, risk_level, finding_count, metadata_json,
                    previous_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"], event["occurred_at"], event["event_type"],
                    event["scanner_version"], event["document_id"], encrypted_path,
                    event["scan_mode"],
                    event["outcome"], event["risk_level"], event["finding_count"],
                    json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True),
                    previous_hash, event_hash,
                ),
            )
        public_event = dict(event)
        public_event.pop("document_path_encrypted", None)
        return {**public_event, "previous_hash": previous_hash, "event_hash": event_hash}

    def record_scan(
        self,
        result: Any,
        *,
        document_path: str | Path | None = None,
        source: str,
        scan_mode: str = "standard",
    ) -> dict[str, Any]:
        access = result.access_summary or {}
        sharepoint = result.sharepoint_access_summary or {}
        purview = result.purview_classification or {}
        return self.record_event(
            "scan_completed" if scan_mode == "standard" else "ai_scan_completed",
            document_path=document_path,
            scan_mode=scan_mode,
            outcome=result.scan_status,
            risk_level=result.risk_level,
            finding_count=len(result.findings),
            metadata={
                "source": source,
                "file_extension": Path(result.file_name).suffix.lower(),
                "file_size": result.file_size,
                "scan_status": result.scan_status,
                "severity_counts": dict(Counter(f.severity for f in result.findings)),
                "access_status": access.get("access_level") or access.get("status") or "not_checked",
                "sharepoint_access_status": sharepoint.get("access_level") or sharepoint.get("status") or "not_checked",
                "purview_status": purview.get("status") or "not_checked",
                "policy_digest": self._policy_digest(),
            },
        )

    def query_events(
        self,
        *,
        limit: int = 200,
        event_type: str = "",
        event_types: Sequence[str] = (),
        since: datetime | None = None,
        scan_mode: str = "",
        risk_level: str = "",
        outcome: str = "",
        path_mode: str = "none",
    ) -> list[dict[str, Any]]:
        if path_mode not in {"none", "name", "full"}:
            raise ValueError("path_mode må være none, name eller full")
        query = "SELECT * FROM audit_events"
        params: list[object] = []
        conditions: list[str] = []
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        elif event_types:
            normalized_types = tuple(str(value) for value in event_types if value)
            if normalized_types:
                placeholders = ", ".join("?" for _ in normalized_types)
                conditions.append(f"event_type IN ({placeholders})")
                params.extend(normalized_types)
        if since is not None:
            conditions.append("julianday(occurred_at) >= julianday(?)")
            params.append(since.isoformat())
        for column, value in (
            ("scan_mode", scan_mode),
            ("risk_level", risk_level),
            ("outcome", outcome),
        ):
            if value:
                conditions.append(f"{column} = ?")
                params.append(value)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY sequence DESC LIMIT ?"
        params.append(max(1, min(int(limit), 10_000)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        events = []
        for row in reversed(rows):
            event = dict(row)
            event.pop("sequence", None)
            event["metadata"] = json.loads(event.pop("metadata_json"))
            encrypted_path = str(event.pop("document_path_encrypted") or "")
            if encrypted_path and path_mode != "none":
                try:
                    document_path = self._decrypt_document_path(encrypted_path)
                    event["document_name"] = Path(document_path).name
                    if path_mode == "full":
                        event["document_path"] = document_path
                except Exception:
                    event["document_name"] = "[utilgjengelig]"
            events.append(event)
        return events

    def verify_integrity(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY sequence"
            ).fetchall()
            previous_hash = self._anchor_hash(connection)
        for row in rows:
            sequence = int(row["sequence"])
            event = {
                "id": row["id"],
                "occurred_at": row["occurred_at"],
                "event_type": row["event_type"],
                "scanner_version": row["scanner_version"],
                "document_id": row["document_id"],
                "scan_mode": row["scan_mode"],
                "outcome": row["outcome"],
                "risk_level": row["risk_level"],
                "finding_count": int(row["finding_count"]),
                "metadata": json.loads(row["metadata_json"]),
            }
            encrypted_path = str(row["document_path_encrypted"] or "")
            if encrypted_path:
                event["document_path_encrypted"] = encrypted_path
            expected_hash = hmac.new(
                self._key(),
                previous_hash.encode("ascii") + _canonical(event),
                hashlib.sha256,
            ).hexdigest()
            if row["previous_hash"] != previous_hash or not hmac.compare_digest(
                str(row["event_hash"]), expected_hash
            ):
                return {"ok": False, "events": len(rows), "broken_at": sequence}
            previous_hash = str(row["event_hash"])
        return {"ok": True, "events": len(rows), "broken_at": None}

    def enforce_retention(
        self,
        *,
        max_events: int = 10_000,
        max_age_days: int = 90,
    ) -> dict[str, int]:
        """Fjern bare et sammenhengende prefiks og behold kjedens siste hash som anker."""
        max_events = max(2, int(max_events))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(max_age_days)))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT sequence, occurred_at, event_hash FROM audit_events ORDER BY sequence"
            ).fetchall()
            age_count = 0
            for row in rows:
                try:
                    occurred = datetime.fromisoformat(str(row["occurred_at"]))
                    if occurred.tzinfo is None:
                        occurred = occurred.replace(tzinfo=timezone.utc)
                except ValueError:
                    break
                if occurred >= cutoff:
                    break
                age_count += 1
            overflow_count = max(0, len(rows) - (max_events - 1))
            remove_count = max(age_count, overflow_count)
            if not remove_count:
                return {"removed": 0, "remaining": len(rows)}
            removed = rows[remove_count - 1]
            connection.execute(
                "INSERT OR REPLACE INTO audit_meta (key, value) VALUES ('anchor_hash', ?)",
                (removed["event_hash"],),
            )
            connection.execute(
                "DELETE FROM audit_events WHERE sequence <= ?",
                (removed["sequence"],),
            )
        self.record_event(
            "retention_applied",
            outcome="success",
            metadata={
                "removed_count": remove_count,
                "retention_reason": "age_or_event_limit",
            },
        )
        return {"removed": remove_count, "remaining": len(rows) - remove_count + 1}

    def export_bundle(self, output_path: str | Path) -> Path:
        """Eksporter signert maskinlesbar JSON sammen med en lesbar HTML-rapport."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.record_event("audit_exported", outcome="success")
        payload = {
            "format": "xlent-audit-v1",
            "exported_at": _utc_now(),
            "integrity": self.verify_integrity(),
            "events": self.query_events(limit=10_000, path_mode="name"),
        }
        payload["signing_key_id"] = hashlib.sha256(self._key()).hexdigest()
        payload["signature"] = hmac.new(
            self._key(), _canonical(payload), hashlib.sha256
        ).hexdigest()
        rows = "".join(
            "<tr>"
            f"<td>{escape(str(event['occurred_at']))}</td>"
            f"<td>{escape(str(event['event_type']))}</td>"
            f"<td>{escape(str(event.get('document_name') or ''))}</td>"
            f"<td>{escape(str(event['scan_mode']))}</td>"
            f"<td>{escape(str(event['outcome']))}</td>"
            f"<td>{escape(str(event['risk_level']))}</td>"
            f"<td>{int(event['finding_count'])}</td>"
            "</tr>"
            for event in payload["events"]
        )
        status = "Bestått" if payload["integrity"]["ok"] else "BRUDD OPPDAGET"
        html = f"""<!doctype html><html lang="nb"><meta charset="utf-8">
<title>XLENT Lokal skannelogg</title>
<style>body{{font:14px system-ui;margin:32px;color:#243230}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;border-bottom:1px solid #ccd5d3;text-align:left}}th{{background:#edf1f0}}</style>
<h1>Lokal skannelogg</h1><p>Loggkontroll: <strong>{status}</strong>. Hendelser: {len(payload['events'])}.</p>
<table><thead><tr><th>Tidspunkt</th><th>Hendelse</th><th>Filnavn</th><th>Modus</th><th>Resultat</th><th>Risiko</th><th>Funn</th></tr></thead><tbody>{rows}</tbody></table>
</html>"""
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "audit.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            archive.writestr("audit.html", html)
        return output
