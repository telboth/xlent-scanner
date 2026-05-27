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

_CLIENTS_FILE = Path(__file__).parent.parent / "data" / "clients.toml"
_patterns: list[tuple[str, re.Pattern[str]]] | None = None


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
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi].replace("\n", " ")
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(text) else "")


def find_client_names(text: str) -> Iterator[Finding]:
    for name, pattern in _get_patterns():
        for m in pattern.finditer(text):
            yield Finding("kundenavn", m.group(0), _ctx(text, m.start(), m.end()))


def detect_clients(text: str) -> list[Finding]:
    return list(find_client_names(text))
