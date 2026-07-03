from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import pytest

from xlent_scanner.models import Finding, ScanResult
from xlent_scanner.zip_processing import cleanup_old_zip_temp_dirs, extract_zip_to_temp

import xlent_scanner.app as app_module
import xlent_scanner.routes.scanning as scanning_routes


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buf.getvalue()


def test_extract_zip_to_temp_counts_supported_and_ignored_files(tmp_path: Path):
    archive = tmp_path / "case.zip"
    archive.write_bytes(_zip_bytes({
        "root.txt": "Kontakt ola@example.com",
        "nested/report.md": "Hei",
        "image.bin": "ignored",
    }))

    extracted = extract_zip_to_temp(archive)

    assert extracted.total_files == 3
    assert extracted.supported_files == 2
    assert extracted.ignored_files == 1
    assert (extracted.root / "root.txt").exists()
    assert (extracted.root / "nested" / "report.md").exists()
    assert extracted.skipped == [{"file": "image.bin", "reason": "Filtypen støttes ikke."}]


def test_extract_zip_to_temp_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes({"../evil.txt": "no"}))

    with pytest.raises(ValueError, match="Usikker sti"):
        extract_zip_to_temp(archive)


def test_cleanup_old_zip_temp_dirs_only_removes_old_zip_dirs(tmp_path: Path):
    old_zip = tmp_path / "xlent-zip-old"
    old_zip.mkdir()
    fresh_zip = tmp_path / "xlent-zip-fresh"
    fresh_zip.mkdir()
    other = tmp_path / "other-temp"
    other.mkdir()
    old_time = time.time() - 48 * 60 * 60
    os.utime(old_zip, (old_time, old_time))

    removed = cleanup_old_zip_temp_dirs(temp_root=tmp_path, max_age_seconds=24 * 60 * 60)

    assert removed == 1
    assert not old_zip.exists()
    assert fresh_zip.exists()
    assert other.exists()


def test_scan_upload_zip_returns_batch_rows(monkeypatch):
    def fake_scan_file(path, **kwargs):
        p = Path(path)
        return ScanResult(
            file_name=p.name,
            file_size=12,
            text_length=24,
            text_preview="Kontakt ola@example.com",
            findings=[Finding(category="e-post", text="ola@example.com", severity="gul")],
            risk_level="gul",
            original_text="Kontakt ola@example.com",
        )

    monkeypatch.setattr(scanning_routes, "scan_file", fake_scan_file)
    with app_module.app_state.folder_jobs_lock:
        app_module.app_state.folder_jobs.clear()
    client = app_module.flask_app.test_client()

    response = client.post(
        "/scan-upload",
        data={"file": (io.BytesIO(_zip_bytes({"a.txt": "Kontakt ola@example.com", "skip.bin": "x"})), "case.zip")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["zip_scan"] is True
    assert data["supported_files"] == 1
    assert data["ignored_files"] == 1
    assert data["skipped"] == [{"file": "skip.bin", "reason": "Filtypen støttes ikke."}]
    assert data["job_id"]
    assert data["files"][0]["relative_path"] == "a.txt"
    assert data["files"][0]["finding_count"] == 1

    status = client.get(f"/scan-folder/status/{data['job_id']}").get_json()
    assert status["status"] == "completed"
    assert status["completed"] == 1


def test_scan_upload_zip_marks_large_archives(monkeypatch):
    def fake_scan_file(path, **kwargs):
        p = Path(path)
        return ScanResult(file_name=p.name, file_size=1, text_length=1, text_preview="", risk_level="grønn")

    monkeypatch.setattr(scanning_routes, "scan_file", fake_scan_file)
    client = app_module.flask_app.test_client()
    entries = {f"{idx}.txt": "x" for idx in range(101)}

    response = client.post(
        "/scan-upload",
        data={"file": (io.BytesIO(_zip_bytes(entries)), "large.zip")},
        content_type="multipart/form-data",
    )

    data = response.get_json()
    assert data["zip_scan"] is True
    assert data["warning"]
    assert data["supported_files"] == 101
