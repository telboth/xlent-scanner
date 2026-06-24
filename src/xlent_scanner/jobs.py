"""Trådsikker, prosesslokal lagring for bakgrunnsjobber."""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from typing import Iterator


class JobManager:
    """Samler opprettelse, status, opprydding og kansellering av jobber."""

    def __init__(
        self,
        *,
        ttl_seconds: float | None = None,
        max_jobs: int | None = None,
        id_length: int | None = None,
        terminal_statuses: tuple[str, ...] = (
            "done",
            "completed",
            "error",
            "failed",
            "cancelled",
        ),
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_jobs = max_jobs
        self.id_length = id_length
        self.terminal_statuses = frozenset(terminal_statuses)
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.last_job_id: str = ""

    def _new_id(self) -> str:
        value = str(uuid.uuid4())
        return value[:self.id_length] if self.id_length else value

    @staticmethod
    def _created_at(job: dict) -> float:
        return float(job.get("started_at") or job.get("created_at") or 0)

    def cleanup_locked(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if self.ttl_seconds is not None:
            expired = [
                job_id
                for job_id, job in self.jobs.items()
                if job.get("status") in self.terminal_statuses
                and float(job.get("completed_at") or self._created_at(job)) > 0
                and now - float(job.get("completed_at") or self._created_at(job))
                > self.ttl_seconds
            ]
            for job_id in expired:
                self.jobs.pop(job_id, None)

        if self.max_jobs is not None:
            while len(self.jobs) > self.max_jobs:
                removable = [
                    job_id
                    for job_id, job in self.jobs.items()
                    if job.get("status") in self.terminal_statuses
                ]
                if not removable:
                    break
                oldest = min(
                    removable,
                    key=lambda job_id: self._created_at(self.jobs[job_id]),
                )
                self.jobs.pop(oldest, None)

        if self.last_job_id and self.last_job_id not in self.jobs:
            self.last_job_id = ""

    def cleanup(self, now: float | None = None) -> None:
        with self.lock:
            self.cleanup_locked(now)

    def create(
        self,
        data: dict | None = None,
        *,
        job_id: str | None = None,
        make_latest: bool = True,
    ) -> str:
        job_id = job_id or self._new_id()
        job = dict(data or {})
        job.setdefault("job_id", job_id)
        job.setdefault("status", "queued")
        job.setdefault("started_at", time.time())
        with self.lock:
            self.cleanup_locked()
            self.jobs[job_id] = job
            if make_latest:
                self.last_job_id = job_id
            self.cleanup_locked()
        return job_id

    def snapshot(self, job_id: str | None = None) -> dict:
        with self.lock:
            self.cleanup_locked()
            resolved_id = job_id or self.last_job_id
            return dict(self.jobs.get(resolved_id, {})) if resolved_id else {}

    @contextmanager
    def mutate(self, job_id: str) -> Iterator[dict | None]:
        with self.lock:
            self.cleanup_locked()
            yield self.jobs.get(job_id)

    def update(self, job_id: str, values: dict | None = None, **kwargs) -> bool:
        with self.mutate(job_id) as job:
            if job is None:
                return False
            job.update(values or {})
            job.update(kwargs)
            return True

    def cancel(
        self,
        job_id: str | None = None,
        *,
        flag: str = "cancel_requested",
        queued_statuses: tuple[str, ...] = ("queued",),
    ) -> bool:
        with self.lock:
            self.cleanup_locked()
            resolved_id = job_id or self.last_job_id
            job = self.jobs.get(resolved_id) if resolved_id else None
            if job is None:
                return False
            job[flag] = True
            if job.get("status") in queued_statuses:
                job["status"] = "cancelled"
            return True

    def clear(self) -> None:
        with self.lock:
            self.jobs.clear()
            self.last_job_id = ""
