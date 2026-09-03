import json
from pathlib import Path

from xlent_scanner import ai_evaluation
from xlent_scanner.evaluation import render_html_report


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_ai_evaluation_records_model_repetitions_and_stability(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_json(tmp_path / "taxonomy.json", {
        "person_name": {"category_prefixes": ["navn (person)"], "severity": "gul"},
    })
    _write_json(tmp_path / "cases" / "name.json", {
        "id": "nb-ai-name-001",
        "corpus_version": 1,
        "language": "nb",
        "text": "Prosjektleder Kari Nordmann godkjente planen.",
        "categories": ["navn"],
        "min_confidence": "medium",
        "expected_findings": [
            {"type": "person_name", "value": "Kari Nordmann"},
        ],
        "forbidden_findings": [],
        "tags": ["positive"],
    })
    monkeypatch.setattr(
        ai_evaluation,
        "_model_metadata",
        lambda model: {"model": model, "model_digest": "sha256:test", "ollama_base": "local"},
    )
    monkeypatch.setattr(
        ai_evaluation,
        "_run_ai_scan",
        lambda **kwargs: ([{
            "category": "🤖 Navn (person)",
            "text": "Kari Nordmann",
            "confidence": "high",
        }], 0.25),
    )

    report = ai_evaluation.evaluate_ai_corpus(
        tmp_path,
        model="llama3.2:3b",
        repetitions=2,
    )

    assert report["metadata"] == {
        "scanner_version": "1.9.19",
        "corpus_versions": [1],
        "scan_mode": "ai_deep",
        "model": "llama3.2:3b",
        "model_digest": "sha256:test",
        "ollama_base": "local",
        "repetitions": 2,
    }
    assert report["summary"]["cases"] == 1
    assert report["summary"]["runs"] == 2
    assert report["summary"]["true_positives"] == 2
    assert report["summary"]["false_positives"] == 0
    assert report["summary"]["false_negatives"] == 0
    assert report["summary"]["exact_run_matches"] == 2
    assert report["summary"]["exact_match_rate"] == 1.0
    assert report["cases"][0]["run_results"][0]["elapsed_seconds"] == 0.25
    html = render_html_report(report)
    assert "modell llama3.2:3b" in html
    assert "Stabile modellresultater: ja" in html


def test_ai_evaluation_keeps_runs_separate_when_model_varies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_json(tmp_path / "taxonomy.json", {
        "person_name": {"category_prefixes": ["navn"], "severity": "gul"},
    })
    _write_json(tmp_path / "cases" / "name.json", {
        "id": "variable",
        "corpus_version": 1,
        "language": "nb",
        "text": "Kari Nordmann deltok.",
        "categories": ["navn"],
        "expected_findings": [{"type": "person_name", "value": "Kari Nordmann"}],
        "forbidden_findings": [],
        "tags": [],
    })
    monkeypatch.setattr(
        ai_evaluation,
        "_model_metadata",
        lambda model: {"model": model, "model_digest": "test", "ollama_base": "local"},
    )
    outputs = iter([
        ([{"category": "🤖 Navn", "text": "Kari Nordmann"}], 0.1),
        ([], 0.1),
    ])
    monkeypatch.setattr(ai_evaluation, "_run_ai_scan", lambda **kwargs: next(outputs))

    report = ai_evaluation.evaluate_ai_corpus(tmp_path, model="test", repetitions=2)

    assert report["summary"]["true_positives"] == 1
    assert report["summary"]["false_negatives"] == 1
    assert report["summary"]["exact_run_matches"] == 1
    assert report["summary"]["exact_match_rate"] == 0.5
    assert report["cases"][0]["stable"] is False
