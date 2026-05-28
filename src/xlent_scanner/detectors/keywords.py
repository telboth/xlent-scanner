"""Detektor for konfidensialitets- og sikkerhetsmarkører.

Skiller mellom:
  - Funn i Markdown-headings (# ## ###) → «konfidensielt dokument (overskrift)»
  - Funn i brødtekst               → «konfidensielt dokument»

Docling eksporterer til Markdown, så heading-deteksjon er direkte.
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx_base


def _ctx(text: str, start: int, end: int, radius: int = 60) -> str:
    return _ctx_base(text, start, end, radius)


# Ord som indikerer at dokumentet er ment som konfidensielt
# Dekker norsk, svensk og engelsk
_CONFIDENTIAL_TERMS = [
    # Norsk
    "konfidensielt", "strengt konfidensielt",
    "fortrolig", "strengt fortrolig",
    "kun til intern bruk", "ikke for distribusjon",
    "hemmelig", "taushetsplikt", "begrenset tilgang",
    # Svensk
    "konfidentiellt", "strikt konfidentiellt",
    "hemlig", "hemligt",
    "sekretess", "tystnadsplikt",
    "ej för distribution", "internt bruk",
    "skyddat",
    # Engelsk
    "confidential", "strictly confidential",
    "internal use only", "restricted",
    "not for distribution", "top secret",
    "classified", "proprietary", "trade secret",
    "privileged and confidential", "eyes only",
    # Felles forkortelser og avtaler
    "nda", "non-disclosure", "dpa",
]

# Ord som indikerer kildekode eller konfig som ikke bør deles
_CODE_TERMS = [
    "api_key", "api-key", "apikey",
    "access_token", "refresh_token",
    "client_secret", "client_id",
    "database_url", "db_password",
    "private_key", "secret_key",
    "auth_token", "bearer",
]

_CONF_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(t) for t in _CONFIDENTIAL_TERMS) + r")(?!\w)",
    re.IGNORECASE,
)

_CODE_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(t) for t in _CODE_TERMS) + r")(?!\w)",
    re.IGNORECASE,
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _headings(text: str) -> list[tuple[int, int, str]]:
    """Returnerer (start, end, heading-tekst) for alle Markdown-headings."""
    return [(m.start(), m.end(), m.group(2)) for m in _HEADING_RE.finditer(text)]


def find_confidential_markers(text: str) -> Iterator[Finding]:
    heading_spans = _headings(text)

    def _in_heading(pos: int) -> bool:
        return any(start <= pos <= end for start, end, _ in heading_spans)

    for m in _CONF_PATTERN.finditer(text):
        label = (
            "konfidensielt dokument (overskrift)"
            if _in_heading(m.start())
            else "konfidensielt dokument (brødtekst)"
        )
        yield Finding(label, m.group(0), _ctx(text, m.start(), m.end()))

    for m in _CODE_PATTERN.finditer(text):
        yield Finding("konfigurasjonsord (mulig secret)", m.group(0), _ctx(text, m.start(), m.end()))


def detect_keywords(text: str) -> list[Finding]:
    return list(find_confidential_markers(text))
