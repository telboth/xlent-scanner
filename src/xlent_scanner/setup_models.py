"""Automatisk nedlasting av manglende spaCy-språkmodeller."""
from __future__ import annotations

_REQUIRED_MODELS = [
    "nb_core_news_sm",  # Norsk bokmål
    "sv_core_news_sm",  # Svensk
    "en_core_web_sm",   # Engelsk
]


def ensure_models() -> None:
    """Last ned manglende spaCy-modeller. Kalles ved oppstart (bakgrunnstråd)."""
    try:
        import spacy
        from spacy.cli import download as spacy_download
    except ImportError:
        return  # spaCy ikke installert — håndteres i ner_names.py

    for model in _REQUIRED_MODELS:
        if not spacy.util.is_package(model):
            try:
                print(f"[setup] Laster ned spaCy-modell: {model}…", flush=True)
                spacy_download(model)
                print(f"[setup] ✓ {model} nedlastet.", flush=True)
            except Exception as exc:
                print(
                    f"[setup] ADVARSEL: Klarte ikke å laste ned {model}: {exc}",
                    flush=True,
                )
