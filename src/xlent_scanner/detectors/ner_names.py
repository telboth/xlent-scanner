"""NER-detektor for personnavn via spaCy.

Modeller lastes lazy og caches per språk. False-positive-filtre for generiske
tittel-/fagfraser ligger i ``data/person_name_filters.toml``.
"""
from __future__ import annotations

import re
import sys
from typing import Any, Iterator

from xlent_scanner.detectors.filter_config import load_person_name_filters
from xlent_scanner.language import SPACY_CONFIG
from xlent_scanner.models import Finding
from xlent_scanner.suppression import record_suppressed
from xlent_scanner.utils import ctx as _ctx

# Er vi inne i en PyInstaller-bundle? Pip-basert nedlasting vil alltid feile der.
_IS_FROZEN = getattr(sys, "frozen", False)

# Modell-cache og feil-cache per språk
_nlp_cache: dict[str, Any] = {}
_load_errors: dict[str, str] = {}

_MAX_CHARS = 100_000

_FILTERS = load_person_name_filters()
_STOPWORDS = _FILTERS.stopwords
_ORG_KEYWORDS = _FILTERS.org_keywords
_ORG_NAMES = _FILTERS.org_names
_GENERIC_TITLE_CASE_WORDS = _FILTERS.generic_title_case_words
_TECHNICAL_TITLE_CASE_WORDS = _FILTERS.technical_title_case_words
_PLACE_OR_THING_PRECEDERS = _FILTERS.place_or_thing_preceders
_PLACE_OR_THING_FOLLOWERS = _FILTERS.place_or_thing_followers

_LIST_SEPARATORS_RE = re.compile(r"[,;:/|]|\s+(?:og|och|and|samt|eller|or)\s+", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-zæøåäöüéèáàóòíìñß]+", re.IGNORECASE)
_CONTEXT_WINDOW_CHARS = 90
_TECHNICAL_CONTEXT_WINDOW_CHARS = 140

_REFERENCE_CONTEXT_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"\bet\s+al\.?(?=\W|$)"
    r"|"
    r"\b(?:"
    r"doi|isbn|issn|references?|bibliograph(?:y|ies|ic)|"
    r"citation|citations|cited|journal|proceedings|conference|"
    r"volume|vol\.|pages?|pp\."
    r")\b"
    r")"
)


def _normalise_profile(scan_profile: str | None) -> str:
    return "technical" if str(scan_profile or "").strip().lower() in {"technical", "academic"} else "normal"


def _words(name: str) -> list[str]:
    return _WORD_RE.findall(str(name or "").casefold())


def _looks_like_generic_title_case_phrase(name: str) -> bool:
    words = _words(name)
    if len(words) < 2:
        return False
    generic_words = _GENERIC_TITLE_CASE_WORDS | _STOPWORDS
    return all(word in generic_words for word in words)


def _looks_like_technical_title_case_phrase(name: str) -> bool:
    """Strammere filter for tekniske/akademiske dokumenter.

    I tekniske PDF-er flagger spaCy ofte fagfraser som personer fordi alle ord har
    stor forbokstav. Her forkastes fraser der minst ett ord er et sterkt teknisk
    signal og resten også ser generiske ut.
    """
    words = _words(name)
    if len(words) < 2:
        return False
    generic_words = _GENERIC_TITLE_CASE_WORDS | _STOPWORDS | _TECHNICAL_TITLE_CASE_WORDS
    has_technical_signal = any(word in _TECHNICAL_TITLE_CASE_WORDS for word in words)
    generic_count = sum(1 for word in words if word in generic_words)
    return has_technical_signal and generic_count >= len(words) - 1


def _base_name_rejection_reason(name: str, *, scan_profile: str = "normal") -> str | None:
    name = " ".join(str(name or "").strip().split())
    if not name:
        return "tom kandidat"
    folded = name.casefold()
    if folded in _ORG_NAMES:
        return "kjent organisasjonsnavn"
    if _LIST_SEPARATORS_RE.search(name):
        return "liste eller sammensatt frase"

    words = set(_words(folded))
    if any(keyword in words for keyword in _ORG_KEYWORDS if "-" not in keyword):
        return "organisasjonsord"
    if any(keyword in folded for keyword in _ORG_KEYWORDS if "-" in keyword):
        return "organisasjonsord"

    parts = name.split()
    if len(parts) < 2 or len(parts) > 4:
        return "ikke 2-4 navnedeler"
    if _looks_like_generic_title_case_phrase(name):
        return "generisk tittel-/fagfrase"
    if _normalise_profile(scan_profile) == "technical" and _looks_like_technical_title_case_phrase(name):
        return "teknisk/akademisk tittel-frase"

    for part in parts:
        part = part.strip(".,;:()[]{}«»\"'")
        if len(part) < 2:
            return "for kort navnedel"
        if any(c.isdigit() for c in part):
            return "inneholder siffer"
        if any(c in part for c in ("’", "'", "`")):
            return "inneholder apostrof eller kodetegn"
        if part.lower() in _STOPWORDS:
            return "generisk stoppord"
        if "-" in part:
            subparts = [sp for sp in part.split("-") if sp]
            for sp in subparts:
                if not sp[0].isupper():
                    return "bindestreksdel starter ikke med stor bokstav"
                if sp.isupper() and len(sp) > 2:
                    return "akronym i kandidat"
                if sp.lower() in _STOPWORDS:
                    return "generisk stoppord"
        else:
            if not part[0].isupper():
                return "navnedel starter ikke med stor bokstav"
            if part.isupper() and len(part) > 2:
                return "akronym i kandidat"
    return None


def looks_like_person_name(name: str, *, scan_profile: str = "normal") -> bool:
    """Returner True bare for konkrete personnavn."""
    return _base_name_rejection_reason(name, scan_profile=scan_profile) is None


def _context_window(text: str, start: int, end: int, *, scan_profile: str = "normal") -> str:
    radius = _TECHNICAL_CONTEXT_WINDOW_CHARS if _normalise_profile(scan_profile) == "technical" else _CONTEXT_WINDOW_CHARS
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right]


def _words_before(text: str, start: int, *, limit: int = 4) -> list[str]:
    left = max(0, start - _CONTEXT_WINDOW_CHARS)
    return _WORD_RE.findall(text[left:start].casefold())[-limit:]


def _words_after(text: str, end: int, *, limit: int = 4) -> list[str]:
    right = min(len(text), end + _CONTEXT_WINDOW_CHARS)
    return _WORD_RE.findall(text[end:right].casefold())[:limit]


def _has_place_or_technical_context(text: str, start: int, end: int) -> bool:
    before = _words_before(text, start, limit=1)
    if not before or before[-1] not in _PLACE_OR_THING_PRECEDERS:
        return False

    after = _words_after(text, end, limit=4)
    return any(word in _PLACE_OR_THING_FOLLOWERS for word in after)


def has_negative_person_name_context(
    text: str,
    start: int,
    end: int,
    *,
    scan_profile: str = "normal",
) -> bool:
    """Returner True når konteksten tyder på referanse/fagtekst, ikke PII."""
    if not text:
        return False
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    window = _context_window(text, start, end, scan_profile=scan_profile)
    if _REFERENCE_CONTEXT_RE.search(window):
        return True
    return _has_place_or_technical_context(text, start, end)


def person_name_rejection_reason(
    name: str,
    text: str = "",
    start: int = 0,
    end: int = 0,
    *,
    scan_profile: str = "normal",
) -> str | None:
    reason = _base_name_rejection_reason(name, scan_profile=scan_profile)
    if reason:
        return reason
    if has_negative_person_name_context(text, start, end, scan_profile=scan_profile):
        return "referanse-, sted- eller fagkontekst"
    return None


def looks_like_person_name_in_context(
    name: str,
    text: str,
    start: int,
    end: int,
    *,
    scan_profile: str = "normal",
) -> bool:
    """Returner True bare når både navn og kontekst ser ut som person-PII."""
    return person_name_rejection_reason(
        name,
        text,
        start,
        end,
        scan_profile=scan_profile,
    ) is None


def _looks_like_name(name: str) -> bool:
    return looks_like_person_name(name)


# ── Modellhåndtering ──────────────────────────────────────────────────────────

def reset_cache_for_model(model_name: str) -> None:
    """Tøm NER-cache for en gitt modell (kalles etter nedlasting)."""
    lang_for_model = {cfg["model"]: lang for lang, cfg in SPACY_CONFIG.items()}
    lang = lang_for_model.get(model_name)
    if lang:
        _nlp_cache.pop(lang, None)
        _load_errors.pop(lang, None)


def _get_nlp(lang: str = "nb") -> Any | None:
    if lang in _nlp_cache:
        return _nlp_cache[lang]

    cfg = SPACY_CONFIG.get(lang, SPACY_CONFIG["nb"])
    model_name = cfg["model"]

    try:
        from xlent_scanner.model_manager import model_path as _user_model_path  # noqa: PLC0415
        user_path = _user_model_path(model_name)
    except Exception:
        user_path = None

    if lang in _load_errors:
        if user_path is not None:
            del _load_errors[lang]
        else:
            return None

    try:
        import spacy  # type: ignore

        if user_path is not None:
            nlp = spacy.load(str(user_path))
        else:
            nlp = spacy.load(model_name)

        _nlp_cache[lang] = nlp
        return nlp

    except OSError:
        if _IS_FROZEN:
            _load_errors[lang] = (
                f"spaCy-modell ({model_name}) er ikke installert. "
                f"Gå til Innstillinger → Navnemodeller for å laste ned."
            )
            return None
        try:
            from spacy.cli import download as spacy_download  # type: ignore
            print(f"[ner] Laster ned manglende modell: {model_name}…", flush=True)
            spacy_download(model_name)
            nlp = spacy.load(model_name)
            _nlp_cache[lang] = nlp
            print(f"[ner] ✓ {model_name} lastet.", flush=True)
            return nlp
        except BaseException as exc:
            _load_errors[lang] = (
                f"Klarte ikke å laste ned spaCy-modell ({model_name}): {exc}"
            )
            return None
    except BaseException as exc:
        _load_errors[lang] = f"Klarte ikke å laste spaCy-modell ({model_name}): {exc}"
        return None


def get_load_error(lang: str = "nb") -> str | None:
    _get_nlp(lang)
    return _load_errors.get(lang)


# ── Deteksjon ─────────────────────────────────────────────────────────────────

def find_names(text: str, lang: str = "nb", *, scan_profile: str = "normal") -> Iterator[Finding]:
    nlp = _get_nlp(lang)
    if nlp is None:
        return

    cfg = SPACY_CONFIG.get(lang, SPACY_CONFIG["nb"])
    ner_label = cfg["ner_label"]

    doc = nlp(text[:_MAX_CHARS])
    seen: set[str] = set()
    for ent in doc.ents:
        if ent.label_ != ner_label:
            continue
        name = ent.text.strip()
        if "#" in name or name.startswith("-"):
            continue
        reason = person_name_rejection_reason(
            name,
            text,
            ent.start_char,
            ent.end_char,
            scan_profile=scan_profile,
        )
        if reason:
            record_suppressed(
                "navn (person)",
                name,
                _ctx(text, ent.start_char, ent.end_char),
                reason,
                source="spaCy",
            )
            continue
        if name not in seen:
            seen.add(name)
            yield Finding(
                "navn (person)",
                name,
                _ctx(text, ent.start_char, ent.end_char),
            )


def detect_names(text: str, lang: str = "nb", *, scan_profile: str = "normal") -> list[Finding]:
    return list(find_names(text, lang, scan_profile=scan_profile))
