"""Kontekstfiltre for bibliografiske referanser.

Brukes av tallbaserte detektorer for å unngå at DOI/ISBN/ISSN-lignende
referanser feiltolkes som telefonnumre eller timesatser.
"""
from __future__ import annotations

import re

_BIBLIOGRAPHIC_LABEL_RE = re.compile(
    r"\b(?:doi|isbn(?:-1[03])?|issn|isdn)\b|doi\.org",
    re.IGNORECASE,
)
_DOI_VALUE_RE = re.compile(r"\b10\.\d{4,9}/[^\s,;]+", re.IGNORECASE)
_PAGE_LABEL_PREFIX_RE = re.compile(
    r"\b(?:p|pp|pages?)\.?\s*$",
    re.IGNORECASE,
)


def has_bibliographic_context(
    text: str,
    start: int,
    end: int,
    *,
    radius: int = 48,
) -> bool:
    """Returner True hvis kandidatspennet ligger i DOI/ISBN/ISSN-kontekst."""
    if not text:
        return False
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    window = text[lo:hi]
    prefix = text[lo:start]
    return bool(
        _BIBLIOGRAPHIC_LABEL_RE.search(window)
        or _DOI_VALUE_RE.search(window)
        or _PAGE_LABEL_PREFIX_RE.search(prefix)
    )
