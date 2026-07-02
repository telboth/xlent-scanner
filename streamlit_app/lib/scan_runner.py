"""Kjør scan og cache resultatet.

Bruker st.cache_data slik at samme fil + samme innstillinger ikke skannes på
nytt ved hver Streamlit-rerun, men at endrede innstillinger automatisk trigger
en ny skann (auto-skann).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from xlent_scanner.models import ScanResult
from xlent_scanner.scanner import scan_file, scan_text


def _norm_categories(categories: list[str] | None) -> tuple[str, ...] | None:
    if categories is None:
        return None
    return tuple(sorted(categories))


@st.cache_data(show_spinner=False, max_entries=32)
def run_file_scan(
    file_bytes: bytes,
    suffix: str,
    *,
    language: str = "auto",
    ignore_xlent: bool = False,
    ocr: bool = False,
    scan_profile: str = "normal",
    categories: tuple[str, ...] | None = None,
    pdf_mode: str = "fast",
) -> ScanResult:
    """Skann filinnhold. Cachet på (bytes + alle parametre)."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        return scan_file(
            tmp_path,
            ignore_xlent=ignore_xlent,
            language=language,
            ocr=ocr,
            scan_profile=scan_profile,
            categories=list(categories) if categories is not None else None,
            pdf_mode=pdf_mode,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@st.cache_data(show_spinner=False, max_entries=32)
def run_text_scan(
    text: str,
    *,
    language: str = "auto",
    scan_profile: str = "normal",
    categories: tuple[str, ...] | None = None,
) -> ScanResult:
    """Skann ren tekst. Cachet på (tekst + parametre)."""
    return scan_text(
        text,
        language=language,
        scan_profile=scan_profile,
        categories=list(categories) if categories is not None else None,
    )


def clear_scan_cache() -> None:
    """Tøm cache — brukes etter endring i hviteliste/blacklist/regex."""
    run_file_scan.clear()
    run_text_scan.clear()
