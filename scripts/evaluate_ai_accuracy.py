"""Kjør det separate evalueringskorpuset for lokal AI-dybdeskann."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xlent_scanner.ai_evaluation import AIExecutionError, evaluate_ai_corpus
from xlent_scanner.evaluation import CorpusValidationError, render_html_report

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=_REPOSITORY_ROOT / "evaluation_ai")
    parser.add_argument("--model", default="llama3.2:3b")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--html-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = evaluate_ai_corpus(
            args.corpus,
            model=args.model,
            repetitions=args.repetitions,
            timeout_seconds=args.timeout,
        )
    except (CorpusValidationError, AIExecutionError, ValueError) as exc:
        print(f"AI-evaluering feilet: {exc}")
        return 2

    summary = report["summary"]
    print(f"Modell: {report['metadata']['model']}")
    print(f"Caser/kjøringer: {summary['cases']}/{summary['runs']}")
    print(
        "TP/FP/FN: "
        f"{summary['true_positives']}/"
        f"{summary['false_positives']}/"
        f"{summary['false_negatives']}"
    )
    print(f"Precision: {summary['precision']:.2%}")
    print(f"Recall: {summary['recall']:.2%}")
    print(f"F1: {summary['f1']:.2%}")
    print(f"Eksakte kjøringer: {summary['exact_run_matches']}/{summary['runs']}")

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
