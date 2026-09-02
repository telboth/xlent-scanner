"""Lokalt, deterministisk evalueringsprogram for scannerens syntetiske korpus."""
from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from html import escape
from pathlib import Path

from jsonschema import Draft202012Validator

from xlent_scanner import __version__
from xlent_scanner.scanner import scan_text


class CorpusValidationError(ValueError):
    """Korpuset kan ikke evalueres fordi fasiten er ugyldig."""


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split()).casefold()


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusValidationError(f"Kan ikke lese {path}: {exc}") from exc


def _matches_type(category: str, finding_type: str, taxonomy: dict) -> bool:
    definition = taxonomy[finding_type]
    normalized_category = _normalized(category)
    return any(
        normalized_category.startswith(_normalized(prefix))
        for prefix in definition["category_prefixes"]
    )


def _matches_expected(finding, expected: dict, taxonomy: dict) -> bool:
    if not _matches_type(finding.category, expected["type"], taxonomy):
        return False
    expected_value = expected.get("value")
    if expected_value is None:
        return True
    values = {_normalized(finding.text), _normalized(finding.raw_text)}
    return _normalized(expected_value) in values


def _validate_case(case: dict, path: Path) -> None:
    required = {
        "id", "corpus_version", "language", "text", "expected_status",
        "expected_risk", "expected_findings",
    }
    missing = sorted(required - case.keys())
    if missing:
        raise CorpusValidationError(
            f"{path}: mangler obligatoriske felt: {', '.join(missing)}."
        )


def _validate_against_schema(case: dict, path: Path, validator) -> None:
    if validator is None:
        return
    errors = sorted(validator.iter_errors(case), key=lambda error: list(error.path))
    if not errors:
        return
    details = "; ".join(error.message for error in errors)
    raise CorpusValidationError(f"{path}: {details}")


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _expected_detail(expected: dict, occurrence: int) -> dict:
    detail = {"type": expected["type"]}
    if "value" in expected:
        detail["value"] = expected["value"]
    detail["occurrence"] = occurrence
    return detail


def _actual_detail(finding, finding_type: str | None = None) -> dict:
    detail = {"category": finding.category, "text": finding.text}
    if finding_type is not None:
        detail = {"type": finding_type, **detail}
    return detail


def evaluate_corpus(corpus_root: str | Path) -> dict:
    """Kjør alle JSON-caser i et korpus og returner en maskinlesbar rapport."""
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
    totals = Counter()
    type_totals: dict[str, Counter] = defaultdict(Counter)
    case_reports: list[dict] = []
    corpus_versions: set[int] = set()

    for path in case_paths:
        case = _load_json(path)
        if not isinstance(case, dict):
            raise CorpusValidationError(f"{path}: caset må være et JSON-objekt.")
        _validate_case(case, path)
        _validate_against_schema(case, path, validator)
        corpus_versions.add(int(case["corpus_version"]))

        result = scan_text(
            str(case["text"]),
            language=str(case["language"]),
            scan_profile=str(case.get("profile", "normal")),
        )
        findings = [finding for finding in result.findings if finding.severity != "grønn"]
        unmatched = list(findings)
        tp = 0
        fn = 0
        missing_findings: list[dict] = []

        for expected in case.get("expected_findings", []):
            finding_type = expected["type"]
            if finding_type not in taxonomy:
                raise CorpusValidationError(f"{path}: ukjent finding-type {finding_type!r}.")
            for occurrence in range(1, int(expected.get("count", 1)) + 1):
                match_index = next(
                    (index for index, finding in enumerate(unmatched)
                     if _matches_expected(finding, expected, taxonomy)),
                    None,
                )
                if match_index is None:
                    fn += 1
                    type_totals[finding_type]["false_negatives"] += 1
                    missing_findings.append(_expected_detail(expected, occurrence))
                else:
                    unmatched.pop(match_index)
                    tp += 1
                    type_totals[finding_type]["true_positives"] += 1

        forbidden_finding_details: list[dict] = []
        for forbidden in case.get("forbidden_findings", []):
            finding_type = forbidden["type"]
            if finding_type not in taxonomy:
                raise CorpusValidationError(f"{path}: ukjent forbidden-type {finding_type!r}.")
            forbidden_finding_details.extend(
                _actual_detail(finding, finding_type)
                for finding in findings
                if _matches_expected(finding, forbidden, taxonomy)
            )
        forbidden_violations = len(forbidden_finding_details)

        fp = len(unmatched)
        for finding in unmatched:
            finding_type = next(
                (key for key in taxonomy if _matches_type(finding.category, key, taxonomy)),
                "_unmapped",
            )
            type_totals[finding_type]["false_positives"] += 1
        totals.update({
            "cases": 1,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "risk_matches": int(result.risk_level == case.get("expected_risk")),
            "status_matches": int(result.scan_status == case.get("expected_status")),
            "forbidden_violations": forbidden_violations,
        })
        case_reports.append({
            "id": case.get("id", path.stem),
            "source": path.relative_to(root).as_posix(),
            "language": case.get("language"),
            "profile": case.get("profile", "normal"),
            "tags": case.get("tags", []),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "risk_expected": case.get("expected_risk"),
            "risk_actual": result.risk_level,
            "status_expected": case.get("expected_status"),
            "status_actual": result.scan_status,
            "forbidden_violations": forbidden_violations,
            "missing_findings": missing_findings,
            "forbidden_finding_details": forbidden_finding_details,
            "unexpected_findings": [
                _actual_detail(finding)
                for finding in unmatched
            ],
        })

    tp = totals["true_positives"]
    fp = totals["false_positives"]
    fn = totals["false_negatives"]
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    summary = dict(totals)
    summary["precision"] = precision
    summary["recall"] = recall
    summary["f1"] = _ratio(2 * precision * recall, precision + recall)
    ordered_summary = {
        key: summary.get(key, 0)
        for key in (
            "cases", "true_positives", "false_positives", "false_negatives",
            "precision", "recall", "f1", "risk_matches", "status_matches",
            "forbidden_violations",
        )
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
            "scan_mode": "standard",
        },
        "summary": ordered_summary,
        "by_type": by_type,
        "cases": case_reports,
    }


def _percent(value: object) -> str:
    return f"{float(value or 0):.1%}"


def _case_has_issues(case: dict) -> bool:
    return any((
        case.get("false_positives", 0),
        case.get("false_negatives", 0),
        case.get("forbidden_violations", 0),
        case.get("risk_expected") != case.get("risk_actual"),
        case.get("status_expected") != case.get("status_actual"),
    ))


def _finding_label(finding: dict) -> str:
    finding_type = finding.get("type") or finding.get("category") or "ukjent"
    value = finding.get("value") or finding.get("text")
    return f"{finding_type}: {value}" if value else str(finding_type)


def render_html_report(report: dict) -> str:
    """Lag en selvstendig, lokal HTML-rapport uten eksterne ressurser."""
    metadata = report["metadata"]
    summary = report["summary"]
    issue_cases = [case for case in report["cases"] if _case_has_issues(case)]
    detail_cases = (
        report["cases"] if metadata.get("scan_mode") == "ai_deep" else issue_cases
    )
    mode_label = {
        "standard": "Standard skann",
        "ai_deep": "AI-dybdeskann",
    }.get(metadata.get("scan_mode"), str(metadata.get("scan_mode", "Ukjent modus")))

    type_rows = []
    for finding_type, metrics in report["by_type"].items():
        css_class = "issue" if metrics["false_positives"] or metrics["false_negatives"] else ""
        type_rows.append(
            f'<tr class="{css_class}"><td>{escape(finding_type)}</td>'
            f'<td>{metrics["true_positives"]}</td>'
            f'<td>{metrics["false_positives"]}</td>'
            f'<td>{metrics["false_negatives"]}</td>'
            f'<td>{_percent(metrics["precision"])}</td>'
            f'<td>{_percent(metrics["recall"])}</td>'
            f'<td>{_percent(metrics["f1"])}</td></tr>'
        )

    case_sections = []
    for case in detail_cases:
        details = []
        if case.get("missing_findings"):
            items = "".join(
                f"<li>{escape(_finding_label(item))}</li>"
                for item in case["missing_findings"]
            )
            details.append(f"<h4>Manglende funn (FN)</h4><ul>{items}</ul>")
        if case.get("unexpected_findings"):
            items = "".join(
                f"<li>{escape(_finding_label(item))}</li>"
                for item in case["unexpected_findings"]
            )
            details.append(f"<h4>Uventede funn (FP)</h4><ul>{items}</ul>")
        if case.get("forbidden_finding_details"):
            items = "".join(
                f"<li>{escape(_finding_label(item))}</li>"
                for item in case["forbidden_finding_details"]
            )
            details.append(f"<h4>Eksplisitt forbudte funn</h4><ul>{items}</ul>")
        tags = " ".join(
            f'<span class="tag">{escape(str(tag))}</span>' for tag in case.get("tags", [])
        )
        ai_run_detail = ""
        if metadata.get("scan_mode") == "ai_deep":
            stable = "ja" if case.get("stable") else "nei"
            ai_run_detail = (
                f' · Stabile modellresultater: {stable} · Eksakte kjøringer: '
                f'{case.get("exact_run_matches", 0)}/{metadata.get("repetitions", 0)}'
            )
        case_class = "case" if _case_has_issues(case) else "case case-ok"
        case_sections.append(
            f'<section class="{case_class}">'
            f'<div class="case-head"><div><h3>{escape(str(case["id"]))}</h3>'
            f'<div class="tags">{tags}</div></div>'
            f'<div class="counts">TP {case["true_positives"]} · '
            f'FP {case["false_positives"]} · FN {case["false_negatives"]}</div></div>'
            f'<p class="meta">Risiko: {escape(str(case["risk_expected"]))} forventet / '
            f'{escape(str(case["risk_actual"]))} faktisk · '
            f'Status: {escape(str(case["status_expected"]))} forventet / '
            f'{escape(str(case["status_actual"]))} faktisk · '
            f'Kilde: {escape(str(case.get("source", "")))}{escape(ai_run_detail)}</p>'
            f'{"".join(details)}</section>'
        )

    all_case_rows = "".join(
        f'<tr class="{"issue" if _case_has_issues(case) else ""}">'
        f'<td>{escape(str(case["id"]))}</td><td>{escape(str(case.get("profile", "")))}</td>'
        f'<td>{case["true_positives"]}</td><td>{case["false_positives"]}</td>'
        f'<td>{case["false_negatives"]}</td>'
        f'<td>{escape(str(case["risk_expected"]))} / {escape(str(case["risk_actual"]))}</td></tr>'
        for case in report["cases"]
    )
    issue_html = "".join(case_sections) or '<p class="ok">Ingen avvik funnet.</p>'
    detail_heading = (
        "AI-caser i detalj"
        if metadata.get("scan_mode") == "ai_deep"
        else "Avvik i detalj"
    )

    model_label = (
        f" · modell {escape(str(metadata['model']))}"
        if metadata.get("model") else ""
    )
    return f"""<!doctype html>
<html lang="nb"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XLENT Scanner – evalueringsrapport</title>
<style>
:root{{--bg:#f4f6f5;--surface:#fff;--ink:#172321;--muted:#60706c;--accent:#536764;--gold:#c7a55b;--bad:#9b3b32;--line:#dce3e1}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1120px;margin:auto;padding:42px 24px 64px}} header{{background:var(--accent);color:#fff;padding:30px;border-radius:18px}}
h1{{margin:0 0 5px;font-size:30px}} h2{{margin:34px 0 14px}} h3{{margin:0 0 6px}} h4{{margin:15px 0 5px;font-size:14px}}
.subtitle,.meta{{color:var(--muted)}} header .subtitle{{color:#dfe7e5}} .cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:18px}}
.card{{background:var(--surface);padding:17px;border-radius:12px;border:1px solid var(--line)}} .card b{{display:block;font-size:24px}} .card span{{color:var(--muted)}}
.panel,.case{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px;margin:12px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%;min-width:660px}} th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:right}} th:first-child,td:first-child{{text-align:left}} th{{color:var(--muted);font-size:12px;text-transform:uppercase}}
tr.issue td{{background:#fff7f4}} .case{{border-left:5px solid var(--bad)}} .case-head{{display:flex;justify-content:space-between;gap:20px}} .counts{{font-weight:700;white-space:nowrap}}
.case.case-ok{{border-left-color:#2e6b4c}} .tag{{display:inline-block;background:#e8eeec;border-radius:999px;padding:2px 8px;margin:0 4px 4px 0;font-size:12px}} ul{{margin:4px 0 0;padding-left:22px}} .ok{{color:#2e6b4c;font-weight:700}}
.note{{border-left:4px solid var(--gold);padding:8px 14px;background:#fffaf0}} @media(max-width:760px){{.cards{{grid-template-columns:repeat(2,1fr)}}.case-head{{display:block}}}}
</style></head><body><main>
<header><h1>Evalueringsrapport</h1><div class="subtitle">XLENT Scanner {escape(str(metadata.get("scanner_version", "")))} · {escape(mode_label)}{model_label} · korpus {escape(", ".join(map(str, metadata.get("corpus_versions", []))))}</div></header>
<div class="cards">
<div class="card"><b>{summary["cases"]}</b><span>Caser</span></div><div class="card"><b>{_percent(summary["precision"])}</b><span>Precision</span></div>
<div class="card"><b>{_percent(summary["recall"])}</b><span>Recall</span></div><div class="card"><b>{_percent(summary["f1"])}</b><span>F1</span></div>
<div class="card"><b>{len(issue_cases)}</b><span>Caser med avvik</span></div></div>
<p class="note"><b>Lesing:</b> FP er et uventet funn som kan skape støy. FN er et forventet funn scanneren overså. Moduser skal sammenlignes i separate rapporter.</p>
<h2>Resultat per kategori</h2><div class="panel"><table><thead><tr><th>Kategori</th><th>TP</th><th>FP</th><th>FN</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{"".join(type_rows)}</tbody></table></div>
<h2>{detail_heading}</h2>{issue_html}
<h2>Alle caser</h2><div class="panel"><table><thead><tr><th>Case</th><th>Profil</th><th>TP</th><th>FP</th><th>FN</th><th>Risiko forventet / faktisk</th></tr></thead><tbody>{all_case_rows}</tbody></table></div>
</main></body></html>"""
