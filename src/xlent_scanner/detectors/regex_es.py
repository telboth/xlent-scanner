"""Spanske regex-detektorer med validering.

Kategorier:
  - DNI  (Documento Nacional de Identidad): 8 siffer + kontrollbokstav
  - NIE  (Número de Identidad de Extranjero): X/Y/Z + 7 siffer + kontrollbokstav
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx

# Kontrollbokstav-tabell (modulo 23)
_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


# ── DNI ───────────────────────────────────────────────────────────────────────

_DNI_RAW = re.compile(
    r"(?<![A-Z0-9])"
    r"(\d{8}[\s\-]?[A-Z])"
    r"(?![A-Z0-9])"
)


def _validate_dni(s: str) -> bool:
    s = re.sub(r"[\s\-]", "", s.upper())
    if len(s) != 9 or not s[:8].isdigit() or not s[8].isalpha():
        return False
    return _DNI_LETTERS[int(s[:8]) % 23] == s[8]


def find_dni(text: str) -> Iterator[Finding]:
    for m in _DNI_RAW.finditer(text):
        raw = m.group(1)
        if _validate_dni(raw):
            yield Finding(
                "DNI (ES)",
                re.sub(r"[\s\-]", "", raw.upper()),
                _ctx(text, m.start(), m.end()),
                severity="svart",
            )


# ── NIE ───────────────────────────────────────────────────────────────────────

_NIE_RAW = re.compile(
    r"(?<![A-Z0-9])"
    r"([XYZxyz][\s\-]?\d{7}[\s\-]?[A-Za-z])"
    r"(?![A-Z0-9])"
)

_NIE_MAP = {"X": "0", "Y": "1", "Z": "2"}


def _validate_nie(s: str) -> bool:
    s = re.sub(r"[\s\-]", "", s.upper())
    if len(s) != 9:
        return False
    prefix = s[0]
    if prefix not in _NIE_MAP:
        return False
    number = _NIE_MAP[prefix] + s[1:8]
    if not number.isdigit():
        return False
    return _DNI_LETTERS[int(number) % 23] == s[8]


def find_nie(text: str) -> Iterator[Finding]:
    for m in _NIE_RAW.finditer(text):
        raw = m.group(1)
        if _validate_nie(raw):
            yield Finding(
                "NIE (ES)",
                re.sub(r"[\s\-]", "", raw.upper()),
                _ctx(text, m.start(), m.end()),
                severity="svart",
            )


# ── Samlet ────────────────────────────────────────────────────────────────────

def detect_es_specific(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for fn in (find_dni, find_nie):
        findings.extend(fn(text))
    return findings
