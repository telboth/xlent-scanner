"""Regresjonsport for deterministiske standard-skannrapporter."""
from __future__ import annotations


def regression_failures(current: dict, baseline: dict) -> list[str]:
    """Returner konkrete brudd; tom liste betyr at rapporten passerer."""
    current_mode = current.get("metadata", {}).get("scan_mode")
    baseline_mode = baseline.get("metadata", {}).get("scan_mode")
    if current_mode != "standard" or baseline_mode != "standard":
        return ["Regresjonsporten krever to rapporter for standard-skann."]

    now = current["summary"]
    before = baseline["summary"]
    failures: list[str] = []
    current_cases = {
        str(case.get("id")): case
        for case in current.get("cases", [])
        if case.get("id")
    }
    for baseline_case in baseline.get("cases", []):
        case_id = str(baseline_case.get("id") or "")
        if not case_id:
            continue
        current_case = current_cases.get(case_id)
        if current_case is None:
            failures.append(f"Baseline-caset mangler: {case_id}.")
        elif (
            baseline_case.get("spec_digest")
            and current_case.get("spec_digest") != baseline_case.get("spec_digest")
        ):
            failures.append(f"Baseline-caset er endret: {case_id}.")
    if now["cases"] < before["cases"]:
        failures.append(
            f"Korpuset har færre caser: {now['cases']} mot {before['cases']}."
        )
    if now["false_negatives"] > before["false_negatives"]:
        failures.append(
            "Antall falske negative økte: "
            f"{now['false_negatives']} mot {before['false_negatives']}."
        )
    if float(now["f1"]) + 1e-9 < float(before["f1"]):
        failures.append(f"F1 falt: {now['f1']:.2%} mot {before['f1']:.2%}.")

    current_risk_mismatches = now["cases"] - now["risk_matches"]
    baseline_risk_mismatches = before["cases"] - before["risk_matches"]
    if current_risk_mismatches > baseline_risk_mismatches:
        failures.append(
            "Antall risikoavvik økte: "
            f"{current_risk_mismatches} mot {baseline_risk_mismatches}."
        )
    return failures
