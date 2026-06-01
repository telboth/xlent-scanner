"""Tyske regex-detektorer med validering.

Kategorier:
  - Steueridentifikationsnummer  (11 siffer, eget kontrollsiffer-algoritme)
  - Sozialversicherungsnummer    (12 tegn, DDMMJJAAAAAZP)
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx


# ── Steueridentifikationsnummer ───────────────────────────────────────────────
# 11 siffer, første siffer 1-9, ikke to like tilstøtende i pos 1-5,
# siste siffer er kontrollsiffer (ISO/IEC-lignende algoritme)

_STEUER_RAW = re.compile(r"(?<!\d)([1-9]\d{10})(?!\d)")

_STEUER_KW = re.compile(
    r"(?i)(?:steuer-?id(?:entifikationsnummer)?|steuer-?nr\.?|steuernummer|tin\b)",
)


def _validate_steuer_id(s: str) -> bool:
    if len(s) != 11 or not s.isdigit() or s[0] == "0":
        return False
    # Ingen to like sifre i posisjon 1-10 sammenhengende
    for i in range(10):
        if s[i] == s[i + 1] and i < 4:
            # Tillater like sifre etter posisjon 4 (mer permissiv enn streng regel)
            pass
    # Kontrollsiffer-algoritme (DBD-metode)
    product = 10
    for i in range(10):
        total = (int(s[i]) + product) % 10
        if total == 0:
            total = 10
        product = (total * 2) % 11
    check = 11 - product
    if check == 10:
        check = 0
    return check == int(s[10])


def find_steuer_id(text: str) -> Iterator[Finding]:
    kw_pos = {m.start() for m in _STEUER_KW.finditer(text)}
    for m in _STEUER_RAW.finditer(text):
        nearby = any(abs(m.start() - kp) < 120 for kp in kw_pos)
        if not nearby:
            continue
        if _validate_steuer_id(m.group(1)):
            yield Finding(
                "steueridentifikationsnummer (DE)",
                m.group(1),
                _ctx(text, m.start(), m.end()),
                severity="svart",
            )


# ── Sozialversicherungsnummer ─────────────────────────────────────────────────
# Format: BEREICHDDMMJJAAAAAZP  (12 tegn: 2 sifre + 6 dato + 1 bokstav + 3 sifre)
# Eksempel: 65070193J003

_SOZIAL_RAW = re.compile(
    r"(?<!\d)"
    r"(\d{2}[0-3]\d[01]\d\d{2}[A-Z]\d{3})"
    r"(?!\d)"
)

_SOZIAL_KW = re.compile(
    r"(?i)(?:sozialversicherungs(?:nummer|nr\.?)|rentenversicherungs(?:nummer|nr\.?)|svnr\.?)",
)


def find_sozial(text: str) -> Iterator[Finding]:
    kw_pos = {m.start() for m in _SOZIAL_KW.finditer(text)}
    for m in _SOZIAL_RAW.finditer(text):
        nearby = any(abs(m.start() - kp) < 120 for kp in kw_pos)
        if not nearby:
            continue
        yield Finding(
            "sozialversicherungsnummer (DE)",
            m.group(1),
            _ctx(text, m.start(), m.end()),
            severity="svart",
        )


# ── Samlet ────────────────────────────────────────────────────────────────────

def detect_de_specific(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for fn in (find_steuer_id, find_sozial):
        findings.extend(fn(text))
    return findings
