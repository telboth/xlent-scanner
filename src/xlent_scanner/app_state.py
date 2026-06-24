"""Eksplisitt, prosesslokal tilstand for desktop- og API-applikasjonen."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xlent_scanner.jobs import JobManager
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
    folder_job_manager: JobManager = field(
        default_factory=lambda: JobManager(ttl_seconds=60 * 60, max_jobs=20)
    )

    window: Any | None = None
    initial_file: str | None = None
    port: int = 0

    def clear_ai_findings(self) -> None:
        self.last_ai_findings.clear()
        self.last_ai_findings_file_name = ""

    @property
    def folder_jobs(self) -> dict[str, dict]:
        """Bakoverkompatibelt innsyn; ny kode bør bruke folder_job_manager."""
        return self.folder_job_manager.jobs

    @property
    def folder_jobs_lock(self) -> threading.RLock:
        return self.folder_job_manager.lock

    @property
    def last_folder_job_id(self) -> str:
        return self.folder_job_manager.last_job_id

    @last_folder_job_id.setter
    def last_folder_job_id(self, value: str) -> None:
        self.folder_job_manager.last_job_id = value


app_state = AppState()
