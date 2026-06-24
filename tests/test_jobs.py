import time

from xlent_scanner.jobs import JobManager


def test_job_manager_tracks_latest_and_returns_copies() -> None:
    jobs = JobManager(max_jobs=3)
    first = jobs.create({"value": 1}, job_id="first")
    second = jobs.create({"value": 2}, job_id="second")

    assert first == "first"
    assert second == "second"
    assert jobs.snapshot()["job_id"] == "second"

    snapshot = jobs.snapshot("first")
    snapshot["value"] = 99
    assert jobs.snapshot("first")["value"] == 1


def test_job_manager_cancels_queued_job() -> None:
    jobs = JobManager()
    jobs.create({"status": "queued"}, job_id="queued")

    assert jobs.cancel("queued") is True
    assert jobs.snapshot("queued")["cancel_requested"] is True
    assert jobs.snapshot("queued")["status"] == "cancelled"


def test_job_manager_removes_expired_and_excess_jobs() -> None:
    jobs = JobManager(ttl_seconds=10, max_jobs=2)
    now = time.time()
    with jobs.lock:
        jobs.jobs["expired"] = {
            "job_id": "expired",
            "status": "completed",
            "started_at": now - 20,
        }
        jobs.jobs["older"] = {
            "job_id": "older",
            "status": "completed",
            "started_at": now - 5,
        }
        jobs.jobs["newer"] = {
            "job_id": "newer",
            "status": "completed",
            "started_at": now - 4,
        }

    jobs.cleanup(now=now)

    assert jobs.snapshot("expired") == {}
    assert set(jobs.jobs) == {"older", "newer"}
