"""Fargekodet funnliste med hviteliste-handling."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from xlent_scanner.models import Finding
from xlent_scanner.whitelist import add_to_whitelist, category_allows_whitelist

from lib.scan_runner import clear_scan_cache

_BG: dict[str, str] = {
    "svart": "#d1d5db",
    "rød":   "#fca5a5",
    "gul":   "#fde68a",
    "grønn": "#bbf7d0",
}
_ICON: dict[str, str] = {
    "svart": "⛔",
    "rød":   "🚫",
    "gul":   "⚠️",
    "grønn": "✅",
}
_ORDER = {"svart": 0, "rød": 1, "gul": 2, "grønn": 3}


def show_summary_badges(findings: list[Finding]) -> None:
    counts = Counter(f.severity for f in findings)
    parts = []
    for sev, icon in [("svart", "⛔"), ("rød", "🚫"), ("gul", "⚠️"), ("grønn", "✅")]:
        if counts.get(sev, 0):
            parts.append(f"{icon} **{counts[sev]}**")
    if parts:
        st.markdown("  &nbsp; ".join(parts))


def show_findings_table(
    findings: list[Finding],
    key: str = "tbl",
    allow_whitelist: bool = True,
) -> None:
    """Vis funn i fargekodet tabell. Med allow_whitelist kan brukeren velge rader
    og legge dem i hvitelisten i én handling."""
    if not findings:
        st.success("Ingen sensitive funn.")
        return

    sorted_findings = sorted(findings, key=lambda f: _ORDER.get(f.severity, 2))
    bg_colors = [_BG.get(f.severity, _BG["gul"]) for f in sorted_findings]

    rows = [
        {
            "Alv.": _ICON.get(f.severity, "⚠️"),
            "Kategori": f.category,
            "Verdi": f.text,
            "Kontekst": (f.context[:120] + "…") if len(f.context) > 120 else f.context,
        }
        for f in sorted_findings
    ]
    df = pd.DataFrame(rows)

    def _color_row(row: pd.Series) -> list[str]:
        color = bg_colors[int(row.name)]
        return [f"background-color: {color}; color: #1a1a1a"] * len(row)

    event = st.dataframe(
        df.style.apply(_color_row, axis=1),
        width="stretch",
        hide_index=True,
        key=key,
        on_select="rerun" if allow_whitelist else "ignore",
        selection_mode="multi-row" if allow_whitelist else None,
    )

    if allow_whitelist:
        selected_rows = getattr(event, "selection", {}).get("rows", []) if event else []
        if selected_rows:
            picks = [sorted_findings[i] for i in selected_rows]
            whitelistable = [f for f in picks if category_allows_whitelist(f.category)]
            skipped = len(picks) - len(whitelistable)
            label = f"✚ Legg {len(whitelistable)} valgte i hviteliste"
            if skipped:
                label += f" ({skipped} kan ikke hvitelistes)"
            if st.button(label, key=f"{key}_wl", disabled=not whitelistable):
                for f in whitelistable:
                    add_to_whitelist(f.raw_text or f.text)
                clear_scan_cache()
                st.success(f"La til {len(whitelistable)} i hvitelisten. Skanner på nytt…")
                st.rerun()


def findings_as_json(findings: list[Finding]) -> str:
    import json
    return json.dumps(
        [
            {
                "kategori": f.category,
                "verdi": f.text,
                "kontekst": f.context,
                "alvorlighet": f.severity,
            }
            for f in findings
        ],
        ensure_ascii=False,
        indent=2,
    )


def findings_as_csv(findings: list[Finding]) -> str:
    rows = [
        {
            "Alvorlighet": f.severity,
            "Kategori": f.category,
            "Verdi": f.text,
            "Kontekst": f.context,
        }
        for f in findings
    ]
    return pd.DataFrame(rows).to_csv(index=False)
