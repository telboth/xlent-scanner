"""Bakgrunnsjobber for mappeskann — gir ekte progress + avbryt i Streamlit.

Streamlit kjører skriptet synkront per interaksjon, så en lang skanneløkke ville
blokkert UI-et og gjort en avbryt-knapp uklikkbar. Derfor kjøres selve skanningen
i en daemon-tråd som skriver fremdrift til et delt register, mens siden poller
status med en auto-oppdaterende fragment.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from xlent_scanner.models import ScanResult
from xlent_scanner.scanner import build_folder_scan_plan, scan_file

_jobs: dict[str, "FolderJob"] = {}
_lock = threading.Lock()
_RISK_ORDER = {"svart": 0, "rød": 1, "gul": 2, "grønn": 3}


@dataclass
class FolderJob:
    job_id: str
    folder: str
    total: int
    recursive: bool
    truncated: bool = False
    completed: int = 0
    status: str = "running"  # running / done / cancelled / error
    current_file: str = ""
    results: list[ScanResult] = field(default_factory=list)
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancel_flag: bool = False

    def sorted_results(self) -> list[ScanResult]:
        return sorted(
            self.results,
            key=lambda r: (_RISK_ORDER.get(r.risk_level, 3), (r.relative_path or r.file_name).lower()),
        )


def start_folder_job(
    folder: str | Path,
    *,
    recursive: bool,
    max_files: int,
    max_depth: int,
    language: str = "auto",
    ignore_xlent: bool = False,
    ocr: bool = False,
    scan_profile: str = "normal",
    categories: tuple[str, ...] | None = None,
    pdf_mode: str = "fast",
) -> str:
    plan = build_folder_scan_plan(folder, recursive=recursive, max_files=max_files, max_depth=max_depth)
    job = FolderJob(
        job_id=uuid.uuid4().hex,
        folder=str(folder),
        total=plan["file_count"],
        recursive=recursive,
        truncated=plan["truncated"],
    )
    with _lock:
        _jobs[job.job_id] = job

    files = plan["files"]
    root = Path(folder)

    def worker() -> None:
        try:
            for f in files:
                if job.cancel_flag:
                    job.status = "cancelled"
                    job.finished_at = time.time()
                    return
                job.current_file = Path(f).name
                r = scan_file(
                    f,
                    language=language,
                    ignore_xlent=ignore_xlent,
                    ocr=ocr,
                    scan_profile=scan_profile,
                    categories=list(categories) if categories else None,
                    pdf_mode=pdf_mode,
                )
                try:
                    r.relative_path = str(Path(f).relative_to(root))
                except ValueError:
                    r.relative_path = Path(f).name
                r.source_path = str(f)
                job.results.append(r)
                job.completed += 1
            job.status = "done"
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            job.status = "error"
        finally:
            if not job.finished_at:
                job.finished_at = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return job.job_id


def get_job(job_id: str) -> FolderJob | None:
    with _lock:
        return _jobs.get(job_id)


def cancel_job(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
    if job:
        job.cancel_flag = True


def preview_count(folder: str | Path, *, recursive: bool, max_files: int, max_depth: int) -> dict:
    """Rask forhåndstelling uten å lese filinnhold."""
    return build_folder_scan_plan(folder, recursive=recursive, max_files=max_files, max_depth=max_depth)
