"""Språkdeteksjon og -konfigurasjon for scanneren.

Støttede dokumentspråk for detektorer:
  nb  – Norsk bokmål  (spaCy: nb_core_news_sm)
  sv  – Svenska       (spaCy: sv_core_news_sm)
  en  – English       (spaCy: en_core_web_sm)
  da  – Dansk         (spaCy: nb_core_news_sm — norsk brukes, skriftspråkene ligner)
  de  – Deutsch       (spaCy: de_core_news_sm)
  fr  – Français      (spaCy: fr_core_news_sm)
  es  – Español       (spaCy: es_core_news_sm)

UI-språk (grensesnittoversettelse) er uavhengig av dokumentspråket og
håndteres i index.html (I18N-objekt). De tre nye språkene er gyldige
UI-valg, men dokumentspråkene brukes for å velge riktige detektorer.
"""
from __future__ import annotations

SUPPORTED: dict[str, str] = {
    "nb": "Norsk",
    "sv": "Svenska",
    "en": "English",
    "da": "Dansk",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
}

# spaCy-modell og NER-label per dokumentspråk.
SPACY_CONFIG: dict[str, dict[str, str]] = {
    "nb": {"model": "nb_core_news_sm", "ner_label": "PER"},
    "sv": {"model": "sv_core_news_sm",  "ner_label": "PER"},
    "en": {"model": "en_core_web_sm",   "ner_label": "PERSON"},
    "da": {"model": "nb_core_news_sm",  "ner_label": "PER"},   # norsk brukes for dansk
    "de": {"model": "de_core_news_sm",  "ner_label": "PER"},
    "fr": {"model": "fr_core_news_sm",  "ner_label": "PER"},
    "es": {"model": "es_core_news_sm",  "ner_label": "PER"},
}

_MIN_DETECT_CHARS = 80   # kortere tekster gir upålitelig deteksjon


def detect_language(text: str) -> str:
    """Detekter dokumentspråk. Returnerer én av kodene i SUPPORTED.

    Bruker de første 3000 tegnene for hastighet.
    Faller tilbake til 'nb' ved feil eller for kort tekst.
    """
    if len(text.strip()) < _MIN_DETECT_CHARS:
        return "nb"
    try:
        from langdetect import detect, DetectorFactory  # type: ignore
        DetectorFactory.seed = 0   # deterministisk resultat
        lang = detect(text[:3000])
        # Norsk bokmål og nynorsk → nb
        if lang in ("no", "nb", "nn"):
            return "nb"
        if lang in SUPPORTED:
            return lang
        return "en"
    except Exception:
        return "nb"


def resolve_language(requested: str, text: str) -> str:
    """Løs opp 'auto' → detektert dokumentspråk; valider andre koder."""
    if requested == "auto":
        return detect_language(text)
    return requested if requested in SUPPORTED else "nb"
