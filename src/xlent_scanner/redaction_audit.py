"""Kontrollskann og persistent revisjonshistorikk for anonymiserte filer."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xlent_scanner.models import Finding, ScanResult
from xlent_scanner.paths import app_data_dir
from xlent_scanner.scanner import scan_file

MAX_REDACTION_HISTORY = 100


def _history_file() -> Path:
    return app_data_dir() / "redaction_history.jsonl"


def load_redaction_history() -> list[dict]:
    path = _history_file()
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text("utf-8", errors="ignore").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries[-MAX_REDACTION_HISTORY:]


def clear_redaction_history() -> None:
    path = _history_file()
    if path.exists():
        path.unlink()


def redaction_history_entry(entry_id: str) -> dict | None:
    return next(
        (entry for entry in load_redaction_history() if entry.get("id") == entry_id),
        None,
    )


def latest_redaction_for_source(file_name: str) -> dict | None:
    normalized = str(file_name or "").casefold()
    return next(
        (
            entry
            for entry in reversed(load_redaction_history())
            if str(entry.get("source_file") or "").casefold() == normalized
        ),
        None,
    )


def _write_history(entries: list[dict]) -> None:
    path = _history_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(entry, ensure_ascii=False)
            for entry in entries[-MAX_REDACTION_HISTORY:]
        )
        + "\n",
        encoding="utf-8",
    )


def _active_findings(result: ScanResult) -> list[Finding]:
    return [
        finding
        for finding in result.findings
        if finding.severity != "grønn" and not finding.category.startswith("⚠")
    ]


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _selected_audit(
    selected_findings: list[Finding],
    ai_findings: list[dict],
) -> list[dict]:
    ai_by_key = {
        (
            str(finding.get("category") or "").casefold(),
            str(finding.get("text") or "").casefold(),
        ): finding
        for finding in ai_findings
    }
    audit: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for finding in selected_findings:
        key = (finding.category.casefold(), finding.text.casefold())
        if key in seen:
            continue
        seen.add(key)
        ai = ai_by_key.get(key) or ai_by_key.get(
            (finding.category.removeprefix("🤖").strip().casefold(), finding.text.casefold())
        )
        is_ai = finding.category.startswith("🤖") or ai is not None
        audit.append({
            "category": finding.category,
            "text": finding.text,
            "severity": finding.severity,
            "engine": "ai" if is_ai else "rule",
            "confidence": str((ai or {}).get("confidence") or ""),
        })
    return audit


def verify_redacted_file(
    output_path: Path,
    selected_findings: list[Finding],
    *,
    language: str = "auto",
) -> dict:
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        result = scan_file(output_path, language=language or "auto")
    except Exception as exc:
        return {
            "status": "error",
            "passed": False,
            "checked_at": checked_at,
            "risk_level": "gul",
            "finding_count": 0,
            "removed_count": 0,
            "remaining_selected_count": 0,
            "remaining_findings": [],
            "removed_findings": [],
            "error": str(exc),
        }

    output_text = _normalized(result.original_text)
    removed_findings: list[dict] = []
    remaining_selected: list[dict] = []
    seen_values: set[str] = set()
    for finding in selected_findings:
        value = finding.raw_text or finding.text
        normalized = _normalized(value)
        if not normalized or normalized in seen_values:
            continue
        seen_values.add(normalized)
        summary = {"category": finding.category, "text": finding.text}
        if normalized in output_text:
            remaining_selected.append(summary)
        else:
            removed_findings.append(summary)

    active = _active_findings(result)
    passed = (
        result.scan_status != "failed"
        and result.risk_level == "grønn"
        and not remaining_selected
    )
    return {
        "status": "passed" if passed else "needs_review",
        "passed": passed,
        "checked_at": checked_at,
        "risk_level": result.risk_level,
        "scan_status": result.scan_status,
        "finding_count": len(active),
        "removed_count": len(removed_findings),
        "remaining_selected_count": len(remaining_selected),
        "remaining_findings": [
            {
                "category": finding.category,
                "text": finding.text,
                "severity": finding.severity,
                "context": finding.context,
            }
            for finding in active[:50]
        ],
        "remaining_selected": remaining_selected,
        "removed_findings": removed_findings,
        "warning": result.warning,
        "error": result.error,
    }


def record_redaction(
    output_path: Path,
    source_result: ScanResult,
    selected_findings: list[Finding],
    *,
    ai_findings: list[dict] | None = None,
    method: str,
    ai_metadata: dict[str, Any] | None = None,
) -> dict:
    ai_findings = ai_findings or []
    verification = verify_redacted_file(
        output_path,
        selected_findings,
        language=source_result.language or "auto",
    )
    entry = {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file": source_result.file_name,
        "output_file": output_path.name,
        "path": str(output_path),
        "method": method,
        "selected_count": len(selected_findings),
        "selected_findings": _selected_audit(selected_findings, ai_findings),
        "ai_metadata": dict(ai_metadata or {}),
        "verification": verification,
    }
    history = load_redaction_history()
    history.append(entry)
    _write_history(history)
    return entry


def refresh_redaction_verification(entry_id: str) -> dict | None:
    history = load_redaction_history()
    entry = next((item for item in history if item.get("id") == entry_id), None)
    if entry is None:
        return None
    path = Path(str(entry.get("path") or ""))
    if not path.is_file():
        entry["verification"] = {
            "status": "error",
            "passed": False,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error": "Filen finnes ikke lenger.",
        }
    else:
        selected = [
            Finding(
                category=str(item.get("category") or ""),
                text=str(item.get("text") or ""),
                severity=str(item.get("severity") or "gul"),
                raw_text=str(item.get("text") or ""),
            )
            for item in entry.get("selected_findings") or []
        ]
        entry["verification"] = verify_redacted_file(path, selected)
    _write_history(history)
    return entry
