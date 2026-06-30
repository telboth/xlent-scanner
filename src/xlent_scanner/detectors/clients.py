"""Detektor for kjente kundenavn.

Matcher mot listen i data/clients.toml.
Treff gir kategori 'kundenavn' med gul alvorlighetsgrad.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx_base

_CLIENTS_FILE = Path(__file__).parent.parent / "data" / "clients.toml"
_patterns: list[tuple[str, re.Pattern[str]]] | None = None

_COMPANY_SUFFIX_RE = re.compile(
    r"(?<![\w@])"
    r"("
    r"[A-ZÆØÅÄÖÜ][A-Za-zÆØÅæøåÄÖäöÜüÉéÈèÁáÀàÓóÒòÍíÌìÑñß0-9&.'-]{1,}"
    r"(?:\s+[A-ZÆØÅÄÖÜ][A-Za-zÆØÅæøåÄÖäöÜüÉéÈèÁáÀàÓóÒòÍíÌìÑñß0-9&.'-]{1,}){0,4}"
    r")"
    r"\s+"
    r"(AS|ASA|LTD|LLC)"
    r"\b",
)


def _get_patterns() -> list[tuple[str, re.Pattern[str]]]:
    global _patterns
    if _patterns is not None:
        return _patterns
    if not _CLIENTS_FILE.exists():
        _patterns = []
        return _patterns
    with open(_CLIENTS_FILE, "rb") as f:
        data = tomllib.load(f)
    _patterns = [
        (name, re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE))
        for name in data.get("names", [])
    ]
    return _patterns


def _ctx(text: str, start: int, end: int, radius: int = 50) -> str:
    return _ctx_base(text, start, end, radius)


def find_client_names(text: str) -> Iterator[Finding]:
    for name, pattern in _get_patterns():
        for m in pattern.finditer(text):
            yield Finding("kundenavn", m.group(0), _ctx(text, m.start(), m.end()))


def find_company_suffix_names(text: str) -> Iterator[Finding]:
    """Finn selskapsnavn med juridisk suffix, f.eks. «Acme AS» eller «Foo LLC».

    Dette er en presis regel under Firmanavn-kategorien. Den krever stor
    forbokstav i navnedelen og ett av få eksplisitte juridiske suffix for å
    unngå generiske fraser.
    """
    seen: set[str] = set()
    for m in _COMPANY_SUFFIX_RE.finditer(text):
        value = f"{m.group(1)} {m.group(2)}".strip()
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        yield Finding("kundenavn", value, _ctx(text, m.start(), m.end()))


def detect_clients(text: str) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(find_client_names(text))
    findings.extend(find_company_suffix_names(text))
    return findings
