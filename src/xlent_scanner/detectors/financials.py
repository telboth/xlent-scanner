"""Detektor for forretningskonfidensielle finansielle data.

Ser etter fire kategorier:
  1. Timepris  — beløp knyttet til pris per time/dag  (gul)
  2. Dagspris  — som timepris, men per dag            (gul)
  3. Prosjektsum — totalsummer og budsjetter          (gul)
  4. Margin / rabatt — prosentsatser for marginer     (gul)

Strategi: krever ENTEN et tydelig nøkkelord ELLER en per-enhet-indikator
(/time, /h, /dag) for å minimere falske positiver.

Severity: gul — forretningssensitivt, men ikke persondata.
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx_base


def _ctx(text: str, start: int, end: int, radius: int = 55) -> str:
    return _ctx_base(text, start, end, radius)


def _clean_amount(s: str) -> str:
    """Fjern ledende/etterfølgende mellomrom og normaliser."""
    return s.strip().rstrip(".,")


# ── A: Beløp / enhet  (høyest presisjon) ──────────────────────────────────────
# Matcher:  "1 850 kr/time",  "NOK 2 200/h",  "1850,-/t",  "1 500 per dag"
_TIME_UNITS = r"time?r?|t(?:\.|imen?s?)?|h(?:\.|our)?s?|tim(?:e|mar)?|timme[rn]?"
_DAY_UNITS  = r"dag?s?|day?s?|dygn"

_RATE_SLASH_RE = re.compile(
    r"(?<!\d)"
    r"((?:NOK|SEK|kr)\s*)?"                                     # valgfri valuta foran
    r"(\d{2,6}(?:[., \t]\d{3})*(?:[.,]\d{1,2})?)"               # beløp (min 2 sifre)
    r"\s*(?:kr|NOK|SEK|,-)?"                                    # valgfri valuta bak
    r"\s*(?:/|per\s+)"                                          # separator
    r"(?P<unit>" + _TIME_UNITS + r"|" + _DAY_UNITS + r")\b",
    re.IGNORECASE,
)


# ── B: Timepris/dagspris nøkkelord + beløp ────────────────────────────────────
# Matcher:  "Timepris: 1 850",  "Konsulentpris NOK 2200",  "hourly rate: £1,200"
_RATE_KW_RE = re.compile(
    r"(?P<kw>"
        r"timepris|timkostnad|konsulentpris|timrate|tim(?:taxa|taxa)"
        r"|konsulttaxa|konsulttariff|timarvodet"
        r"|dagspris|dagsrate|dagkostnad|dagstimmar"
        r"|hourly[\s\-]rate|day[\s\-]rate|billing[\s\-]rate|charge[\s\-]out"
        r"|sats(?:\s+per\s+(?:time|dag))?"
    r")"
    r"\s*:?\s*"
    r"(?:NOK|SEK|DKK|EUR|USD|£|kr)?\s*"
    r"(\d{2,6}(?:[., \t]\d{3})*(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)


# ── C: Prosjektsum / budsjett / kontraktsverdi ─────────────────────────────────
# Matcher:  "Prosjektsum: 4,5 MNOK",  "Budsjett: NOK 2.4 mill",  "Total: 450 000 kr"
_SCALE = r"(?:\s*(?:mill(?:ion(?:er)?)?|mrd|milliarder?|MNOK|MSEK|MEUR|k|K))??"
_SUM_KW_RE = re.compile(
    r"(?:"
        r"budsjett|prosjektsum|tilbudssum|kontraktsverdi|prosjektkostnad"
        r"|total\s+kostnad|samlet\s+(?:pris|sum|kostnad)|fakturabeløp"
        r"|anbudssum|pristilbud"
        r"|offertsumma|offertvärde|projektbudget|kontraktsvärde|projektkostnad"
        r"|contract\s+value|project\s+(?:budget|cost|value)"
        r"|total\s+(?:cost|value|amount|sum|fee)"
        r"|invoice\s+(?:total|amount)|quote\s+(?:total|value)"
    r")"
    r"\s*:?\s*"
    r"(?:NOK|SEK|DKK|EUR|USD|£|kr|€|\$)?\s*"
    r"(\d{1,3}(?:[., \t]\d{3})*(?:[.,]\d{1,2})?)"
    r"(?:" + _SCALE + r"\s*(?:NOK|SEK|DKK|EUR|USD|kr|mill\w*|MNOK|MSEK))?",
    re.IGNORECASE,
)


# ── D: Margin / rabatt / påslag (prosentsats) ──────────────────────────────────
# Matcher:  "Margin: 35%",  "Rabatt 20 %",  "Påslag: 12,5%",  "discount: 15%"
_MARGIN_RE = re.compile(
    r"(?P<kw>"
        r"margin(?:al)?|bruttomargin|nettomarg\w*|fortjeneste"
        r"|påslag|rabatt|avslag"
        r"|marginal|bruttomarginal"
        r"|discount|markup|gross[\s\-]margin|net[\s\-]margin|profit[\s\-]margin"
    r")"
    r"\s*:?\s*"
    r"(\d{1,3}(?:[.,]\d{1,2})?)"
    r"\s*%",
    re.IGNORECASE,
)


# ── Samlet ────────────────────────────────────────────────────────────────────

def find_financial_data(text: str) -> Iterator[Finding]:
    seen: set[tuple] = set()

    # A: rate per enhet
    for m in _RATE_SLASH_RE.finditer(text):
        amount = _clean_amount(m.group(2))
        unit   = m.group("unit").lower()
        cat    = "dagspris" if re.match(_DAY_UNITS, unit, re.IGNORECASE) else "timepris"
        key    = (cat, amount)
        if key not in seen:
            seen.add(key)
            yield Finding(cat, amount, _ctx(text, m.start(), m.end()), severity="gul")

    # B: rate nøkkelord
    for m in _RATE_KW_RE.finditer(text):
        amount = _clean_amount(m.group(2))
        kw     = m.group("kw").lower()
        cat    = "dagspris" if any(x in kw for x in ("dag", "day")) else "timepris"
        key    = (cat, amount)
        if key not in seen:
            seen.add(key)
            yield Finding(cat, amount, _ctx(text, m.start(), m.end()), severity="gul")

    # C: prosjektsum
    for m in _SUM_KW_RE.finditer(text):
        amount = _clean_amount(m.group(1))
        key    = ("prosjektsum", amount)
        if key not in seen:
            seen.add(key)
            yield Finding("prosjektsum", amount, _ctx(text, m.start(), m.end()), severity="gul")

    # D: margin / rabatt
    for m in _MARGIN_RE.finditer(text):
        pct = m.group(2)
        kw  = m.group("kw").lower()
        cat = "rabatt" if any(x in kw for x in ("rabatt", "avslag", "discount")) else "margin / påslag"
        val = f"{pct}%"
        key = (cat, val)
        if key not in seen:
            seen.add(key)
            yield Finding(cat, val, _ctx(text, m.start(), m.end()), severity="gul")


def detect_financials(text: str) -> list[Finding]:
    return list(find_financial_data(text))
