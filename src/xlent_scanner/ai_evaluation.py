"""Modellspesifikk evaluering av lokal AI-dybdeskann."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

from xlent_scanner import __version__
from xlent_scanner.deep_scanner import (
    cancel_deep_scan,
    get_deep_scan_status,
    ollama_status,
    start_deep_scan,
)
from xlent_scanner.evaluation import CorpusValidationError


class AIExecutionError(RuntimeError):
    """AI-kjøringen kunne ikke fullføres og skal ikke telles som et kvalitetsavvik."""


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusValidationError(f"Kan ikke lese {path}: {exc}") from exc


def _normalized(value: object) -> str:
    return " ".join(str(value or "").replace("🤖", "").split()).casefold()


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _matches_type(category: str, finding_type: str, taxonomy: dict) -> bool:
    normalized_category = _normalized(category)
    return any(
        normalized_category.startswith(_normalized(prefix))
        for prefix in taxonomy[finding_type]["category_prefixes"]
    )


def _matches_expected(finding: dict, expected: dict, taxonomy: dict) -> bool:
    if not _matches_type(str(finding.get("category") or ""), expected["type"], taxonomy):
        return False
    expected_value = expected.get("value")
    if expected_value is None:
        return True
    actual = _normalized(finding.get("text")).strip(".,;:")
    return _normalized(expected_value).strip(".,;:") == actual


def _score_run(findings: list[dict], case: dict, taxonomy: dict) -> dict:
    unmatched = list(findings)
    missing: list[dict] = []
    counts_by_type: dict[str, Counter] = defaultdict(Counter)

    for expected in case.get("expected_findings", []):
        finding_type = expected["type"]
        if finding_type not in taxonomy:
            raise CorpusValidationError(f"Ukjent AI finding-type {finding_type!r}.")
        for occurrence in range(1, int(expected.get("count", 1)) + 1):
            match_index = next(
                (
                    index for index, finding in enumerate(unmatched)
                    if _matches_expected(finding, expected, taxonomy)
                ),
                None,
            )
            if match_index is None:
                detail = {"type": finding_type, "occurrence": occurrence}
                if "value" in expected:
                    detail["value"] = expected["value"]
                missing.append(detail)
                counts_by_type[finding_type]["false_negatives"] += 1
            else:
                unmatched.pop(match_index)
                counts_by_type[finding_type]["true_positives"] += 1

    forbidden_details: list[dict] = []
    for forbidden in case.get("forbidden_findings", []):
        finding_type = forbidden["type"]
        if finding_type not in taxonomy:
            raise CorpusValidationError(f"Ukjent AI forbidden-type {finding_type!r}.")
        forbidden_details.extend(
            {
                "type": finding_type,
                "category": finding.get("category", ""),
                "text": finding.get("text", ""),
            }
            for finding in findings
            if _matches_expected(finding, forbidden, taxonomy)
        )

    unexpected = []
    for finding in unmatched:
        finding_type = next(
            (
                key for key in taxonomy
                if _matches_type(str(finding.get("category") or ""), key, taxonomy)
            ),
            "_unmapped",
        )
        counts_by_type[finding_type]["false_positives"] += 1
        unexpected.append({
            "category": finding.get("category", ""),
            "text": finding.get("text", ""),
        })

    tp = sum(counts["true_positives"] for counts in counts_by_type.values())
    fp = len(unexpected)
    fn = len(missing)
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "forbidden_violations": len(forbidden_details),
        "missing_findings": missing,
        "unexpected_findings": unexpected,
        "forbidden_finding_details": forbidden_details,
        "counts_by_type": counts_by_type,
        "exact_match": fp == 0 and fn == 0 and not forbidden_details,
    }


def _model_metadata(model: str) -> dict:
    status = ollama_status()
    if not status.get("running"):
        raise AIExecutionError(status.get("error") or "Ollama kjører ikke.")
    if model not in status.get("models", []):
        raise AIExecutionError(f"Modellen {model!r} er ikke installert i Ollama.")
    details = next(
        (item for item in status.get("model_details", []) if item.get("name") == model),
        {},
    )
    return {
        "model": model,
        "model_digest": details.get("digest", ""),
        "ollama_base": status.get("ollama_base", ""),
    }


def _run_ai_scan(
    *,
    text: str,
    model: str,
    language: str,
    categories: list[str],
    min_confidence: str,
    timeout_seconds: float,
) -> tuple[list[dict], float]:
    started = time.monotonic()
    job_id = start_deep_scan(
        text,
        model,
        lang=language,
        categories=categories,
        min_confidence=min_confidence,
    )
    deadline = started + timeout_seconds
    while time.monotonic() < deadline:
        status = get_deep_scan_status(job_id)
        state = status.get("status")
        if state == "done":
            return list(status.get("findings") or []), round(time.monotonic() - started, 3)
        if state in {"cancelled", "error", "failed"}:
            raise AIExecutionError(f"AI-jobb {job_id} avsluttet med status {state}.")
        time.sleep(0.1)
    cancel_deep_scan(job_id)
    raise AIExecutionError(f"AI-jobb {job_id} brukte mer enn {timeout_seconds:g} sekunder.")


def evaluate_ai_corpus(
    corpus_root: str | Path,
    *,
    model: str,
    repetitions: int = 3,
    timeout_seconds: float = 300,
) -> dict:
    """Kjør et separat AI-korpus og returner modellspesifikk rapport."""
    if repetitions < 1:
        raise ValueError("repetitions må være minst 1.")
    root = Path(corpus_root)
    taxonomy = _load_json(root / "taxonomy.json")
    if not isinstance(taxonomy, dict):
        raise CorpusValidationError("taxonomy.json må være et JSON-objekt.")
    schema_path = root / "case.schema.json"
    validator = None
    if schema_path.is_file():
        schema = _load_json(schema_path)
        if not isinstance(schema, dict):
            raise CorpusValidationError("case.schema.json må være et JSON-objekt.")
        validator = Draft202012Validator(schema)
    case_paths = sorted((root / "cases").rglob("*.json"))
    if not case_paths:
        raise CorpusValidationError(f"Fant ingen AI-caser under {root / 'cases'}.")

    model_metadata = _model_metadata(model)
    totals = Counter()
    type_totals: dict[str, Counter] = defaultdict(Counter)
    case_reports: list[dict] = []
    corpus_versions: set[int] = set()

    for path in case_paths:
        case = _load_json(path)
        if not isinstance(case, dict):
            raise CorpusValidationError(f"{path}: caset må være et JSON-objekt.")
        errors = (
            sorted(validator.iter_errors(case), key=lambda error: list(error.path))
            if validator else []
        )
        if errors:
            raise CorpusValidationError(
                f"{path}: " + "; ".join(error.message for error in errors)
            )
        corpus_versions.add(int(case["corpus_version"]))

        run_results = []
        signatures = set()
        for run_number in range(1, repetitions + 1):
            findings, elapsed = _run_ai_scan(
                text=str(case["text"]),
                model=model,
                language=str(case["language"]),
                categories=list(case["categories"]),
                min_confidence=str(case.get("min_confidence", "medium")),
                timeout_seconds=timeout_seconds,
            )
            score = _score_run(findings, case, taxonomy)
            for finding_type, counts in score.pop("counts_by_type").items():
                type_totals[finding_type].update(counts)
            score["run"] = run_number
            score["elapsed_seconds"] = elapsed
            score["findings"] = findings
            run_results.append(score)
            signatures.add(tuple(sorted(
                (_normalized(f.get("category")), _normalized(f.get("text")))
                for f in findings
            )))
            totals.update({
                "runs": 1,
                "successful_runs": 1,
                "true_positives": score["true_positives"],
                "false_positives": score["false_positives"],
                "false_negatives": score["false_negatives"],
                "forbidden_violations": score["forbidden_violations"],
                "exact_run_matches": int(score["exact_match"]),
            })

        case_reports.append({
            "id": case["id"],
            "source": path.relative_to(root).as_posix(),
            "language": case["language"],
            "profile": "ai_deep",
            "tags": case.get("tags", []),
            "true_positives": sum(run["true_positives"] for run in run_results),
            "false_positives": sum(run["false_positives"] for run in run_results),
            "false_negatives": sum(run["false_negatives"] for run in run_results),
            "risk_expected": "ikke relevant",
            "risk_actual": "ikke relevant",
            "status_expected": "done",
            "status_actual": "done",
            "forbidden_violations": sum(run["forbidden_violations"] for run in run_results),
            "missing_findings": [
                {**finding, "run": run["run"]}
                for run in run_results for finding in run["missing_findings"]
            ],
            "unexpected_findings": [
                {**finding, "run": run["run"]}
                for run in run_results for finding in run["unexpected_findings"]
            ],
            "forbidden_finding_details": [
                {**finding, "run": run["run"]}
                for run in run_results for finding in run["forbidden_finding_details"]
            ],
            "exact_run_matches": sum(run["exact_match"] for run in run_results),
            "stable": len(signatures) == 1,
            "run_results": run_results,
        })

    tp = totals["true_positives"]
    fp = totals["false_positives"]
    fn = totals["false_negatives"]
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    summary = {
        "cases": len(case_reports),
        "runs": totals["runs"],
        "successful_runs": totals["successful_runs"],
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
        "exact_run_matches": totals["exact_run_matches"],
        "exact_match_rate": _ratio(totals["exact_run_matches"], totals["runs"]),
        "risk_matches": 0,
        "status_matches": len(case_reports),
        "forbidden_violations": totals["forbidden_violations"],
    }
    by_type = {}
    for finding_type, counts in sorted(type_totals.items()):
        type_tp = counts["true_positives"]
        type_fp = counts["false_positives"]
        type_fn = counts["false_negatives"]
        type_precision = _ratio(type_tp, type_tp + type_fp)
        type_recall = _ratio(type_tp, type_tp + type_fn)
        by_type[finding_type] = {
            "true_positives": type_tp,
            "false_positives": type_fp,
            "false_negatives": type_fn,
            "precision": type_precision,
            "recall": type_recall,
            "f1": _ratio(
                2 * type_precision * type_recall,
                type_precision + type_recall,
            ),
        }
    return {
        "metadata": {
            "scanner_version": __version__,
            "corpus_versions": sorted(corpus_versions),
            "scan_mode": "ai_deep",
            **model_metadata,
            "repetitions": repetitions,
        },
        "summary": summary,
        "by_type": by_type,
        "cases": case_reports,
    }
