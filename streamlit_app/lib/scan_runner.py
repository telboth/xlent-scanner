"""Kjør scan og cache resultatet.

Bruker st.cache_data slik at samme fil + samme innstillinger ikke skannes på
nytt ved hver Streamlit-rerun, men at endrede innstillinger automatisk trigger
en ny skann (auto-skann).
"""
from __future__ import annotations

import tempfile
import shutil
from pathlib import Path

import streamlit as st

from xlent_scanner.models import ScanResult
from xlent_scanner.scanner import build_folder_scan_plan, scan_file, scan_text
from xlent_scanner.zip_processing import (
    ZIP_LARGE_FILE_COUNT,
    ZIP_LARGE_TOTAL_BYTES,
    extract_zip_to_temp,
)


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


@st.cache_data(show_spinner=False, max_entries=8)
def run_zip_scan(
    file_bytes: bytes,
    *,
    file_name: str,
    language: str = "auto",
    ignore_xlent: bool = False,
    ocr: bool = False,
    scan_profile: str = "normal",
    categories: tuple[str, ...] | None = None,
    pdf_mode: str = "auto",
) -> dict:
    """Skann ZIP som midlertidig mappe. Cachet på bytes + innstillinger."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        extracted = extract_zip_to_temp(tmp_path)
        try:
            plan = build_folder_scan_plan(extracted.root, recursive=True)
            results: list[ScanResult] = []
            for path in plan["files"]:
                result = scan_file(
                    path,
                    ignore_xlent=ignore_xlent,
                    language=language,
                    ocr=ocr,
                    scan_profile=scan_profile,
                    categories=list(categories) if categories is not None else None,
                    pdf_mode=pdf_mode,
                )
                result.relative_path = str(Path(path).relative_to(extracted.root))
                result.source_path = str(path)
                results.append(result)
            warning = ""
            if (
                extracted.total_files >= ZIP_LARGE_FILE_COUNT
                or extracted.total_uncompressed_bytes >= ZIP_LARGE_TOTAL_BYTES
            ):
                warning = "ZIP-arkivet er stort. Skanning kan ta tid."
            return {
                "file_name": file_name,
                "total_files": extracted.total_files,
                "supported_files": extracted.supported_files,
                "ignored_files": extracted.ignored_files,
                "skipped": extracted.skipped,
                "warning": warning,
                "results": results,
            }
        finally:
            shutil.rmtree(extracted.root, ignore_errors=True)
    finally:
        tmp_path.unlink(missing_ok=True)


def clear_scan_cache() -> None:
    """Tøm cache — brukes etter endring i hviteliste/blacklist/regex."""
    run_file_scan.clear()
    run_text_scan.clear()
    run_zip_scan.clear()
