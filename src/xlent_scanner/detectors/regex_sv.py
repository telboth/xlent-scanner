"""Svenska regex-detektorer med validering.

Kategorier:
  - personnummer      (10/12 siffror, Luhn mod-10, datumvalidering)
  - samordningsnummer (dag + 60, annars som personnummer)
  - organisationsnummer (10 siffror, siffra[2] >= 2, Luhn mod-10)
  - telefonnummer     (mobil 07X, fast 0X(X), +46 / 0046)
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx


# ── hjälpfunktioner ───────────────────────────────────────────────────────────


def _luhn10(digits: list[int]) -> bool:
    """Kontrollerar Luhn mod-10 for en liste med 10 heltall.

    Posisjon 0, 2, 4, 6, 8 multipliseres med 2;
    posisjon 1, 3, 5, 7, 9 multipliseres med 1.
    Produkter >= 10 reduseres med 9 (= siffer-sum for tosifrede tall).
    Gyldig dersom total % 10 == 0.
    """
    total = 0
    for i, d in enumerate(digits):
        v = d * 2 if i % 2 == 0 else d
        if v >= 10:
            v -= 9
        total += v
    return total % 10 == 0


# ── personnummer / samordningsnummer ──────────────────────────────────────────
#
# Format:  YYMMDD[-+]NNNN   (10 + separator)
#       eller  YYYYMMDD-NNNN   (12 + separator)
# Separator: '-' (standard), '+' (person > 100 år), ingen = sjeldnere
# Samordningsnummer: dag-delen er dag + 60 (dvs. dag 61-91)

_PERSNR_RAW = re.compile(
    r"(?<!\d)"
    r"(\d{8}|\d{6})"   # YYYYMMDD (8 siffer) eller YYMMDD (6 siffer)
    r"([-+]?)"          # valgfri separator
    r"(\d{4})"          # fodelsenummer (3) + kontrollsiffer (1)
    r"(?!\d)"
)


def _validate_persnr(date_str: str, sep: str, last4: str) -> str | None:
    """Returnerer 'personnummer (SV)', 'samordningsnummer (SV)' eller None."""
    if len(date_str) == 8:
        # 12-siffersformat YYYYMMDD: bruk de to siste år-sifrene for Luhn
        yy, mm, dd = date_str[2:4], date_str[4:6], date_str[6:8]
    else:
        # 10-siffersformat YYMMDD
        yy, mm, dd = date_str[0:2], date_str[2:4], date_str[4:6]

    month = int(mm)
    day   = int(dd)

    if not (1 <= month <= 12):
        return None

    is_samnr = 61 <= day <= 91
    real_day = day - 60 if is_samnr else day

    if not (1 <= real_day <= 31):
        return None

    ten_digits = [int(c) for c in (yy + mm + dd + last4)]
    if len(ten_digits) != 10 or not _luhn10(ten_digits):
        return None

    return "samordningsnummer (SV)" if is_samnr else "personnummer (SV)"


def find_persnr(text: str) -> Iterator[Finding]:
    for m in _PERSNR_RAW.finditer(text):
        kind = _validate_persnr(m.group(1), m.group(2), m.group(3))
        if kind:
            yield Finding(kind, m.group(0), _ctx(text, m.start(), m.end()))


# ── organisationsnummer ───────────────────────────────────────────────────────
#
# Format: XXXXXX-XXXX (10 siffror, separator valgfri)
# Nøkkelregel: siffra ved index 2 (0-basert) >= 2
#   → personnummer har alltid siffra[2] ∈ {0, 1}  (første siffer i måneden)
#   → org-nummer starter typisk med 5x / 6x / 7x / 8x
# I tillegg Luhn mod-10 gyldig.

_ORGNR_SV_RAW = re.compile(
    r"(?<!\d)"
    r"(\d{6})"   # 6 første sifre
    r"-?"         # valgfri bindestrek
    r"(\d{4})"   # 4 siste sifre (inkludert kontrollsiffer)
    r"(?!\d)"
)


def _validate_orgnr_sv(s: str) -> bool:
    """s = 10 sammenhengende sifre (ingen separator)."""
    if len(s) != 10 or not s.isdigit():
        return False
    if int(s[2]) < 2:   # skiller org-nummer fra personnummer
        return False
    return _luhn10([int(c) for c in s])


def find_orgnr_sv(text: str) -> Iterator[Finding]:
    for m in _ORGNR_SV_RAW.finditer(text):
        digits = m.group(1) + m.group(2)
        if _validate_orgnr_sv(digits):
            yield Finding(
                "organisasjonsnummer (SV)",
                m.group(0),
                _ctx(text, m.start(), m.end()),
            )


# ── telefonnummer ─────────────────────────────────────────────────────────────
#
# Vanlige svenske formater (10 sifre uten landkode):
#   Mobil:   07X-XXX XX XX  (area 070, 072, 073, 076, 079 mm.)
#   Fast 08: 08-XXX XX XX   (Stockholm, 2-siffer area + 7 sifre = 9? nei: 10 inkl. 0)
#            Egentlig: 08 (2) + 7 = 9 sifre... men med 0 foran = 10
#            08-12345678 = 10 sifre m/ 0, 9 u/ 0
#   Fast 3-siffer: 031-XX XX XX (Göteborg), 040-XX XX XX (Malmö) osv.
#   Internasjonalt: +46 XX XXX XX XX eller 0046 XX XXX XX XX

_SV_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:"
        # ── Internasjonalt: +46 / 0046 + 9 siffer (uten ledende 0)
        r"(?:\+46|0046)[\s\-]?[1-9]\d{1,2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
        r"|"
        # ── Mobil: 07X-XXX XX XX  (10 sifre totalt)
        r"07[0-9][\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
        r"|"
        # ── Fast 2-siffer area (08): 08-XXX XX XX  (10 sifre inkl. 0)
        r"08[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
        r"|"
        # ── Fast 3-siffer area (0XX): 031-XX XX XX  (10 sifre inkl. 0)
        r"0[1-9]\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}"
    r")"
    r"(?!\d)"
)


def find_telefon_sv(text: str) -> Iterator[Finding]:
    for m in _SV_PHONE_RE.finditer(text):
        yield Finding("telefonnummer (SV)", m.group(0).strip(), _ctx(text, m.start(), m.end()))


# ── bankgiro / plusgiro ───────────────────────────────────────────────────────
#
# Bankgiro:  NNN-NNNN  eller  NNNN-NNNN  (7-8 sifre), krever nøkkelord
# Plusgiro:  N-N  til  NNNNNNN-N,         krever nøkkelord
# Nøkkelord kreves for å unngå falske positiver fra telefon/datoer o.l.

_BANKGIRO_RE = re.compile(
    r"(?i)(?:bankgiro|b\.?g\.?)\s*(?:nr\.?)?\s*:?\s*"
    r"(\d{3,4}[\s\-]\d{4}|\d{7,8})"
)

_PLUSGIRO_RE = re.compile(
    r"(?i)(?:plusgiro|p\.?g\.?)\s*(?:nr\.?)?\s*:?\s*"
    r"(\d{1,7}[\s\-]\d|\d{2,8})"
)


def find_bankgiro(text: str) -> Iterator[Finding]:
    for m in _BANKGIRO_RE.finditer(text):
        val = m.group(1).strip()
        yield Finding(
            "bankgiro (SV)",
            val,
            _ctx(text, m.start(), m.end()),
            severity="svart",
        )


def find_plusgiro(text: str) -> Iterator[Finding]:
    for m in _PLUSGIRO_RE.finditer(text):
        val = m.group(1).strip()
        yield Finding(
            "plusgiro (SV)",
            val,
            _ctx(text, m.start(), m.end()),
            severity="svart",
        )


# ── samlet ────────────────────────────────────────────────────────────────────

def detect_sv_specific(text: str) -> list[Finding]:
    """Svenska mønstre: personnummer, samordningsnummer, org-nummer, telefon, bankgiro.

    E-post håndteres separat via find_emails() for alle språk.
    """
    findings: list[Finding] = []
    for fn in (find_persnr, find_orgnr_sv, find_telefon_sv, find_bankgiro, find_plusgiro):
        findings.extend(fn(text))
    return findings
