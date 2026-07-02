"""Om programmet som gjenbrukbar fane — brukerveiledning og forklaringer."""
from __future__ import annotations

import streamlit as st

from xlent_scanner import __version__


def render_about() -> None:
    st.caption(f"Versjon {__version__}")
    st.markdown(
        """
XLENT Scanner er et **lokalt** verktøy som oppdager og anonymiserer sensitiv informasjon i
dokumenter før deling, lagring eller opplasting til nettbaserte tjenester.

> 🔒 **Alt kjøres 100 % lokalt** — ingen dokumenter, tekst eller funn sendes over internett.
"""
    )
    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            """
### 🚦 Trafikklys-nivåer
- 🟢 **Grønn** — ingen sensitive funn
- 🟡 **Gul** — sensitive funn, vurder bruk
- 🔴 **Rød** — høy risiko, del ikke
- ⚫ **Svart** — kritisk (fødselsnummer, konto, nøkler)

### 📄 Slik skanner du
1. Velg fanen **Fil**, **Tekst** eller **Mappe**
2. Slipp en fil (skannes automatisk) eller lim inn tekst
3. Se gjennom funnene og trafikklys-nivået
4. Anonymiser om nødvendig før du deler
"""
        )
    with col2:
        st.markdown(
            """
### ⚙️ Innstillinger (venstre panel)
- Huk av **kategoriene** du vil skanne etter. Visningen følger hovedappen med 11 sammenslåtte kategorier.
- **Avansert** — scan-modus, automatisk OCR og XLENT-internt filter
- **🔬 AI-dybdeskann** — valgfri lokal AI (Ollama) som
  fanger kontekstuelle funn regelmotoren kan misse

### 🕶️ Anonymisering
- Generer renset `.md`/PDF, eller masker in-place i
  `.docx` / `.pptx` / `.xlsx` / `.pdf`
- Feltet **«Ord og uttrykk som skal anonymiseres»** lar
  deg maskere egne ord i tillegg til funnene
- Hver anonymisering **kontrollskannes** automatisk
"""
        )

    st.markdown("---")
    st.markdown(
        """
### 🗂 Fanene
- **Fil / Tekst** — skann enkeltdokumenter eller innlimt tekst
- **Mappe** — skann alle støttede filer i en mappe, med eksport, audit-rapport og batch-anonymisering
- **Innstillinger** — hviteliste, blacklist, egne regex-mønstre, ignore-liste, spaCy-modeller og import/eksport av profil
- **Bakgrunnsvakt** — overvåk utklippstavlen og mapper automatisk

### 📂 Støttede filformater
`.pdf` · `.docx` · `.pptx` · `.xlsx` · `.txt` · `.md` · `.html` · `.csv` · `.eml` · `.rtf` · `.odt`

### ❓ Tips
- Endrer du en innstilling, skannes dokumentet automatisk på nytt.
- Falske positive? Marker dem og legg dem i **hvitelisten** — de flagges ikke igjen.
- AI-dybdeskann krever at [Ollama](https://ollama.ai) kjører lokalt med en nedlastet modell.
"""
    )
    st.info("Spørsmål eller feil? Kontakt thomas.elboth@xlent.no")
