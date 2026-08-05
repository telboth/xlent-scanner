import io
import stat
from pathlib import Path
from types import SimpleNamespace

from xlent_scanner import app as app_module
from xlent_scanner import scanner
from xlent_scanner import access_audit
from xlent_scanner.access_audit import _parse_icacls_output, _posix_access_audit, audit_path_access
from xlent_scanner.models import ScanResult
import xlent_scanner.routes.scanning as scanning_routes


def test_parse_icacls_output_marks_local_group_as_shared_not_broad():
    output = "\n".join([
        r"C:\tmp\doc.txt BUILTIN\Users:(I)(RX)",
        r"               DOMAIN\Ola:(F)",
        "Successfully processed 1 files; Failed processing 0 files",
    ])

    summary = _parse_icacls_output(output, r"C:\tmp\doc.txt")

    assert summary["entries_total"] == 2
    assert summary["direct_entries"] == 1
    assert summary["inherited_entries"] == 1
    assert summary["broad_access"] is False
    assert summary["shared_local_access"] is True
    assert summary["shared_identities"] == [r"BUILTIN\Users"]
    assert summary["access_level"] == "shared_local"


def test_parse_icacls_output_does_not_treat_deny_as_granted_access():
    output = r"C:\tmp\doc.txt Everyone:(I)(CI)(DENY)(DC)"

    summary = _parse_icacls_output(output, r"C:\tmp\doc.txt")

    assert summary["broad_access"] is False
    assert summary["shared_local_access"] is False
    assert summary["access_level"] == "restricted"
    assert summary["entries"][0]["effect"] == "deny"
    assert summary["entries"][0]["grants_access"] is False


def test_parse_icacls_output_keeps_everyone_read_as_broad_access():
    output = r"C:\tmp\doc.txt Everyone:(I)(RX)"

    summary = _parse_icacls_output(output, r"C:\tmp\doc.txt")

    assert summary["broad_access"] is True
    assert summary["broad_identities"] == ["Everyone"]
    assert summary["access_level"] == "broad"


def test_audit_path_access_never_fails_for_existing_file(tmp_path: Path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("ok", encoding="utf-8")

    summary = audit_path_access(file_path)

    assert "available" in summary
    assert "ok" in summary
    assert summary.get("person_count_estimate") is None or summary["available"] is False


def test_posix_group_permissions_are_reported_as_shared_not_broad():
    class FakePosixPath:
        def stat(self):
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=1000, st_gid=100)

        def is_dir(self):
            return False

    summary = _posix_access_audit(FakePosixPath())

    assert summary["broad_access"] is False
    assert summary["shared_local_access"] is True
    assert any(identity.startswith("group:") for identity in summary["shared_identities"])
    assert summary["access_level"] == "shared_local"


def test_scan_file_adds_access_summary_only_when_requested(monkeypatch, tmp_path: Path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("Ola Nordmann", encoding="utf-8")
    monkeypatch.setattr(scanner, "extract_text", lambda path, ocr=False, pdf_mode="fast": "Ola Nordmann")
    monkeypatch.setattr(scanner, "audit_path_access", lambda path: {"available": True, "ok": True, "source": "test"})

    without_access = scanner.scan_file(file_path, language="nb", categories=["epost"])
    with_access = scanner.scan_file(file_path, language="nb", categories=["epost"], include_access_check=True)

    assert without_access.access_summary is None
    assert with_access.access_summary == {"available": True, "ok": True, "source": "test"}


def test_scan_folder_reuses_access_check_per_containing_folder(monkeypatch, tmp_path: Path):
    (tmp_path / "sub").mkdir()
    for relative in ("one.txt", "two.txt", "sub/three.txt"):
        (tmp_path / relative).write_text("ok", encoding="utf-8")

    audit_calls: list[Path] = []

    def fake_audit(path):
        audit_calls.append(Path(path))
        return {"available": True, "ok": True, "source": "test", "entries_total": 1}

    def fake_scan(path, **kwargs):
        assert kwargs.get("include_access_check") is False
        p = Path(path)
        return ScanResult(file_name=p.name, file_size=2, text_length=2, text_preview="ok")

    monkeypatch.setattr(access_audit, "audit_path_access", fake_audit)
    monkeypatch.setattr(scanner, "scan_file", fake_scan)

    results = scanner.scan_folder(tmp_path, recursive=True, include_access_check=True)

    assert set(audit_calls) == {tmp_path, tmp_path / "sub"}
    assert len(audit_calls) == 2
    assert all(result.access_summary["scope"] == "containing_folder" for result in results)


def test_uploaded_file_does_not_report_temporary_file_permissions(monkeypatch):
    observed: dict = {}

    def fake_scan(path, **kwargs):
        observed.update(kwargs)
        p = Path(path)
        return ScanResult(file_name=p.name, file_size=2, text_length=2, text_preview="ok")

    monkeypatch.setattr(scanning_routes, "scan_file", fake_scan)
    client = app_module.flask_app.test_client()

    response = client.post(
        "/scan-upload",
        data={
            "file": (io.BytesIO(b"ok"), "original.txt"),
            "access_check": "true",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert observed["include_access_check"] is False
    assert data["access_summary"]["available"] is False
    assert data["access_summary"]["source"] == "uploaded_copy"
