from pathlib import Path

from xlent_scanner import redaction_audit
from xlent_scanner.models import Finding, ScanResult


def _source_result() -> ScanResult:
    return ScanResult(
        file_name="source.txt",
        file_size=30,
        text_length=30,
        text_preview="Kontakt person@example.com",
        original_text="Kontakt person@example.com",
        language="nb",
        findings=[
            Finding(
                category="e-post",
                text="person@example.com",
                raw_text="person@example.com",
                severity="gul",
            )
        ],
        risk_level="gul",
    )


def test_verify_redacted_file_reports_removed_and_passed(monkeypatch, tmp_path):
    output = tmp_path / "source-anonymisert.txt"
    output.write_text("Kontakt <Epost 1>", encoding="utf-8")
    monkeypatch.setattr(
        redaction_audit,
        "scan_file",
        lambda path, language="auto": ScanResult(
            file_name=Path(path).name,
            file_size=10,
            text_length=10,
            text_preview="Kontakt <Epost 1>",
            original_text="Kontakt <Epost 1>",
            findings=[],
            risk_level="grønn",
            scan_status="success",
        ),
    )

    verification = redaction_audit.verify_redacted_file(
        output,
        _source_result().findings,
        language="nb",
    )

    assert verification["passed"] is True
    assert verification["removed_count"] == 1
    assert verification["remaining_selected_count"] == 0
    assert verification["finding_count"] == 0


def test_verify_redacted_file_reports_selected_text_not_found_in_source(monkeypatch, tmp_path):
    output = tmp_path / "source-anonymisert.txt"
    output.write_text("Kontakt <Epost 1>", encoding="utf-8")
    selected = [
        Finding(
            category="Egendefinert tekst",
            text="Acme Prosjekt",
            raw_text="Acme Prosjekt",
            severity="gul",
        )
    ]
    monkeypatch.setattr(
        redaction_audit,
        "scan_file",
        lambda path, language="auto": ScanResult(
            file_name=Path(path).name,
            file_size=10,
            text_length=10,
            text_preview="Kontakt <Epost 1>",
            original_text="Kontakt <Epost 1>",
            findings=[],
            risk_level="grønn",
            scan_status="success",
        ),
    )

    verification = redaction_audit.verify_redacted_file(
        output,
        selected,
        source_text="Kontakt person@example.com",
    )

    assert verification["passed"] is True
    assert verification["removed_count"] == 0
    assert verification["not_found_count"] == 1
    assert verification["not_found_findings"] == [
        {"category": "Egendefinert tekst", "text": "Acme Prosjekt"}
    ]


def test_verify_redacted_file_requires_review_when_findings_remain(monkeypatch, tmp_path):
    output = tmp_path / "source-anonymisert.txt"
    output.write_text("Kontakt person@example.com", encoding="utf-8")
    remaining = Finding(
        category="e-post",
        text="person@example.com",
        severity="gul",
    )
    monkeypatch.setattr(
        redaction_audit,
        "scan_file",
        lambda path, language="auto": ScanResult(
            file_name=Path(path).name,
            file_size=10,
            text_length=10,
            text_preview="Kontakt person@example.com",
            original_text="Kontakt person@example.com",
            findings=[remaining],
            risk_level="gul",
            scan_status="success",
        ),
    )

    verification = redaction_audit.verify_redacted_file(
        output,
        _source_result().findings,
    )

    assert verification["passed"] is False
    assert verification["status"] == "needs_review"
    assert verification["remaining_selected_count"] == 1
    assert verification["finding_count"] == 1


def test_record_redaction_persists_audit_metadata(monkeypatch, tmp_path):
    output = tmp_path / "source-anonymisert.txt"
    output.write_text("redacted", encoding="utf-8")
    monkeypatch.setattr(redaction_audit, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        redaction_audit,
        "verify_redacted_file",
        lambda *args, **kwargs: {
            "status": "passed",
            "passed": True,
            "risk_level": "grønn",
            "finding_count": 0,
            "removed_count": 1,
        },
    )

    entry = redaction_audit.record_redaction(
        output,
        _source_result(),
        _source_result().findings,
        method="patch_txt",
        ai_metadata={"model": "llama3.2:3b", "categories": ["navn"]},
    )

    loaded = redaction_audit.load_redaction_history()
    assert loaded == [entry]
    assert entry["verification"]["passed"] is True
    assert entry["selected_findings"][0]["engine"] == "rule"
    assert entry["ai_metadata"]["model"] == "llama3.2:3b"
