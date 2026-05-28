"""Danske regex-detektorer med validering.

Kategorier:
  - CPR-nummer  (10 siffer, mod-11, datovalidering)
  - e-post      (håndtert av find_emails i regex_no.py)
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx_base


def _ctx(text: str, start: int, end: int, radius: int = 40) -> str:
    return _ctx_base(text, start, end, radius)


# ── CPR-nummer ────────────────────────────────────────────────────────────────
# Format: DDMMYY-NNNN (med bindestrek) eller DDMMYYNNNN (uten)

_CPR_RAW = re.compile(
    r"\b(\d{6})-(\d{4})\b"   # med bindestrek: 210572-1234
    r"|\b(\d{10})\b"          # uten skilletegn: 2105721234
)

_CPR_WEIGHTS = [4, 3, 2, 7, 6, 5, 4, 3, 2, 1]


def _validate_cpr(s: str) -> bool:
    """Valider dansk CPR-nummer med mod-11.

    Merk: CPRer utstedt etter 1999 oppfyller ikke alltid mod-11,
    men vi bruker det som primærfilter for høy presisjon.
    """
    if len(s) != 10 or not s.isdigit():
        return False
    d = [int(c) for c in s]
    day = d[0] * 10 + d[1]
    month = d[2] * 10 + d[3]
    if not (1 <= day <= 31) or not (1 <= month <= 12):
        return False
    # Mod-11
    total = sum(digit * weight for digit, weight in zip(d, _CPR_WEIGHTS))
    return total % 11 == 0


def find_cpr(text: str) -> Iterator[Finding]:
    for m in _CPR_RAW.finditer(text):
        if m.group(1) is not None:
            raw     = m.group(1) + m.group(2)
            display = m.group(0).strip()
        else:
            raw     = m.group(3)
            display = m.group(3)
        if _validate_cpr(raw):
            yield Finding("cpr-nummer", display, _ctx(text, m.start(), m.end()))


def detect_da_specific(text: str) -> list[Finding]:
    """Danske mønstre (e-post dekkes av find_emails)."""
    return list(find_cpr(text))
