from pathlib import Path
import time

from xlent_scanner import app as app_module
from xlent_scanner import scanner
from xlent_scanner.models import Finding, ScanResult


def _write(path: Path, text: str = "hello") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_folder_scan_plan_is_non_recursive_by_default(tmp_path: Path):
    _write(tmp_path / "root.txt")
    _write(tmp_path / "sub" / "nested.txt")

    plan = scanner.build_folder_scan_plan(tmp_path)

    assert plan["file_count"] == 1
    assert plan["samples"] == ["root.txt"]
    assert plan["folder_count"] == 1


def test_folder_scan_plan_can_scan_recursively(tmp_path: Path):
    _write(tmp_path / "root.txt")
    _write(tmp_path / "sub" / "nested.docx")
    _write(tmp_path / "sub" / "ignore.exe")

    plan = scanner.build_folder_scan_plan(tmp_path, recursive=True)

    assert plan["file_count"] == 2
    assert plan["samples"] == ["root.txt", str(Path("sub") / "nested.docx")]
    assert plan["folder_count"] == 2


def test_folder_scan_plan_respects_max_depth(tmp_path: Path):
    _write(tmp_path / "root.txt")
    _write(tmp_path / "sub" / "nested.txt")
    _write(tmp_path / "sub" / "deep" / "too-deep.txt")

    plan = scanner.build_folder_scan_plan(tmp_path, recursive=True, max_depth=1)

    assert plan["samples"] == ["root.txt", str(Path("sub") / "nested.txt")]


def test_folder_scan_plan_excludes_hidden_and_heavy_dirs(tmp_path: Path):
    _write(tmp_path / "root.txt")
    _write(tmp_path / ".git" / "secret.txt")
    _write(tmp_path / "node_modules" / "package.txt")
    _write(tmp_path / "regular" / "ok.txt")

    plan = scanner.build_folder_scan_plan(tmp_path, recursive=True)

    assert set(plan["samples"]) == {"root.txt", str(Path("regular") / "ok.txt")}
    assert all(".git" not in sample for sample in plan["samples"])
    assert all("node_modules" not in sample for sample in plan["samples"])


def test_folder_scan_plan_marks_truncated_at_max_files(tmp_path: Path):
    for i in range(3):
        _write(tmp_path / f"{i}.txt")

    plan = scanner.build_folder_scan_plan(tmp_path, max_files=2)

    assert plan["file_count"] == 2
    assert plan["truncated"] is True


def test_scan_folder_sets_relative_paths(monkeypatch, tmp_path: Path):
    _write(tmp_path / "root.txt")
    _write(tmp_path / "sub" / "nested.txt")

    def fake_scan_file(path, ignore_xlent=False, language="auto"):
        p = Path(path)
        return ScanResult(file_name=p.name, file_size=1, text_length=1, text_preview="x")

    monkeypatch.setattr(scanner, "scan_file", fake_scan_file)

    results = scanner.scan_folder(tmp_path, recursive=True)

    assert {r.relative_path for r in results} == {"root.txt", str(Path("sub") / "nested.txt")}


def test_scan_folder_preview_endpoint_returns_plan(tmp_path: Path):
    _write(tmp_path / "root.txt")
    _write(tmp_path / "sub" / "nested.txt")
    client = app_module.flask_app.test_client()

    response = client.post(
        "/scan-folder/preview",
        json={"folder_path": str(tmp_path), "recursive": True, "max_files": 500, "max_depth": 5},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["file_count"] == 2
    assert data["folder_count"] == 2


def test_scan_folder_endpoint_returns_tooltip_summary_and_report(monkeypatch, tmp_path: Path):
    _write(tmp_path / "root.txt")
    result = ScanResult(
        file_name="root.txt",
        relative_path="root.txt",
        file_size=12,
        text_length=12,
        text_preview="Kontakt person@example.com",
        findings=[
            Finding(category="e-post", text="person@example.com", context="Kontakt person@example.com", severity="gul"),
            Finding(category="⚠ system", text="ignored", context="", severity="gul"),
        ],
        risk_level="gul",
        risk_summary="Funn",
        recommended_action="Kontroller funn.",
        original_text="Kontakt person@example.com",
    )
    monkeypatch.setattr(app_module, "scan_folder", lambda *args, **kwargs: [result])
    client = app_module.flask_app.test_client()

    response = client.post("/scan-folder", json={"folder_path": str(tmp_path)})

    assert response.status_code == 200
    data = response.get_json()
    file_row = data["files"][0]
    assert file_row["report_id"]
    assert file_row["findings_summary"] == [
        {
            "category": "e-post",
            "text": "person@example.com",
            "severity": "gul",
            "context": "Kontakt person@example.com",
        }
    ]

    report = client.get(f"/folder-report/{file_row['report_id']}")
    assert report.status_code == 200
    assert "root.txt" in report.get_data(as_text=True)
    assert "person@example.com" in report.get_data(as_text=True)


def test_scan_folder_start_endpoint_tracks_background_progress(monkeypatch, tmp_path: Path):
    _write(tmp_path / "root.txt")
    _write(tmp_path / "sub" / "nested.txt")

    def fake_scan_file(path, ignore_xlent=False, language="auto"):
        p = Path(path)
        return ScanResult(
            file_name=p.name,
            source_path=str(p),
            file_size=1,
            text_length=7,
            text_preview="secret",
            findings=[Finding(category="hemmelighet", text="secret", context="secret", severity="rød")],
            risk_level="rød",
        )

    monkeypatch.setattr(app_module, "scan_file", fake_scan_file)
    with app_module._folder_jobs_lock:
        app_module._folder_jobs.clear()
    client = app_module.flask_app.test_client()

    started = client.post("/scan-folder/start", json={"folder_path": str(tmp_path), "recursive": True}).get_json()

    assert started["ok"] is True
    job_id = started["job_id"]
    status = {}
    for _ in range(50):
        status = client.get(f"/scan-folder/status/{job_id}").get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["completed"] == 2
    assert status["total"] == 2
    assert {row["relative_path"] for row in status["files"]} == {"root.txt", str(Path("sub") / "nested.txt")}
    assert all(row["report_id"] for row in status["files"])


def test_folder_export_and_audit_endpoints_write_files(monkeypatch, tmp_path: Path):
    result = ScanResult(
        file_name="root.txt",
        relative_path="root.txt",
        source_path=str(tmp_path / "root.txt"),
        file_size=12,
        text_length=12,
        text_preview="Kontakt person@example.com",
        findings=[Finding(category="e-post", text="person@example.com", context="", severity="gul")],
        risk_level="gul",
    )
    row = app_module._folder_result_row(result, report_id="report-1")
    job_id = "job-export"
    with app_module._folder_jobs_lock:
        app_module._folder_jobs[job_id] = {
            "status": "completed",
            "folder": str(tmp_path),
            "recursive": True,
            "total": 1,
            "completed": 1,
            "truncated": False,
            "files": [row],
        }
    monkeypatch.setattr(app_module, "_downloads_dir", lambda: tmp_path)
    client = app_module.flask_app.test_client()

    for endpoint, suffix in [
        ("/folder-export/json", ".json"),
        ("/folder-export/csv", ".csv"),
        ("/folder-audit/html", ".html"),
        ("/folder-audit/pdf", ".pdf"),
    ]:
        data = client.post(endpoint, json={"job_id": job_id}).get_json()
        assert data["ok"] is True
        assert data["path"].endswith(suffix)
        assert Path(data["path"]).exists()


def test_folder_redact_endpoint_patches_selected_files(monkeypatch, tmp_path: Path):
    source = _write(tmp_path / "source.docx", "secret")
    result = ScanResult(
        file_name="source.docx",
        relative_path=str(Path("docs") / "source.docx"),
        source_path=str(source),
        file_size=6,
        text_length=6,
        text_preview="secret",
        findings=[Finding(category="hemmelighet", text="secret", context="secret", severity="rød")],
        risk_level="rød",
    )
    with app_module._folder_scan_lock:
        app_module._folder_scan_results["report-redact"] = result
    monkeypatch.setattr(app_module, "_downloads_dir", lambda: tmp_path)

    calls = []

    def fake_patch_file(src, replacements, output, strip_annotations=False):
        calls.append((src, replacements, output, strip_annotations))
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text("redacted", encoding="utf-8")

    monkeypatch.setattr(app_module, "patch_file", fake_patch_file)
    client = app_module.flask_app.test_client()

    data = client.post(
        "/folder-redact",
        json={"report_ids": ["report-redact"], "strip_annotations": True},
    ).get_json()

    assert data["ok"] is True
    assert len(data["outputs"]) == 1
    assert Path(data["outputs"][0]["path"]).exists()
    assert calls[0][0] == source
    assert calls[0][3] is True


def test_folder_csv_export_escapes_excel_formula_cells(monkeypatch, tmp_path: Path):
    row = {
        "file_name": "=evil.txt",
        "relative_path": "=evil.txt",
        "report_id": "report-formula",
        "risk_level": "gul",
        "finding_count": 1,
        "file_size": 1,
        "text_length": 1,
        "error": "",
        "warning": "",
        "findings_summary": [{"category": "test", "text": "+cmd", "severity": "gul", "context": ""}],
    }
    with app_module._folder_jobs_lock:
        app_module._folder_jobs["job-formula"] = {
            "status": "completed",
            "folder": str(tmp_path),
            "recursive": False,
            "total": 1,
            "completed": 1,
            "truncated": False,
            "files": [row],
        }
    monkeypatch.setattr(app_module, "_downloads_dir", lambda: tmp_path)
    client = app_module.flask_app.test_client()

    data = client.post("/folder-export/csv", json={"job_id": "job-formula"}).get_json()

    assert data["ok"] is True
    csv_text = Path(data["path"]).read_text(encoding="utf-8-sig")
    assert "'=evil.txt" in csv_text
    assert "test: +cmd" in csv_text
