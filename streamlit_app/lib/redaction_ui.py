"""Anonymiserings-/redaction-panel — gjenbrukbart UI-blokk.

Dekker generering av anonymisert .md/PDF, in-place redaction i originalformat,
bilde-PDF-redaction, forhåndsvisning, kontrollskann og åpne/vis-i-mappe.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from xlent_scanner.anonymize import anonymize_text, build_replacements
from xlent_scanner.image_pdf_redaction import redact_image_pdf
from xlent_scanner.models import Finding, ScanResult
from xlent_scanner.patch import SUPPORTED_PATCH_SUFFIXES, patch_file
from xlent_scanner.redaction_audit import record_redaction
from xlent_scanner.scanner import IMAGE_SUFFIXES, _image_to_temp_pdf
from xlent_scanner.utils import open_path, reveal_path

from lib.exports import unique_output, write_text_pdf

_MIME = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _is_image_pdf(result: ScanResult, suffix: str) -> bool:
    if suffix != ".pdf":
        return False
    return bool(getattr(result, "ocr_used", False)) or result.warning_code in {
        "no_text_extracted",
        "little_text_extracted",
    }


def _write_temp_source(source_bytes: bytes, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, prefix="xlent-src-") as tmp:
        tmp.write(source_bytes)
        return Path(tmp.name)


def _show_verification(entry: dict) -> None:
    v = entry.get("verification", {})
    status = v.get("status", "")
    if status == "passed":
        st.success(
            f"✅ Kontrollskann bestått — {v.get('removed_count', 0)} funn fjernet, "
            f"{v.get('finding_count', 0)} gjenværende."
        )
    elif status == "error":
        st.error(f"Kontrollskann feilet: {v.get('error', 'ukjent feil')}")
    else:
        st.warning(
            f"⚠️ Krever kontroll — {v.get('removed_count', 0)} fjernet, "
            f"{v.get('remaining_selected_count', 0)} av de valgte funnene finnes fortsatt, "
            f"{v.get('finding_count', 0)} funn totalt i den anonymiserte filen."
        )


def redaction_panel(
    result: ScanResult,
    source_bytes: bytes | None,
    source_suffix: str,
    key_prefix: str = "red",
    extra_terms: list[str] | None = None,
) -> None:
    if not result.original_text:
        return

    suffix = (source_suffix or "").lower()
    st.markdown("#### 🕶️ Anonymiser")

    # 1) Velg funn som skal maskeres (default: alle ikke-grønne)
    redactable = [f for f in result.findings if f.severity != "grønn"]
    selected: list[Finding] = []
    if redactable:
        opts = list(range(len(redactable)))
        labels = {i: f"[{redactable[i].category}] {redactable[i].text[:50]}" for i in opts}
        selected_idx = st.multiselect(
            "Funn som skal maskeres",
            options=opts,
            default=opts,
            format_func=labels.get,
            key=f"{key_prefix}_sel",
        )
        selected = [redactable[i] for i in selected_idx]

    # 1b) Egne ord/uttrykk fra sidebaren (+ AI-dybdeskann-funn) som maskeres i tillegg.
    custom_terms = [str(t).strip() for t in (extra_terms or []) if str(t).strip()]
    custom_findings = [
        Finding(category="Egendefinert", text=t, raw_text=t, severity="rød")
        for t in custom_terms
    ]
    if custom_terms:
        st.caption("Maskerer også: " + ", ".join(f"«{t}»" for t in custom_terms[:15]))

    all_selected = selected + custom_findings
    if not all_selected:
        st.info("Velg minst ett funn, eller skriv inn ord/uttrykk i venstre marg, for å anonymisere.")
        return

    selected = all_selected
    replacements = build_replacements(selected)

    # 2) Forhåndsvisning
    with st.expander(f"Forhåndsvis maskering ({len(replacements)} erstatninger)"):
        src = result.original_text or ""
        rows = [
            {"Original": old, "Erstattes med": new, "Forekomster": src.count(old)}
            for old, new in sorted(replacements.items(), key=lambda kv: kv[0].casefold())
        ]
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        skipped = [f for f in selected if (f.raw_text or f.text) not in replacements]
        if skipped:
            st.caption(f"{len(skipped)} funn kan ikke maskeres direkte i tekst.")

    # 3) Velg utdataformat
    formats = ["Markdown (.md)", "PDF (fra tekst)"]
    can_inplace = source_bytes is not None and suffix in SUPPORTED_PATCH_SUFFIXES
    image_pdf = _is_image_pdf(result, suffix)
    if can_inplace and not (suffix == ".pdf" and image_pdf):
        formats.append(f"In-place ({suffix})")
    if source_bytes is not None and ((suffix == ".pdf" and image_pdf) or suffix in IMAGE_SUFFIXES):
        formats.append("Bilde-PDF (raster)")

    choice = st.radio("Format", formats, horizontal=True, key=f"{key_prefix}_fmt")
    strip_annotations = False
    if choice.startswith("In-place") or choice.startswith("Bilde-PDF"):
        strip_annotations = st.checkbox(
            "Fjern kommentarer / notater / annotasjoner",
            value=False, key=f"{key_prefix}_strip",
        )

    # 4) Generer
    if st.button("🛡️ Generer anonymisert fil", type="primary", key=f"{key_prefix}_gen"):
        try:
            entry = _generate(result, selected, replacements, choice, suffix,
                              source_bytes, strip_annotations)
            st.session_state[f"{key_prefix}_result"] = entry
        except Exception as exc:  # noqa: BLE001
            st.session_state[f"{key_prefix}_result"] = None
            st.error(f"Anonymisering feilet: {exc}")

    # 5) Vis resultat (persistert i session_state)
    entry = st.session_state.get(f"{key_prefix}_result")
    if entry:
        out_path = Path(entry["path"])
        st.markdown("---")
        st.success(f"Lagret: `{out_path}`")
        _show_verification(entry)
        cols = st.columns(3)
        if out_path.is_file():
            with cols[0]:
                st.download_button(
                    "⬇ Last ned", data=out_path.read_bytes(),
                    file_name=out_path.name,
                    mime=_MIME.get(out_path.suffix.lower(), "application/octet-stream"),
                    key=f"{key_prefix}_dl", width="stretch",
                )
            with cols[1]:
                if st.button("📂 Åpne fil", key=f"{key_prefix}_open", width="stretch"):
                    try:
                        open_path(out_path)
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))
            with cols[2]:
                if st.button("🗂 Vis i mappe", key=f"{key_prefix}_reveal", width="stretch"):
                    try:
                        reveal_path(out_path)
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))


def _generate(result, selected, replacements, choice, suffix, source_bytes, strip_annotations) -> dict:
    stem = Path(result.file_name or "dokument").stem

    if choice.startswith("Markdown"):
        cleaned = anonymize_text(result.original_text, selected)
        output = unique_output(f"{stem}-anonymisert", ".md")
        output.write_text(cleaned, encoding="utf-8")
        return record_redaction(output, result, selected, method="text_md")

    if choice.startswith("PDF (fra tekst)"):
        cleaned = anonymize_text(result.original_text, selected)
        output = unique_output(f"{stem}-anonymisert", ".pdf")
        write_text_pdf(cleaned, output, title=f"{stem} – anonymisert")
        return record_redaction(output, result, selected, method="text_pdf")

    if choice.startswith("In-place"):
        tmp_src = _write_temp_source(source_bytes, suffix)
        try:
            output = unique_output(f"{stem}-anonymisert", suffix)
            patch_file(tmp_src, replacements, output, strip_annotations=strip_annotations)
            return record_redaction(output, result, selected, method=f"patch_{suffix.lstrip('.')}")
        finally:
            tmp_src.unlink(missing_ok=True)

    # Bilde-PDF (raster)
    tmp_src = _write_temp_source(source_bytes, suffix)
    tmp_pdf = None
    try:
        redaction_source = tmp_src
        if suffix in IMAGE_SUFFIXES:
            tmp_pdf = _image_to_temp_pdf(tmp_src)
            redaction_source = tmp_pdf
        output = unique_output(f"{stem}-anonymisert-bilde", ".pdf")
        redact_image_pdf(redaction_source, replacements, output, strip_annotations=strip_annotations)
        return record_redaction(output, result, selected, method="patch_image_pdf")
    finally:
        tmp_src.unlink(missing_ok=True)
        if tmp_pdf is not None:
            tmp_pdf.unlink(missing_ok=True)
