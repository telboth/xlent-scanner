"""Språkdeteksjon og -konfigurasjon for scanneren.

Støttede språk:
  nb  – Norsk bokmål  (spaCy: nb_core_news_sm)
  sv  – Svenska       (spaCy: sv_core_news_sm)
  en  – English       (spaCy: en_core_web_sm)
  da  – Dansk         (spaCy: da_core_news_sm)
"""
from __future__ import annotations

SUPPORTED: dict[str, str] = {
    "nb": "Norsk",
    "sv": "Svenska",
    "en": "English",
    "da": "Dansk",
}

# spaCy-modell og NER-label per språk
SPACY_CONFIG: dict[str, dict[str, str]] = {
    "nb": {"model": "nb_core_news_sm", "ner_label": "PER"},
    "sv": {"model": "sv_core_news_sm",  "ner_label": "PER"},
    "en": {"model": "en_core_web_sm",   "ner_label": "PERSON"},
    "da": {"model": "da_core_news_sm",  "ner_label": "PER"},
}

_MIN_DETECT_CHARS = 80   # kortere tekster gir upålitelig deteksjon


def detect_language(text: str) -> str:
    """Detekter språk fra tekst. Returnerer 'nb', 'sv' eller 'en'.

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
        if lang == "da":
            return "da"
        if lang == "sv":
            return "sv"
        return "en"
    except Exception:
        return "nb"


def resolve_language(requested: str, text: str) -> str:
    """Løs opp 'auto' → detektert språk; valider andre koder.

    Args:
        requested: 'auto', 'nb', 'sv' eller 'en' fra brukergrensesnittet.
        text:      Ekstrahert dokumenttekst (brukes ved auto-deteksjon).

    Returns:
        Språkkode ('nb', 'sv' eller 'en').
    """
    if requested == "auto":
        return detect_language(text)
    return requested if requested in SUPPORTED else "nb"
