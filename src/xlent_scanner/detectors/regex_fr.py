"""Franske regex-detektorer med validering.

Kategorier:
  - Numéro INSEE (Sécurité sociale): 15 siffer, kontrollert med clé = 97 - (N mod 97)
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx


# ── Numéro de sécurité sociale (INSEE) ───────────────────────────────────────
# Format: S AA MM DDD CCC KK  (15 tegn totalt, vises gjerne som S-AA-MM-DDD-CCC-KK)
# S: 1=menn, 2=kvinner (og spesielle koder)
# AA: fødselsår, MM: fødselsmåned, DDD: departement+kommune, CCC: rekkefølge
# KK: clé = 97 - (13-sifret-grunntal mod 97)

_INSEE_COMPACT = re.compile(
    r"(?<!\d)"
    r"([12][0-9]{2}(?:0[1-9]|1[0-2]|20)\d{6}\d{2})"  # kompakt 15 siffer
    r"(?!\d)"
)

_INSEE_SPACED = re.compile(
    r"(?<!\d)"
    r"([12][\s\-]?\d{2}[\s\-]?(?:0[1-9]|1[0-2]|20)[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{2})"
    r"(?!\d)"
)

_INSEE_KW = re.compile(
    r"(?i)(?:num[eé]ro?\s*(?:de\s*)?s[eé]curit[eé]\s*sociale|insee|n[oº°]?\s*ss|nir\b|s[eé]cu\.?)",
)


def _validate_insee(s: str) -> bool:
    digits = re.sub(r"[\s\-]", "", s)
    if len(digits) != 15 or not digits.isdigit():
        return False
    base = int(digits[:13])
    key = int(digits[13:])
    expected = 97 - (base % 97)
    return key == expected


def find_insee(text: str) -> Iterator[Finding]:
    seen: set[str] = set()
    kw_pos = {m.start() for m in _INSEE_KW.finditer(text)}

    for pattern in (_INSEE_SPACED, _INSEE_COMPACT):
        for m in pattern.finditer(text):
            raw = m.group(1)
            compact = re.sub(r"[\s\-]", "", raw)
            if compact in seen:
                continue
            nearby = any(abs(m.start() - kp) < 150 for kp in kw_pos)
            if not nearby and len(compact) == 15:
                # Uten nøkkelord: krev validering
                if not _validate_insee(compact):
                    continue
            if _validate_insee(compact):
                seen.add(compact)
                yield Finding(
                    "numéro de sécurité sociale (FR)",
                    raw.strip(),
                    _ctx(text, m.start(), m.end()),
                    severity="svart",
                )


# ── Samlet ────────────────────────────────────────────────────────────────────

def detect_fr_specific(text: str) -> list[Finding]:
    return list(find_insee(text))
