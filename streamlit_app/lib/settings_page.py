"""Innstillinger som gjenbrukbar fane — hviteliste, blacklist, regex, ignore, modeller, profil."""
from __future__ import annotations

import json
import re
import time

import pandas as pd
import streamlit as st

from xlent_scanner import __version__
from xlent_scanner.blacklist import get_blacklist_entries, save_blacklist_entries
from xlent_scanner.detectors.custom_patterns import (
    get_custom_patterns_text,
    save_custom_patterns_text,
    validate_custom_patterns_text,
)
from xlent_scanner.ignore import get_ignore_toml_text, save_ignore_toml_text
from xlent_scanner.model_manager import download_model_async, models_status
from xlent_scanner.scanner import reset_ignore_cache
from xlent_scanner.whitelist import get_whitelist_entries, save_whitelist_entries

from lib.scan_runner import clear_scan_cache


def _lines_to_list(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


@st.fragment(run_every=2.0)
def _models_section() -> None:
    status = models_status()
    rows = [
        {
            "Språk": m["lang"],
            "Modell": m["model"],
            "Størrelse": f"{m['size_mb']} MB" if m.get("size_mb") else "–",
            "Status": "✅ Installert" if m["installed"] else (m["progress"] or "Ikke installert"),
        }
        for m in status
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    not_installed = [m for m in status if not m["installed"]]
    if not_installed:
        cols = st.columns(min(len(not_installed), 4))
        for i, m in enumerate(not_installed):
            with cols[i % len(cols)]:
                downloading = bool(m["progress"]) and not m["progress"].startswith("error")
                if st.button(f"⬇ {m['model']}", key=f"dl_{m['model']}", disabled=downloading, width="stretch"):
                    download_model_async(m["model"])
                    st.rerun()
    else:
        st.success("Alle modeller er installert.")


def render_settings() -> None:
    """Tegn innstillinger-fanen med undertabber."""
    tabs = st.tabs([
        "✅ Hviteliste", "⛔ Blacklist", "🔤 Regex-mønstre",
        "🙈 Ignore", "🧠 Modeller", "💾 Import/Eksport",
    ])

    with tabs[0]:
        st.caption("Verdier her flagges ikke i fremtidige skann (én per linje).")
        wl_text = st.text_area("Hviteliste", value="\n".join(get_whitelist_entries()), height=300, key="wl_area")
        if st.button("💾 Lagre hviteliste", type="primary"):
            save_whitelist_entries(_lines_to_list(wl_text))
            clear_scan_cache()
            st.success("Hviteliste lagret.")

    with tabs[1]:
        st.caption("Ord/uttrykk her flagges alltid og fjernes ved redaction (én per linje).")
        bl_text = st.text_area("Blacklist", value="\n".join(get_blacklist_entries()), height=300, key="bl_area")
        if st.button("💾 Lagre blacklist", type="primary"):
            save_blacklist_entries(_lines_to_list(bl_text))
            clear_scan_cache()
            st.success("Blacklist lagret.")

    with tabs[2]:
        st.caption("Definer egne mønstre i TOML. Valideres ved lagring.")
        cp_text = st.text_area("custom_patterns.toml", value=get_custom_patterns_text(), height=260, key="cp_area")
        if st.button("💾 Lagre mønstre", type="primary"):
            try:
                patterns = validate_custom_patterns_text(cp_text)
                save_custom_patterns_text(cp_text)
                clear_scan_cache()
                st.success(f"Lagret {len(patterns)} mønstre.")
            except ValueError as exc:
                st.error(f"Ugyldig: {exc}")

        st.markdown("---")
        st.markdown("**Test et regex mot eksempeltekst**")
        tc1, tc2 = st.columns(2)
        with tc1:
            test_regex = st.text_input("Regex", key="cp_test_regex")
            ignore_case = st.checkbox("Ignorer store/små bokstaver", value=True, key="cp_test_ic")
        with tc2:
            test_sample = st.text_area("Eksempeltekst", height=120, key="cp_test_sample")
        if test_regex:
            try:
                pattern = re.compile(test_regex, re.IGNORECASE if ignore_case else 0)
                matches = [m.group(0) for _, m in zip(range(20), pattern.finditer(test_sample))]
                if matches:
                    st.success(f"{len(matches)} treff: " + ", ".join(f"`{m}`" for m in matches))
                else:
                    st.info("Ingen treff.")
            except re.error as exc:
                st.error(f"Ugyldig regex: {exc}")

    with tabs[3]:
        st.caption("Interne navn/e-postdomener som alltid ignoreres (TOML).")
        ig_text = st.text_area("ignore.toml", value=get_ignore_toml_text(), height=300, key="ig_area")
        if st.button("💾 Lagre ignore-liste", type="primary"):
            try:
                save_ignore_toml_text(ig_text)
                reset_ignore_cache()
                clear_scan_cache()
                st.success("Ignore-liste lagret.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Feil: {exc}")

    with tabs[4]:
        st.caption("spaCy NER-modeller for personnavn-deteksjon. Lastes ned ved behov.")
        _models_section()

    with tabs[5]:
        st.markdown("**Eksporter** hviteliste, blacklist, ignore og regex-mønstre til én fil.")
        profile = {
            "format": "xlent-scanner-settings",
            "format_version": 1,
            "app_version": __version__,
            "exported_at": int(time.time()),
            "whitelist": get_whitelist_entries(),
            "blacklist": get_blacklist_entries(),
            "ignore_toml": get_ignore_toml_text(),
            "custom_patterns_toml": get_custom_patterns_text(),
        }
        st.download_button(
            "⬇ Eksporter innstillinger",
            data=json.dumps(profile, ensure_ascii=False, indent=2),
            file_name="xlent-scanner-innstillinger.json",
            mime="application/json",
        )

        st.markdown("---")
        st.markdown("**Importer** en tidligere eksportert innstillingsfil.")
        up = st.file_uploader("Innstillingsfil (.json)", type=["json"], key="settings_import")
        if up is not None and st.button("📥 Importer", type="primary"):
            try:
                data = json.loads(up.getvalue().decode("utf-8"))
                if data.get("format") != "xlent-scanner-settings":
                    st.error("Ugyldig innstillingsfil.")
                else:
                    if isinstance(data.get("whitelist"), list):
                        save_whitelist_entries([str(t) for t in data["whitelist"]])
                    if isinstance(data.get("blacklist"), list):
                        save_blacklist_entries([str(t) for t in data["blacklist"]])
                    if isinstance(data.get("ignore_toml"), str):
                        save_ignore_toml_text(data["ignore_toml"])
                        reset_ignore_cache()
                    if isinstance(data.get("custom_patterns_toml"), str):
                        save_custom_patterns_text(data["custom_patterns_toml"])
                    clear_scan_cache()
                    st.success("Innstillinger importert. Åpne fanene for å se resultatet.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Import feilet: {exc}")
