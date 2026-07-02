"""Bakgrunnsvakter som gjenbrukbar fane — utklippstavle-vakt og mappeovervåkning."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from xlent_scanner.clipboard_guard import guard
from xlent_scanner.folder_watch import watcher

from lib.scan_ui import LANG_OPTIONS

_RISK_ICON = {"svart": "⚫", "rød": "🔴", "gul": "🟡", "grønn": "🟢"}


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return ""


@st.fragment(run_every=2.0)
def _clipboard_status() -> None:
    s = guard.status()
    if s["running"]:
        st.success(f"🟢 Aktiv — {s['checks']} sjekker · startet {_fmt_ts(s['started_at'])}")
    else:
        st.info("⚪ Ikke aktiv")
    alerts = s.get("recent_alerts") or []
    if alerts:
        rows = [
            {
                "Tid": _fmt_ts(a.get("timestamp")),
                "Risiko": f"{_RISK_ICON.get(a.get('risk_level'), '🟡')} {a.get('risk_level', '')}",
                "Funn": a.get("finding_count", 0),
                "Kategorier": ", ".join(a.get("categories") or []),
            }
            for a in reversed(alerts)
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    elif s["running"]:
        st.caption("Ingen varsler ennå.")


@st.fragment(run_every=2.0)
def _folder_watch_status() -> None:
    s = watcher.status()
    folders = s.get("folders") or []
    if not folders:
        st.info("⚪ Ingen mapper overvåkes.")
        return
    st.success(f"🟢 Overvåker {len(folders)} mappe(r) · {s.get('scanned_count', 0)} filer skannet totalt")
    for f in folders:
        cols = st.columns([5, 1])
        with cols[0]:
            st.write(f"📁 `{f['folder']}` — {f.get('scanned_count', 0)} skannet · startet {_fmt_ts(f.get('started_at'))}")
        with cols[1]:
            if st.button("⏹ Stopp", key=f"fw_stop_{f['folder']}", width="stretch"):
                watcher.stop(f["folder"])
                st.rerun()

    results = s.get("recent_results") or []
    if results:
        st.markdown("**Nylig skannet**")
        rows = [
            {
                "Tid": _fmt_ts(r.get("timestamp")),
                "Fil": r.get("file_name", ""),
                "Risiko": f"{_RISK_ICON.get(r.get('risk_level'), '🟡')} {r.get('risk_level', '')}",
                "Funn": r.get("finding_count", 0),
            }
            for r in reversed(results)
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_background() -> None:
    """Tegn bakgrunnsvakt-fanen."""
    st.markdown("## 📋 Utklippstavle-vakt")
    st.caption("Overvåker utklippstavlen og varsler når du kopierer sensitiv informasjon.")

    cb_status = guard.status()
    c1, _ = st.columns([1, 3])
    with c1:
        if cb_status["running"]:
            if st.button("⏹ Stopp vakt", key="cb_stop", width="stretch"):
                guard.stop()
                st.rerun()
        else:
            if st.button("▶ Start vakt", key="cb_start", type="primary", width="stretch"):
                guard.start()
                st.rerun()

    _clipboard_status()

    st.markdown("---")

    st.markdown("## 📂 Mappeovervåkning")
    st.caption("Skanner automatisk nye/endrede filer i valgte mapper.")

    fw_status = watcher.status()
    folder_in = st.text_input("Mappe å overvåke", placeholder=r"F.eks. C:\Users\thomas\Downloads", key="fw_folder")
    oc1, oc2, oc3 = st.columns([2, 2, 2])
    with oc1:
        fw_lang_label = st.selectbox("Språk", list(LANG_OPTIONS.keys()), index=0, key="fw_lang")
    with oc2:
        fw_ignore = st.checkbox("Ignorer XLENT-interne", value=False, key="fw_ignore")
    with oc3:
        st.caption(f"Maks {fw_status.get('max_folders', 3)} mapper samtidig")

    if st.button("▶ Start overvåkning", type="primary", disabled=not folder_in):
        res = watcher.start(folder_in, ignore_xlent=fw_ignore, language=LANG_OPTIONS[fw_lang_label])
        if res.get("ok"):
            st.success(f"Overvåker: {folder_in}")
        else:
            st.error(res.get("error", "Kunne ikke starte overvåkning."))
        st.rerun()

    _folder_watch_status()

    if fw_status.get("running"):
        if st.button("⏹ Stopp alle", key="fw_stop_all"):
            watcher.stop()
            st.rerun()
