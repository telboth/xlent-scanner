"""Normalisering av AI-funn og utledning av anonymiserbare tekstverdier."""
from __future__ import annotations

import logging

from xlent_scanner.models import Finding

LOGGER = logging.getLogger("xlent_scanner")

_FINANCIAL_MARKERS = (
    "budsjett", "finans", "financial", "monetary", "pengebel", "penning",
    "money", "cost", "amount", "price", "total", "budget", "revenue",
    "fee", "rate", "invoice",
)


def _category_is_financial(category: str) -> bool:
    normalized = category.replace("🤖", "").strip().casefold()
    return any(marker in normalized for marker in _FINANCIAL_MARKERS)


def _append_unique(values: list[str], seen: set[str], value: str) -> None:
    value = str(value or "").strip()
    if not value:
        return
    key = value.casefold()
    if key not in seen:
        seen.add(key)
        values.append(value)


def financial_values_from_snippet(text: str) -> list[str]:
    if "|" not in text:
        return []
    values: list[str] = []
    seen: set[str] = set()
    try:
        from xlent_scanner.deep_scanner import (  # noqa: PLC0415
            _find_tabular_financial_values,
            _looks_like_financial_amount_cell,
        )

        for finding in _find_tabular_financial_values(text):
            _append_unique(values, seen, str(finding.get("text") or ""))
        for line in text.splitlines():
            if "|" not in line:
                continue
            for cell in line.strip().strip("|").split("|"):
                cell = cell.strip()
                if _looks_like_financial_amount_cell(cell):
                    _append_unique(values, seen, cell)
    except Exception as exc:
        LOGGER.warning("Klarte ikke å utlede finansielle AI-tabellverdier: %s", exc)
    return values


def findings_from_payload(data: dict) -> list[dict]:
    findings: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for raw in data.get("ai_findings") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        category = str(raw.get("category") or "🤖 AI-funn").strip()
        context = str(raw.get("context") or "").strip()
        key = (text.casefold(), category.casefold(), context.casefold())
        if key in seen:
            continue
        seen.add(key)
        findings.append({"text": text, "category": category, "context": context})

    for text in data.get("ai_texts") or []:
        text = str(text or "").strip()
        if not text:
            continue
        key = (text.casefold(), "🤖 ai-funn", "")
        if key in seen:
            continue
        seen.add(key)
        findings.append({"text": text, "category": "🤖 AI-funn", "context": ""})

    return findings


def replacement_texts(ai_findings: list[dict]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for finding in ai_findings:
        text = str(finding.get("text") or "").strip()
        category = str(finding.get("category") or "")
        context = str(finding.get("context") or "").strip()
        _append_unique(values, seen, text)
        if _category_is_financial(category):
            sources = (text, context, f"{context}\n{text}" if context else text)
            for source in sources:
                for value in financial_values_from_snippet(source):
                    _append_unique(values, seen, value)
    return values


def as_model_findings(ai_findings: list[dict]) -> list[Finding]:
    from xlent_scanner.risk import _category_severity  # noqa: PLC0415

    return [
        Finding(
            category=str(finding.get("category") or "🤖 AI-funn"),
            text=str(finding.get("text") or ""),
            context=str(finding.get("context") or ""),
            severity=(
                "grønn"
                if str(finding.get("severity") or "") == "grønn"
                else _category_severity(
                    str(finding.get("category") or "AI-funn").replace("🤖", "").strip()
                )
            ),
            raw_text=str(finding.get("text") or ""),
        )
        for finding in ai_findings
        if str(finding.get("text") or "").strip()
    ]
