"""XLENT Compliance-scanner — Streamlit-frontend.

Kjør med:
    cd streamlit_app
    uv run streamlit run app.py

Forsiden ER skann-opplevelsen: slipp en fil og resultatet vises umiddelbart,
uten å trykke på noen «Skann»-knapp.
"""
from pathlib import Path

import streamlit as st

from xlent_scanner import __version__

from lib.about_page import render_about
from lib.background_page import render_background
from lib.branding import show_logo
from lib.folder_scan import render_folder_scan
from lib.scan_runner import run_file_scan, run_text_scan
from lib.scan_ui import render_result, settings_sidebar
from lib.settings_page import render_settings

st.set_page_config(
    page_title="XLENT Compliance-scanner",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)
show_logo()

SUPPORTED = [
    "pdf", "docx", "pptx", "xlsx", "txt", "md", "html", "csv", "eml", "rtf", "odt",
    "png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp",
]

st.markdown(
    """
    <style>
      .stApp { background: #f6f8fb; }
      section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e5e7eb; }
      div[data-testid="stFileUploader"] section {
        border: 1px dashed #9ca3af;
        border-radius: 16px;
        background: #ffffff;
      }
      .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
        background: #ffffff;
        color: #111827;
        border: 1px solid #d1d5db;
      }
      .stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {
        border-color: #111827;
        color: #111827;
      }
      [data-testid="stExpander"] {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("XLENT Scanner")
st.caption(f"v{__version__} · Sjekker og anonymiserer dokumenter for sensitiv informasjon. Alt kjøres lokalt.")
st.caption(
    "Slipp et dokument nedenfor — det skannes automatisk. Ingen dokumenter, tekst eller funn sendes over internett."
)

settings = settings_sidebar()

tab_fil, tab_tekst, tab_mappe, tab_innst, tab_vakt, tab_om = st.tabs(
    ["📄 Fil", "📋 Tekst", "📁 Mappe", "⚙️ Innstillinger", "🛡️ Bakgrunnsvakt", "ℹ️ Om"]
)

with tab_fil:
    uploaded = st.file_uploader(
        "Dra og slipp fil(er) her — skannes automatisk",
        type=SUPPORTED,
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if uploaded:
        for idx, up in enumerate(uploaded):
            suffix = Path(up.name).suffix.lower()
            with st.spinner(f"Skanner {up.name}…"):
                result = run_file_scan(
                    up.getvalue(), suffix,
                    language=settings.language,
                    ignore_xlent=settings.ignore_xlent,
                    ocr=settings.ocr,
                    scan_profile=settings.scan_profile,
                    categories=settings.categories or None,
                    pdf_mode=settings.pdf_mode,
                )
            result.file_name = up.name
            expanded = len(uploaded) == 1 or result.risk_level in ("rød", "svart")
            with st.expander(f"**{up.name}** — {result.risk_level.upper()}", expanded=expanded):
                render_result(
                    result, key_prefix=f"file_{idx}",
                    source_bytes=up.getvalue(), source_suffix=suffix,
                    deep_scan=settings.deep_scan, ai_model=settings.ai_model,
                    min_confidence=settings.min_confidence,
                    anonymize_terms=settings.anonymize_terms,
                )

with tab_tekst:
    text = st.text_area(
        "Lim inn tekst (Ctrl+Enter for å skanne)",
        height=220,
        placeholder="Lim inn e-post, kontraktsutdrag, referat …",
        label_visibility="collapsed",
    )
    if text.strip():
        with st.spinner("Skanner…"):
            result = run_text_scan(
                text,
                language=settings.language,
                scan_profile=settings.scan_profile,
                categories=settings.categories or None,
            )
        st.markdown("---")
        render_result(
            result, key_prefix="text",
            deep_scan=settings.deep_scan, ai_model=settings.ai_model,
            min_confidence=settings.min_confidence,
            anonymize_terms=settings.anonymize_terms,
        )

with tab_mappe:
    render_folder_scan(settings)

with tab_innst:
    render_settings()

with tab_vakt:
    render_background()

with tab_om:
    render_about()
