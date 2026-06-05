from pathlib import Path

from xlent_scanner import app as app_module
from xlent_scanner import scanner
from xlent_scanner.models import ScanResult


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
