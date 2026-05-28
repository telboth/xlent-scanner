"""IBAN-detektor med MOD-97 validering.

Dekker alle europeiske og vanlige internasjonale banker.
Format: 2 bokstaver (landkode) + 2 sjekksiffer + opptil 30 alfanumeriske (BBAN).
Støtter både kompakt og spaced format (mellomrom etter hver 4. tegn).

Severity: rød — internasjonalt bankkontonummer er høyst sensitiv finansinfo.
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx_base


def _ctx(text: str, start: int, end: int, radius: int = 45) -> str:
    return _ctx_base(text, start, end, radius)


# ── Kjente IBAN-landkoder ─────────────────────────────────────────────────────

_IBAN_COUNTRIES: frozenset[str] = frozenset({
    "AD","AE","AL","AT","AZ","BA","BE","BG","BH","BR","BY",
    "CH","CR","CY","CZ","DE","DJ","DK","DO","EE","EG","ES",
    "FI","FK","FR","GB","GE","GI","GL","GR","GT","HR","HU",
    "IE","IL","IQ","IS","IT","JO","KW","KZ","LB","LC","LI",
    "LT","LU","LV","LY","MC","MD","ME","MK","MN","MR","MT",
    "MU","NI","NL","NO","OM","PK","PL","PS","PT","QA","RO",
    "RS","SA","SC","SD","SE","SI","SK","SM","SO","ST",
    "TL","TN","TR","UA","VA","VG","XK",
})

# ── Regex ─────────────────────────────────────────────────────────────────────
# Matcher kompakt: NO938601117947  og spaced: NO93 8601 1117 947
_IBAN_RE = re.compile(
    r"(?<![A-Z0-9])"
    r"([A-Z]{2}[0-9]{2}"              # landkode + kontrollsifre (4 tegn)
    r"(?:\s?[A-Z0-9]{4}){2,7}"        # mellomgrupper á 4 tegn (spaced eller kompakt)
    r"\s?[A-Z0-9]{1,4})"              # siste gruppe (1-4 tegn)
    r"(?![A-Z0-9])",
    re.IGNORECASE,
)


# ── MOD-97 validering ─────────────────────────────────────────────────────────

def _iban_valid(raw: str) -> bool:
    iban = raw.replace(" ", "").upper()
    # Minimum/maksimum lengde for kjente land (korteste er NO = 15 tegn)
    if not (14 <= len(iban) <= 34):
        return False
    if iban[:2] not in _IBAN_COUNTRIES:
        return False
    # Flytt de 4 første tegnene til slutten
    rearranged = iban[4:] + iban[:4]
    # Erstatt bokstaver med tall: A=10, B=11, ..., Z=35
    numeric = ""
    for c in rearranged:
        if c.isdigit():
            numeric += c
        elif "A" <= c <= "Z":
            numeric += str(ord(c) - 55)   # A:65-55=10, ..., Z:90-55=35
        else:
            return False
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


# ── Deteksjon ─────────────────────────────────────────────────────────────────

def find_iban(text: str) -> Iterator[Finding]:
    seen: set[str] = set()
    for m in _IBAN_RE.finditer(text):
        candidate = m.group(1)
        compact = candidate.replace(" ", "").upper()
        if compact in seen:
            continue
        if _iban_valid(candidate):
            seen.add(compact)
            # Masker: vis landkode + kontrollsifre + *** + siste 4 tegn
            masked = compact[:4] + "…" + compact[-4:]
            f = Finding(
                "IBAN",
                masked,
                _ctx(text, m.start(), m.end()),
                severity="rød",
            )
            f.raw_text = compact
            yield f


def detect_iban(text: str) -> list[Finding]:
    return list(find_iban(text))
