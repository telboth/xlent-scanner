import json
import os
import subprocess
import sys
from pathlib import Path

from xlent_scanner.evaluation_gate import regression_failures


def _report(*, cases=30, false_negatives=1, f1=0.85, risk_matches=28) -> dict:
    return {
        "metadata": {"scan_mode": "standard"},
        "summary": {
            "cases": cases,
            "false_negatives": false_negatives,
            "f1": f1,
            "risk_matches": risk_matches,
        },
        "cases": [
            {"id": f"case-{index}", "spec_digest": f"digest-{index}"}
            for index in range(cases)
        ],
    }


def test_regression_gate_accepts_equal_or_better_report() -> None:
    baseline = _report()
    current = _report(cases=38, false_negatives=0, f1=0.95, risk_matches=38)

    assert regression_failures(current, baseline) == []


def test_regression_gate_reports_each_guardrail() -> None:
    baseline = _report()
    current = _report(cases=29, false_negatives=2, f1=0.80, risk_matches=26)

    failures = regression_failures(current, baseline)

    assert any("færre caser" in failure for failure in failures)
    assert any("falske negative" in failure for failure in failures)
    assert any("F1" in failure for failure in failures)
    assert any("risikoavvik" in failure for failure in failures)


def test_regression_gate_rejects_removed_or_changed_baseline_cases() -> None:
    baseline = _report(cases=2, false_negatives=0, f1=1.0, risk_matches=2)
    current = _report(cases=2, false_negatives=0, f1=1.0, risk_matches=2)
    current["cases"] = [
        {"id": "case-0", "spec_digest": "changed"},
        {"id": "replacement", "spec_digest": "new"},
    ]

    failures = regression_failures(current, baseline)

    assert any("endret" in failure and "case-0" in failure for failure in failures)
    assert any("mangler" in failure and "case-1" in failure for failure in failures)


def test_regression_gate_cli_returns_nonzero_for_regression(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    baseline_path.write_text(json.dumps(_report()), encoding="utf-8")
    current_path.write_text(
        json.dumps(_report(false_negatives=2)),
        encoding="utf-8",
    )
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")

    completed = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "check_evaluation_regression.py"),
            "--baseline", str(baseline_path),
            "--current", str(current_path),
        ],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "falske negative" in completed.stdout


def test_quality_workflow_runs_standard_evaluation_gate() -> None:
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts/evaluate_accuracy.py" in workflow
    assert "scripts/check_evaluation_regression.py" in workflow
    assert "evaluation/baselines/v1.9.16.json" in workflow
