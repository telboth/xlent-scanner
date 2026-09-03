import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from xlent_scanner.evaluation import (
    CorpusValidationError,
    evaluate_corpus,
    render_html_report,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_evaluate_corpus_scores_a_real_scanner_finding(tmp_path: Path) -> None:
    _write_json(tmp_path / "taxonomy.json", {
        "email": {"category_prefixes": ["e-post"], "severity": "gul"},
    })
    _write_json(tmp_path / "cases" / "email.json", {
        "id": "nb-email-001",
        "corpus_version": 1,
        "language": "nb",
        "profile": "normal",
        "text": "Kontakt test.person@example.com for mer informasjon.",
        "expected_status": "success",
        "expected_risk": "gul",
        "expected_findings": [
            {"type": "email", "value": "test.person@example.com", "count": 1},
        ],
        "forbidden_findings": [],
        "tags": ["structured", "positive"],
    })

    report = evaluate_corpus(tmp_path)

    assert report["metadata"]["scanner_version"] == "1.9.20"
    assert report["metadata"]["corpus_versions"] == [1]
    assert report["metadata"]["scan_mode"] == "standard"
    assert report["summary"] == {
        "cases": 1,
        "true_positives": 1,
        "false_positives": 0,
        "false_negatives": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "risk_matches": 1,
        "status_matches": 1,
        "forbidden_violations": 0,
    }
    assert len(report["cases"][0]["spec_digest"]) == 64
    assert report["by_type"]["email"] == {
        "true_positives": 1,
        "false_positives": 0,
        "false_negatives": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_evaluate_corpus_rejects_case_without_required_language(tmp_path: Path) -> None:
    _write_json(tmp_path / "taxonomy.json", {
        "email": {"category_prefixes": ["e-post"], "severity": "gul"},
    })
    _write_json(tmp_path / "cases" / "invalid.json", {
        "id": "invalid",
        "text": "test@example.com",
        "expected_status": "success",
        "expected_risk": "gul",
        "expected_findings": [],
    })

    with pytest.raises(CorpusValidationError, match="language"):
        evaluate_corpus(tmp_path)


def test_evaluate_corpus_applies_json_schema_when_present(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    schema = json.loads((repo / "evaluation" / "case.schema.json").read_text(encoding="utf-8"))
    _write_json(tmp_path / "case.schema.json", schema)
    _write_json(tmp_path / "taxonomy.json", {
        "email": {"category_prefixes": ["e-post"], "severity": "gul"},
    })
    _write_json(tmp_path / "cases" / "invalid.json", {
        "id": "invalid-extra-property",
        "corpus_version": 1,
        "language": "nb",
        "profile": "normal",
        "text": "test@example.com",
        "expected_status": "success",
        "expected_risk": "gul",
        "expected_findings": [{"type": "email", "value": "test@example.com"}],
        "forbidden_findings": [],
        "tags": [],
        "unexpected_property": True,
    })

    with pytest.raises(CorpusValidationError, match="unexpected_property"):
        evaluate_corpus(tmp_path)


def test_evaluate_corpus_counts_false_positive_and_false_negative(tmp_path: Path) -> None:
    _write_json(tmp_path / "taxonomy.json", {
        "email": {"category_prefixes": ["e-post"], "severity": "gul"},
    })
    base = {
        "corpus_version": 1,
        "language": "nb",
        "profile": "normal",
        "expected_status": "success",
        "forbidden_findings": [],
        "tags": [],
    }
    _write_json(tmp_path / "cases" / "missed.json", {
        **base,
        "id": "missed",
        "text": "Ingen kontaktinformasjon her.",
        "expected_risk": "grønn",
        "expected_findings": [{"type": "email", "value": "missing@example.com"}],
    })
    _write_json(tmp_path / "cases" / "unexpected.json", {
        **base,
        "id": "unexpected",
        "text": "unexpected@example.com",
        "expected_risk": "gul",
        "expected_findings": [],
        "forbidden_findings": [{"type": "email", "value": "unexpected@example.com"}],
    })

    report = evaluate_corpus(tmp_path)

    assert report["summary"]["false_positives"] == 1
    assert report["summary"]["false_negatives"] == 1
    assert report["summary"]["precision"] == 0.0
    assert report["summary"]["recall"] == 0.0
    cases = {case["id"]: case for case in report["cases"]}
    assert cases["missed"]["missing_findings"] == [
        {"type": "email", "value": "missing@example.com", "occurrence": 1},
    ]
    assert cases["unexpected"]["forbidden_finding_details"] == [
        {
            "type": "email",
            "category": "e-post",
            "text": "unexpected@example.com",
        },
    ]

    html = render_html_report(report)
    assert "Evalueringsrapport" in html
    assert "Standard skann" in html
    assert "missing@example.com" in html
    assert "unexpected@example.com" in html


def test_accuracy_cli_writes_machine_readable_report(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    output = tmp_path / "report.json"
    html_output = tmp_path / "report.html"
    _write_json(corpus / "taxonomy.json", {
        "email": {"category_prefixes": ["e-post"], "severity": "gul"},
    })
    _write_json(corpus / "cases" / "email.json", {
        "id": "nb-email-cli-001",
        "corpus_version": 1,
        "language": "nb",
        "profile": "normal",
        "text": "Kontakt: cli@example.com",
        "expected_status": "success",
        "expected_risk": "gul",
        "expected_findings": [{"type": "email", "value": "cli@example.com"}],
        "forbidden_findings": [],
        "tags": [],
    })
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")

    completed = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "evaluate_accuracy.py"),
            "--corpus", str(corpus),
            "--output", str(output),
            "--html-output", str(html_output),
        ],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["cases"] == 1
    assert "Evalueringsrapport" in html_output.read_text(encoding="utf-8")
    assert "Precision: 100.00%" in completed.stdout
    assert "Avvik: 0 av 1 caser" in completed.stdout


def test_accuracy_cli_default_corpus_works_from_scripts_directory() -> None:
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")

    completed = subprocess.run(
        [sys.executable, "evaluate_accuracy.py"],
        cwd=repo / "scripts",
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Caser: 38" in completed.stdout
