"""Eksplisitt, prosesslokal tilstand for desktop- og API-applikasjonen."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xlent_scanner.models import ScanResult


@dataclass
class AppState:
    """Samler muterbar apptilstand som tidligere lå som modulglobaler."""

    last_result: ScanResult | None = None
    last_path: Path | None = None
    last_tmp_path: Path | None = None
    last_ai_findings: list[dict] = field(default_factory=list)
    last_ai_findings_file_name: str = ""

    api_scan_results: dict[str, dict] = field(default_factory=dict)
    api_scan_lock: threading.Lock = field(default_factory=threading.Lock)

    folder_scan_results: dict[str, ScanResult] = field(default_factory=dict)
    folder_scan_lock: threading.Lock = field(default_factory=threading.Lock)
    folder_jobs: dict[str, dict] = field(default_factory=dict)
    folder_jobs_lock: threading.Lock = field(default_factory=threading.Lock)
    last_folder_job_id: str = ""

    window: Any | None = None
    initial_file: str | None = None
    port: int = 0

    def clear_ai_findings(self) -> None:
        self.last_ai_findings.clear()
        self.last_ai_findings_file_name = ""


app_state = AppState()
