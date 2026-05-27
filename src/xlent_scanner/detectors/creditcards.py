"""Kredittkort-detektor med Luhn-validering og prefix-sjekk.

Støttede korttyper: Visa, Mastercard, American Express, Discover.
Krever BÅDE gyldig Luhn AND kjent kortprefix for å unngå falske positiver.

Severity: svart — betalingskort er kritisk sensitiv finansinfo.
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding


def _ctx(text: str, start: int, end: int, radius: int = 40) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi].replace("\n", " ")
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(text) else "")


# ── Luhn MOD-10 ───────────────────────────────────────────────────────────────

def _luhn(digits: list[int]) -> bool:
    """Standard Luhn MOD-10: dobler annenhver siffer FRA HØYRE."""
    total = 0
    parity = len(digits) % 2   # 0 for partall-lengde, 1 for oddetall
    for i, d in enumerate(digits):
        v = d * 2 if (i % 2 == parity) else d
        if v >= 10:
            v -= 9
        total += v
    return total % 10 == 0


# ── Korttype og prefix ────────────────────────────────────────────────────────

def _card_type(digits: str) -> str | None:
    """Returnerer korttype-streng eller None hvis prefix er ukjent."""
    n = len(digits)
    if n == 16:
        if digits[0] == "4":
            return "Visa"
        p2 = digits[:2]
        if p2 in ("51", "52", "53", "54", "55"):
            return "Mastercard"
        p4 = digits[:4]
        if "2221" <= p4 <= "2720":
            return "Mastercard"
        if p2 == "65" or p4 == "6011":
            return "Discover"
    elif n == 15:
        if digits[:2] in ("34", "37"):
            return "American Express"
    elif n == 13:
        if digits[0] == "4":
            return "Visa"
    return None   # ukjent prefix — hopp over for å unngå falske positiver


# ── Regex ─────────────────────────────────────────────────────────────────────
# Matcher 4×4 (Visa/MC), 4-6-5 (Amex), 4-4-5 (gammel Visa 13-siffer)
_CC_RE = re.compile(
    r"(?<!\d)"
    r"("
        r"\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"   # 4-4-4-4 (16 sifre)
        r"|\d{4}[\s\-]?\d{6}[\s\-]?\d{5}"               # 4-6-5   (15 sifre Amex)
        r"|\d{4}[\s\-]?\d{4}[\s\-]?\d{5}"               # 4-4-5   (13 sifre)
    r")"
    r"(?!\d)"
)


# ── Deteksjon ─────────────────────────────────────────────────────────────────

def find_creditcards(text: str) -> Iterator[Finding]:
    seen: set[str] = set()
    for m in _CC_RE.finditer(text):
        raw = m.group(1)
        digits = re.sub(r"[\s\-]", "", raw)
        if digits in seen:
            continue
        card_type = _card_type(digits)
        if not card_type:
            continue
        if not _luhn([int(c) for c in digits]):
            continue
        seen.add(digits)
        # Masker: BIN (4 sifre) + skjult midtdel + siste 4 (som på kvittering)
        masked = digits[:4] + " ****" * ((len(digits) - 8) // 4) + " " + digits[-4:]
        f = Finding(
            f"kredittkort ({card_type})",
            masked.strip(),
            _ctx(text, m.start(), m.end()),
            severity="svart",
        )
        f.raw_text = digits
        yield f


def detect_creditcards(text: str) -> list[Finding]:
    return list(find_creditcards(text))
