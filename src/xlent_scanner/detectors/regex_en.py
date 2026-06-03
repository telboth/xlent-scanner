"""Engelske regex-detektorer med validering.

Kategorier:
  - UK National Insurance Number  (format AA 99 99 99 A)
  - US Social Security Number     (format XXX-XX-XXXX)
  - US phone number               ((234) 567-8901, +1 (234) 567-8901)
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx


# ── UK National Insurance Number ──────────────────────────────────────────────
#
# Format: AA 99 99 99 A
# Regler:
#   - Første bokstav: ikke D, F, I, Q, U, V
#   - Andre bokstav:  ikke D, F, I, O, Q, U, V  (O er ekstra ugyldig)
#   - Prefiks ikke: BG, GB, NK, KN, NT, TN, ZZ  (reserverte)
#   - Siste bokstav: A, B, C eller D

_NI_RE = re.compile(
    r"(?<![A-Z\d])"
    r"([A-CE-HJ-PR-TW-Z])"         # første bokstav (ekskl. D,F,I,Q,U,V)
    r"([A-CE-HJ-NPR-TW-Z])"        # andre bokstav  (ekskl. D,F,I,O,Q,U,V)
    r"[\s]?"
    r"(\d{2})"
    r"[\s]?"
    r"(\d{2})"
    r"[\s]?"
    r"(\d{2})"
    r"[\s]?"
    r"([A-Da-d])"
    r"(?![A-Z\d])",
    re.IGNORECASE,
)

_NI_INVALID_PREFIXES: frozenset[str] = frozenset(
    {"BG", "GB", "NK", "KN", "NT", "TN", "ZZ"}
)


def find_uk_ni(text: str) -> Iterator[Finding]:
    for m in _NI_RE.finditer(text):
        prefix = (m.group(1) + m.group(2)).upper()
        if prefix in _NI_INVALID_PREFIXES:
            continue
        raw = m.group(0).replace(" ", "").upper()
        formatted = f"{raw[:2]} {raw[2:4]} {raw[4:6]} {raw[6:8]} {raw[8]}"
        yield Finding(
            "UK National Insurance Number",
            formatted,
            _ctx(text, m.start(), m.end()),
            severity="svart",
        )


# ── US Social Security Number ─────────────────────────────────────────────────
#
# Format: XXX-XX-XXXX  (bindestrek er obligatorisk for å unngå for mange falske positiver)
# Regler:
#   - AAA: ikke 000, ikke 666, ikke 900-999
#   - BB:  ikke 00
#   - CCCC: ikke 0000

_SSN_RE = re.compile(
    r"(?<!\d)"
    r"(\d{3})"
    r"-"
    r"(\d{2})"
    r"-"
    r"(\d{4})"
    r"(?!\d)"
)


def _validate_ssn(a: str, b: str, c: str) -> bool:
    ai = int(a)
    if ai == 0 or ai == 666 or 900 <= ai <= 999:
        return False
    if int(b) == 0:
        return False
    if int(c) == 0:
        return False
    return True


def find_us_ssn(text: str) -> Iterator[Finding]:
    for m in _SSN_RE.finditer(text):
        a, b, c = m.group(1), m.group(2), m.group(3)
        if _validate_ssn(a, b, c):
            masked = f"{a[:1]}**-**-{c[-4:]}"
            f = Finding(
                "US Social Security Number",
                masked,
                _ctx(text, m.start(), m.end()),
                severity="svart",
            )
            f.raw_text = f"{a}-{b}-{c}"
            yield f


# ── US/NANP telefonnummer ────────────────────────────────────────────────────
#
# Presist format for å unngå vanlige tall-falskpositiver:
#   (234) 567-8901
#   234-567-8901
#   234 567 8901
#   +1 (234) 567-8901 / +01 (234) 567-8901
# NANP krever at area code og central office code ikke starter med 0/1.

_US_PHONE_RE = re.compile(
    r"(?<![\w])"
    r"(?:(?:\+?1|\+01|001)[\s.\-]*)?"
    r"(?:\(([2-9]\d{2})\)|([2-9]\d{2}))"
    r"[\s.\-]*"
    r"([2-9]\d{2})"
    r"[\s.\-]*"
    r"(\d{4})"
    r"(?![\w])"
)


def find_us_phone(text: str) -> Iterator[Finding]:
    for m in _US_PHONE_RE.finditer(text):
        yield Finding(
            "telefonnummer",
            m.group(0).strip(),
            _ctx(text, m.start(), m.end()),
        )


# ── Samlet ────────────────────────────────────────────────────────────────────

def detect_en_specific(text: str) -> list[Finding]:
    """Engelske mønstre: UK NI-nummer, US SSN og US telefonnummer."""
    findings: list[Finding] = []
    for fn in (find_uk_ni, find_us_ssn, find_us_phone):
        findings.extend(fn(text))
    return findings
