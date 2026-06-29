"""Detektor for nettadresser (URL-er).

Finner:
  - HTTP/HTTPS URL-er:  https://example.com/path?q=1
  - www.-adresser:      www.vg.no  www.xlent.no/om-oss

E-postadresser (format: bruker@domene.tld) er IKKE inkludert
– de håndteres av find_emails() i regex_no.py.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx_base


def _ctx(text: str, start: int, end: int, radius: int = 60) -> str:
    return _ctx_base(text, start, end, radius)


# HTTP/HTTPS URL-er – fanger det meste unntatt whitespace og vanlige termineringer
_HTTP_RE = re.compile(
    r"https?://[^\s<>\"')}\]]{4,}",
    re.IGNORECASE,
)

# www.-adresser uten protokoll – krev minst ett punkt-tegn etter www.
_WWW_RE = re.compile(
    r"\bwww\.[a-zA-Z0-9][a-zA-Z0-9\-]{0,61}\.[a-zA-Z]{2,}"
    r"(?:[/\w\-._~:/?#\[\]@!$&'()*+,;=%]*)?",
    re.IGNORECASE,
)

# Tegn som ofte henger etter en URL i løpende tekst
_TRAILING = re.compile(r"[.,;:!?)]+$")


def _is_doi_resolver_url(url: str) -> bool:
    """Returner True for DOI-resolvere som ikke er personvernsensitive nettadresser."""
    candidate = url if "://" in url else f"https://{url}"
    host = (urlparse(candidate).hostname or "").casefold()
    return host == "doi.org" or host.endswith(".doi.org")


def detect_urls(text: str) -> Iterator[Finding]:
    """Finn HTTP/HTTPS URL-er og www.-adresser i teksten (gul alvorlighetsgrad)."""
    seen: set[str] = set()

    for pattern in (_HTTP_RE, _WWW_RE):
        for m in pattern.finditer(text):
            raw = m.group()
            # Fjern tegnsetting som henger etter URL-en
            cleaned = _TRAILING.sub("", raw)
            if len(cleaned) < 5:
                continue
            # Hopp over e-postlignende strenger (har @)
            if "@" in cleaned:
                continue
            # DOI-lenker i akademiske referanser gir ofte mye støy og peker
            # normalt til publikasjoner, ikke person-/kundedata.
            if _is_doi_resolver_url(cleaned):
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            start = m.start()
            end = start + len(cleaned)
            yield Finding(
                category="nettadresse",
                text=cleaned,
                context=_ctx(text, start, end),
            )
