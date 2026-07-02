"""AI-dybdeskann (Ollama) — sidebar-kontroller og kjør/poll/vis-seksjon."""
from __future__ import annotations

import streamlit as st

from xlent_scanner.ai_findings import as_model_findings
from xlent_scanner.deep_scanner import (
    cancel_deep_scan,
    get_deep_scan_status,
    ollama_status,
    start_deep_scan,
)
from xlent_scanner.models import ScanResult


@st.cache_data(ttl=15, show_spinner=False)
def cached_ollama_status() -> dict:
    try:
        return ollama_status()
    except Exception as exc:  # noqa: BLE001
        return {"running": False, "models": [], "error": str(exc)}


def deep_scan_controls() -> tuple[bool, str, str]:
    """Rendres i sidebaren. Returnerer (deep_scan_på, modell, min_konfidens)."""
    st.markdown("---")
    deep_scan = st.checkbox(
        "🔬 Kjør AI-dybdeskann (Ollama)",
        value=False,
        help="Analyser dokumentet med en lokal AI-modell for å fange kontekstuelle funn "
             "(navn, adresser, selskaper) som regelmotoren kan misse. Krever at Ollama kjører lokalt.",
    )
    model, min_confidence = "", "medium"
    if deep_scan:
        status = cached_ollama_status()
        if not status.get("running"):
            st.warning("⚠️ Ollama kjører ikke. Start Ollama lokalt for å bruke AI-dybdeskann.")
        else:
            models = status.get("models") or []
            if not models:
                rec = status.get("recommended_model", "llama3.2:3b")
                st.warning(f"Ingen modeller installert. Kjør: `ollama pull {rec}`")
            else:
                rec = status.get("recommended_model")
                idx = models.index(rec) if rec in models else 0
                model = st.selectbox("AI-modell", models, index=idx, key="cfg_ai_model")
    return deep_scan, model, min_confidence


def run_deep_scan_section(result: ScanResult, model: str, min_confidence: str, key_prefix: str) -> None:
    """Knapp + fremdrift + visning av AI-funn. Lagrer AI-funn-tekster i session_state."""
    if not result.original_text or not model:
        return
    st.markdown("---")
    st.markdown("#### 🔬 AI-dybdeskann")
    job_key = f"{key_prefix}_deepjob"

    if st.button("Kjør AI-dybdeskann", key=f"{key_prefix}_deepbtn", type="primary"):
        st.session_state[job_key] = start_deep_scan(
            result.original_text, model, result.language or "en", min_confidence=min_confidence,
        )
        st.rerun()

    job_id = st.session_state.get(job_key)
    if not job_id:
        st.caption("Ikke kjørt ennå.")
        return

    status = get_deep_scan_status(job_id)
    state = status.get("status", "")

    if state == "running":
        _poll_deep_scan(job_id, key_prefix)
    else:
        _render_ai_findings(status, key_prefix)


@st.fragment(run_every=1.0)
def _poll_deep_scan(job_id: str, key_prefix: str) -> None:
    status = get_deep_scan_status(job_id)
    if status.get("status") == "running":
        pct = int(status.get("progress_percent") or 0)
        done = status.get("completed_chunks", 0)
        total = status.get("total_chunks", 0)
        st.progress(pct / 100, text=f"{status.get('progress', 'Analyserer…')} ({done}/{total} deler)")
        if st.button("⛔ Avbryt", key=f"{key_prefix}_deepcancel"):
            cancel_deep_scan(job_id)
    else:
        st.rerun()


def _render_ai_findings(status: dict, key_prefix: str) -> None:
    state = status.get("status", "")
    if state == "cancelled":
        st.warning("AI-dybdeskann avbrutt.")
    elif state == "error":
        st.error(f"AI-dybdeskann feilet: {status.get('error') or status.get('progress') or 'ukjent feil'}")
    raw = status.get("findings") or []
    ai_findings = as_model_findings(raw)
    # Lagre tekstene så anonymiseringspanelet kan foreslå dem
    st.session_state[f"{key_prefix}_ai_terms"] = [f.text for f in ai_findings if f.text]
    if not ai_findings:
        if state == "done":
            st.success("AI-dybdeskann fullført — ingen ekstra funn.")
        return
    from lib.findings_table import show_findings_table, show_summary_badges
    st.success(f"AI-dybdeskann fant {len(ai_findings)} funn.")
    show_summary_badges(ai_findings)
    show_findings_table(ai_findings, key=f"{key_prefix}_aitbl", allow_whitelist=False)
