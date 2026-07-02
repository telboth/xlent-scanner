"""Mappeskann-UI som gjenbrukbar blokk (fane på forsiden).

Async jobb med progress/avbryt, eksport, audit og batch-redaction.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from xlent_scanner.utils import open_path, reveal_path

from lib.exports import build_html_report, report_filename
from lib.findings_table import show_findings_table, show_summary_badges
from lib.folder_jobs import cancel_job, get_job, preview_count, start_folder_job
from lib.folder_ui import (
    audit_html,
    audit_pdf_bytes,
    batch_redact,
    export_csv_bytes,
    export_json_bytes,
)
from lib.risk_badge import show_risk_badge

_RISK_ICON = {"svart": "⚫", "rød": "🔴", "gul": "🟡", "grønn": "🟢"}
_RISK_BG = {"svart": "#d1d5db", "rød": "#fca5a5", "gul": "#fde68a", "grønn": "#bbf7d0"}


@st.fragment(run_every=0.6)
def _progress(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        st.warning("Jobben ble borte.")
        return
    if job.status == "running":
        pct = job.completed / max(job.total, 1)
        st.progress(pct, text=f"Skanner {job.current_file}  ({job.completed}/{job.total})")
        if st.button("⛔ Avbryt", key="folder_cancel"):
            cancel_job(job_id)
    else:
        st.rerun()


def _render_results(job) -> None:
    if job.status == "error":
        st.error(f"Skann feilet: {job.error}")
        return
    if job.status == "cancelled":
        st.warning(f"Avbrutt etter {job.completed} av {job.total} filer.")
    results = job.sorted_results()
    if not results:
        st.info("Ingen resultater.")
        return

    # Sammendrag
    counts = {lvl: sum(1 for r in results if r.risk_level == lvl) for lvl in ("svart", "rød", "gul", "grønn")}
    m = st.columns(5)
    m[0].metric("Filer", len(results))
    m[1].metric("⚫ Svart", counts["svart"])
    m[2].metric("🔴 Rød", counts["rød"])
    m[3].metric("🟡 Gul", counts["gul"])
    m[4].metric("🟢 Grønn", counts["grønn"])
    if job.truncated:
        st.caption(f"⚠️ Listen ble begrenset til {job.total} filer.")

    # Filter
    filter_risk = st.multiselect(
        "Vis risikonivå", options=["svart", "rød", "gul", "grønn"],
        default=[lvl for lvl in ("svart", "rød", "gul") if counts[lvl]] or ["grønn"],
    )
    visible = [r for r in results if r.risk_level in filter_risk]

    # Tabell med seleksjon
    rows = [
        {
            "": _RISK_ICON.get(r.risk_level, "🟡"),
            "Fil": r.relative_path or r.file_name,
            "Risiko": r.risk_level,
            "Funn": len(r.findings),
            "Status": r.scan_status,
        }
        for r in visible
    ]
    bg = [_RISK_BG.get(r.risk_level, _RISK_BG["gul"]) for r in visible]

    def _color(row: pd.Series) -> list[str]:
        return [f"background-color: {bg[int(row.name)]}"] * len(row)

    event = st.dataframe(
        pd.DataFrame(rows).style.apply(_color, axis=1),
        width="stretch", hide_index=True, key="folder_tbl",
        on_select="rerun", selection_mode="multi-row",
    )
    selected_idx = getattr(event, "selection", {}).get("rows", []) if event else []
    selected = [visible[i] for i in selected_idx]

    # Eksport + audit (hele jobben)
    st.markdown("**Eksport**")
    e = st.columns(4)
    with e[0]:
        st.download_button("⬇ JSON", export_json_bytes(results, job.folder),
                           file_name="mappeskann.json", mime="application/json", width="stretch")
    with e[1]:
        st.download_button("⬇ CSV", export_csv_bytes(results),
                           file_name="mappeskann.csv", mime="text/csv", width="stretch")
    with e[2]:
        st.download_button("⬇ Audit HTML", audit_html(results, job.folder),
                           file_name="mappeskann-audit.html", mime="text/html", width="stretch")
    with e[3]:
        st.download_button("⬇ Audit PDF", audit_pdf_bytes(results, job.folder),
                           file_name="mappeskann-audit.pdf", mime="application/pdf", width="stretch")

    # Batch-redaction (valgte filer)
    st.markdown("**Batch-redaction**")
    strip = st.checkbox("Fjern kommentarer/notater", value=False, key="folder_strip")
    if st.button(f"🛡️ Anonymiser {len(selected)} valgte filer", disabled=not selected):
        with st.spinner("Anonymiserer…"):
            res = batch_redact(selected, strip_annotations=strip)
        if res["outputs"]:
            st.success(f"{len(res['outputs'])} filer anonymisert til: `{res['folder']}`")
            if st.button("🗂 Åpne mappe"):
                open_path(Path(res["folder"]))
        for err in res["errors"]:
            st.warning(f"{err['file']}: {err['error']}")
    if not selected:
        st.caption("Velg filer i tabellen for å anonymisere eller åpne dem.")

    # Per-fil detaljer
    st.markdown("---")
    st.markdown(f"**Detaljer ({len(visible)} filer)**")
    for r in visible:
        icon = _RISK_ICON.get(r.risk_level, "🟡")
        with st.expander(f"{icon} {r.relative_path or r.file_name}  —  {len(r.findings)} funn"):
            show_risk_badge(r.risk_level, r.risk_summary, r.recommended_action)
            if r.error:
                st.error(r.error)
            if r.warning:
                st.warning(r.warning)
            if r.findings:
                show_summary_badges(r.findings)
                show_findings_table(r.findings, key=f"fld_{r.source_path}", allow_whitelist=False)
            b = st.columns(3)
            with b[0]:
                st.download_button("⬇ HTML-rapport", build_html_report(r),
                                   file_name=report_filename(r, "html"),
                                   mime="text/html", key=f"rep_{r.source_path}", width="stretch")
            with b[1]:
                if st.button("📂 Åpne fil", key=f"open_{r.source_path}", width="stretch"):
                    try:
                        open_path(Path(r.source_path))
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))
            with b[2]:
                if st.button("🗂 Vis i mappe", key=f"rev_{r.source_path}", width="stretch"):
                    try:
                        reveal_path(Path(r.source_path))
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))


def render_folder_scan(settings) -> None:
    """Tegn hele mappeskann-fanen. `settings` er ScanSettings fra sidebaren."""
    folder_path = st.text_input("Mappe-sti", placeholder=r"F.eks. C:\Users\thomas\Documents\Prosjekt")
    c1, c2, c3 = st.columns(3)
    with c1:
        recursive = st.checkbox("Inkluder undermapper", value=False)
    with c2:
        max_files = st.number_input("Maks filer", min_value=1, max_value=10_000, value=500, step=50)
    with c3:
        max_depth = st.number_input("Maks dybde", min_value=0, max_value=50, value=5, step=1, disabled=not recursive)

    valid_folder = bool(folder_path) and Path(folder_path).is_dir()
    if folder_path and not valid_folder:
        st.warning("Finner ikke mappen. Sjekk at stien er korrekt.")

    if valid_folder:
        try:
            plan = preview_count(folder_path, recursive=recursive, max_files=int(max_files), max_depth=int(max_depth))
            msg = f"**{plan['file_count']}** støttede filer funnet i {plan['folder_count']} mappe(r)"
            if plan["truncated"]:
                msg += f" (begrenset til {max_files})"
            st.info(msg)
            if st.button("🔍 Skann mappen", type="primary", disabled=plan["file_count"] == 0):
                st.session_state["folder_job_id"] = start_folder_job(
                    folder_path,
                    recursive=recursive, max_files=int(max_files), max_depth=int(max_depth),
                    language=settings.language, ignore_xlent=settings.ignore_xlent, ocr=settings.ocr,
                    scan_profile=settings.scan_profile, categories=settings.categories or None,
                    pdf_mode=settings.pdf_mode,
                )
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Kunne ikke lese mappen: {exc}")

    job_id = st.session_state.get("folder_job_id")
    job = get_job(job_id) if job_id else None
    if job:
        st.markdown("---")
        if job.status == "running":
            _progress(job_id)
        else:
            _render_results(job)
