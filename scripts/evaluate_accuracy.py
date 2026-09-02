"""Kjør det syntetiske evalueringskorpuset og skriv en lokal rapport."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xlent_scanner.evaluation import (
    CorpusValidationError,
    evaluate_corpus,
    render_html_report,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=_REPOSITORY_ROOT / "evaluation",
        help="Korpusrot med taxonomy.json og cases/ (standard: repositoryets evaluation/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Valgfri fil for komplett JSON-rapport.",
    )
    parser.add_argument(
        "--html-output",
        type=Path,
        help="Valgfri fil for en selvstendig, lesbar HTML-rapport.",
    )
    return parser


def _case_has_issues(case: dict) -> bool:
    return any((
        case["false_positives"],
        case["false_negatives"],
        case["forbidden_violations"],
        case["risk_expected"] != case["risk_actual"],
        case["status_expected"] != case["status_actual"],
    ))


def _finding_label(finding: dict) -> str:
    finding_type = finding.get("type") or finding.get("category") or "ukjent"
    value = finding.get("value") or finding.get("text")
    return f"{finding_type}: {value}" if value else str(finding_type)


def _print_issues(report: dict) -> None:
    issue_cases = [case for case in report["cases"] if _case_has_issues(case)]
    print(f"Avvik: {len(issue_cases)} av {report['summary']['cases']} caser")
    for case in issue_cases:
        print(f"\n- {case['id']} (TP {case['true_positives']}, "
              f"FP {case['false_positives']}, FN {case['false_negatives']})")
        if case["risk_expected"] != case["risk_actual"]:
            print(f"  Risiko: forventet {case['risk_expected']}, faktisk {case['risk_actual']}")
        if case["status_expected"] != case["status_actual"]:
            print(f"  Status: forventet {case['status_expected']}, faktisk {case['status_actual']}")
        for finding in case["missing_findings"]:
            print(f"  Mangler: {_finding_label(finding)}")
        for finding in case["unexpected_findings"]:
            print(f"  Uventet: {_finding_label(finding)}")
        for finding in case["forbidden_finding_details"]:
            print(f"  Forbudt: {_finding_label(finding)}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = evaluate_corpus(args.corpus)
    except CorpusValidationError as exc:
        print(f"Ugyldig evalueringskorpus: {exc}")
        return 2

    summary = report["summary"]
    print(f"Caser: {summary['cases']}")
    print(
        "TP/FP/FN: "
        f"{summary['true_positives']}/"
        f"{summary['false_positives']}/"
        f"{summary['false_negatives']}"
    )
    print(f"Precision: {summary['precision']:.2%}")
    print(f"Recall: {summary['recall']:.2%}")
    print(f"F1: {summary['f1']:.2%}")
    print(f"Korrekt risiko: {summary['risk_matches']}/{summary['cases']}")
    _print_issues(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON-rapport: {args.output}")
    if args.html_output:
        args.html_output.parent.mkdir(parents=True, exist_ok=True)
        args.html_output.write_text(render_html_report(report), encoding="utf-8")
        print(f"HTML-rapport: {args.html_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
