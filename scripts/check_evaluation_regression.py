"""Sammenlign en standardrapport med en tidligere baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xlent_scanner.evaluation_gate import regression_failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    return parser


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} inneholder ikke et JSON-objekt.")
    return data


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        baseline = _read(args.baseline)
        current = _read(args.current)
        failures = regression_failures(current, baseline)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Kan ikke kontrollere evalueringsrapportene: {exc}")
        return 2

    if failures:
        print("Evalueringsport feilet:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Evalueringsport OK: ingen svekkelse mot baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
