"""Trafikklysbadge for risikonivå."""
from __future__ import annotations

import streamlit as st

_STYLE: dict[str, tuple[str, str, str]] = {
    "grønn": ("#dcfce7", "#15803d", "🟢"),
    "gul":   ("#fef9c3", "#854d0e", "🟡"),
    "rød":   ("#fee2e2", "#b91c1c", "🔴"),
    "svart": ("#1f2937", "#f9fafb", "⚫"),
}

_LABEL: dict[str, str] = {
    "grønn": "Grønn — Ingen sensitive funn",
    "gul":   "Gul — Sensitive funn, vurder bruk",
    "rød":   "Rød — Høy risiko, del ikke",
    "svart": "Svart — Kritisk, del ikke",
}


def show_risk_badge(risk_level: str, summary: str = "", action: str = "") -> None:
    bg, fg, icon = _STYLE.get(risk_level, _STYLE["grønn"])
    label = _LABEL.get(risk_level, risk_level)
    extra = ""
    if summary:
        extra += f'<div style="font-weight:400;font-size:13px;margin-top:4px">{summary}</div>'
    if action:
        extra += f'<div style="font-weight:400;font-size:12px;opacity:0.85;margin-top:2px">{action}</div>'
    st.markdown(
        f'<div style="background:{bg};color:{fg};padding:12px 18px;border-radius:8px;'
        f'font-weight:600;font-size:15px;margin:8px 0">{icon} {label}{extra}</div>',
        unsafe_allow_html=True,
    )
