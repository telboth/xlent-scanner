"""Persistent scan-historikk – lagret i JSONL-fil under %APPDATA%/xlent-scanner/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from xlent_scanner.paths import app_data_dir

MAX_HISTORY = 200


def _history_file() -> Path:
    return app_data_dir() / "scan_history.jsonl"


def load_history() -> list[dict]:
    """Last inn historikk fra disk. Returnerer liste sortert nyest sist."""
    f = _history_file()
    if not f.exists():
        return []
    entries: list[dict] = []
    for line in f.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries[-MAX_HISTORY:]


def add_history_entry(
    file_name: str,
    risk_level: str,
    finding_count: int,
    file_size: int = 0,
    source: str = "file",
) -> None:
    """Legg til en oppføring i historikken."""
    history = load_history()
    history.append({
        "file_name": file_name,
        "risk_level": risk_level,
        "finding_count": finding_count,
        "file_size": file_size,
        "source": source,  # "file" | "text" | "batch"
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    history = history[-MAX_HISTORY:]
    f = _history_file()
    f.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in history) + "\n",
        encoding="utf-8",
    )


def clear_history() -> None:
    """Slett all historikk."""
    f = _history_file()
    if f.exists():
        f.unlink()
