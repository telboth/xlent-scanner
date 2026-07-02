"""Delt UI: innstillinger-sidebar og resultatvisning."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from xlent_scanner.models import ScanResult

from lib.category_labels import (
    category_columns,
    default_categories,
    label_for,
)
from lib.exports import build_html_report, build_pdf_report, report_filename
from lib.findings_table import (
    findings_as_csv,
    findings_as_json,
    show_findings_table,
    show_summary_badges,
)
from lib.deep_scan_ui import deep_scan_controls, run_deep_scan_section
from lib.redaction_ui import redaction_panel
from lib.risk_badge import show_risk_badge

LANG_OPTIONS = {
    "Automatisk": "auto",
    "Norsk": "nb",
    "Svensk": "sv",
    "Dansk": "da",
    "Engelsk": "en",
    "Tysk": "de",
    "Fransk": "fr",
    "Spansk": "es",
}


@dataclass(frozen=True)
class ScanSettings:
    language: str
    scan_profile: str
    categories: tuple[str, ...]
    pdf_mode: str
    ocr: bool
    ignore_xlent: bool
    deep_scan: bool = False
    ai_model: str = ""
    min_confidence: str = "medium"
    anonymize_terms: tuple[str, ...] = ()


def settings_sidebar() -> ScanSettings:
    """Tegn innstillinger i sidebar med fornuftige defaults og returner valgene.

    Språk er alltid Automatisk og profil er alltid «normal» (skjult for brukeren).
    Kategorier vises som avkrysningsbokser.
    """
    with st.sidebar:
        st.markdown("### Kategorier")
        st.caption("Velg hva som skal skannes og anonymiseres.")
        defaults = set(default_categories())
        selected_categories: list[str] = []
        cols = st.columns(3)
        for col, keys in zip(cols, category_columns(), strict=True):
            with col:
                for key in keys:
                    if st.checkbox(label_for(key), value=key in defaults, key=f"cat_{key}"):
                        selected_categories.append(key)

        with st.expander("Ord og uttrykk som skal anonymiseres", expanded=False):
            anon_text = st.text_area(
                "Egendefinerte ord/uttrykk",
                placeholder="Ett ord eller uttrykk per linje …",
                help="Disse maskeres i tillegg til de oppdagede funnene ved anonymisering.",
                key="cfg_anon_terms",
                label_visibility="collapsed",
            )
        anonymize_terms = tuple(line.strip() for line in anon_text.splitlines() if line.strip())

        with st.expander("Avansert", expanded=False):
            pdf_mode = st.radio(
                "Scan-modus",
                options=["fast", "auto", "advanced"],
                index=1,  # auto
                format_func={
                    "fast": "Rask",
                    "auto": "Automatisk",
                    "advanced": "Avansert",
                }.get,
                help=(
                    "Automatisk velger rask parsing når dokumentet har enkel tekst, "
                    "og avansert Docling/OCR når dokumentet ser ut til å kreve bedre layout- eller tabellhåndtering. "
                    "Avansert bevarer formatering bedre, men tar lengre tid."
                ),
            )
            ocr = st.checkbox("Kjør automatisk OCR på bildefiler", value=True, help="Tekstgjenkjenning på bilde-PDF-er og bildefiler.")
            ignore_xlent = st.checkbox(
                "Ignorer XLENT-interne navn/e-post",
                value=False,
                help="Filtrer bort interne XLENT-navn og e-postdomener fra funnene.",
            )

        deep_scan, ai_model, min_confidence = deep_scan_controls()

    return ScanSettings(
        language="auto",
        scan_profile="normal",
        categories=tuple(selected_categories),
        pdf_mode=pdf_mode,
        ocr=ocr,
        ignore_xlent=ignore_xlent,
        deep_scan=deep_scan,
        ai_model=ai_model,
        min_confidence=min_confidence,
        anonymize_terms=anonymize_terms,
    )


def render_result(
    result: ScanResult,
    key_prefix: str = "res",
    allow_whitelist: bool = True,
    source_bytes: bytes | None = None,
    source_suffix: str = "",
    deep_scan: bool = False,
    ai_model: str = "",
    min_confidence: str = "medium",
    anonymize_terms: tuple[str, ...] = (),
) -> None:
    """Vis fullt resultat: risikobadge, summary, funnliste, eksport, anonymisering."""
    show_risk_badge(result.risk_level, result.risk_summary, result.recommended_action)

    if result.error:
        st.error(result.error)
    if result.warning:
        st.warning(result.warning)

    if result.findings:
        show_summary_badges(result.findings)

    # Eksport-rad
    cols = st.columns(4)
    with cols[0]:
        st.download_button(
            "⬇ JSON", data=findings_as_json(result.findings),
            file_name=report_filename(result, "json").replace("-rapport", "-funn"),
            mime="application/json", key=f"{key_prefix}_json",
            disabled=not result.findings, width="stretch",
        )
    with cols[1]:
        st.download_button(
            "⬇ CSV", data=findings_as_csv(result.findings),
            file_name=report_filename(result, "csv").replace("-rapport", "-funn"),
            mime="text/csv", key=f"{key_prefix}_csv",
            disabled=not result.findings, width="stretch",
        )
    with cols[2]:
        st.download_button(
            "⬇ HTML-rapport", data=build_html_report(result),
            file_name=report_filename(result, "html"),
            mime="text/html", key=f"{key_prefix}_html",
            width="stretch",
        )
    with cols[3]:
        try:
            pdf_bytes = build_pdf_report(result)
            st.download_button(
                "⬇ PDF-rapport", data=pdf_bytes,
                file_name=report_filename(result, "pdf"),
                mime="application/pdf", key=f"{key_prefix}_pdf",
                width="stretch",
            )
        except Exception as exc:  # noqa: BLE001
            st.caption(f"PDF utilgjengelig: {exc}")

    show_findings_table(result.findings, key=f"{key_prefix}_tbl", allow_whitelist=allow_whitelist)

    # Metadata
    meta = []
    if result.language:
        meta.append(f"Språk: `{result.language}`")
    if result.text_length:
        meta.append(f"Tekst: {result.text_length:,} tegn")
    if result.ocr_used:
        meta.append("OCR brukt")
    if result.scan_timings:
        total = result.scan_timings.get("total_s") or result.scan_timings.get("total")
        if total:
            meta.append(f"Tid: {float(total):.1f}s")
    if meta:
        st.caption("  ·  ".join(meta))

    # AI-dybdeskann (valgfri, kjøres på forespørsel)
    if deep_scan and result.original_text and ai_model:
        run_deep_scan_section(result, ai_model, min_confidence, key_prefix=key_prefix)

    # Anonymisering (når det finnes originaltekst)
    ai_terms = st.session_state.get(f"{key_prefix}_ai_terms") or []
    extra_terms = list(anonymize_terms) + [t for t in ai_terms if t not in anonymize_terms]
    if result.original_text and (result.findings or extra_terms):
        st.markdown("---")
        redaction_panel(result, source_bytes, source_suffix, key_prefix=key_prefix, extra_terms=extra_terms)
