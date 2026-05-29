"""Norske regex-detektorer med validering.

Kategorier:
  - e-post
  - fødselsnummer  (11 siffer, mod-11, datovalidering)
  - d-nummer       (som fnr men første siffer + 4)
  - organisasjonsnummer (9 siffer, starts 8/9, mod-11)
  - kontonummer    (11 siffer, mod-11)
  - telefon        (norsk, 8 siffer, med/uten +47/0047)
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx


# ── helpers ──────────────────────────────────────────────────────────────────


def _mod11(digits: list[int], weights: list[int]) -> int:
    """Returnerer mod-11 kontrollsiffer. Returnerer -1 hvis ugyldig (rest=10)."""
    remainder = sum(d * w for d, w in zip(digits, weights)) % 11
    if remainder == 0:
        return 0
    ctrl = 11 - remainder
    return -1 if ctrl == 10 else ctrl


# ── e-post ───────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"(?<![.\w])"           # ikke del av lengre ord
    r"[\w.+\-]{1,64}"
    r"@"
    r"[\w\-]{1,63}"
    r"(?:\.[\w\-]{1,63})+"
    r"(?![@\w])",           # tillater etterfølgende . (setningsavslutning)
    re.IGNORECASE,
)


def find_emails(text: str) -> Iterator[Finding]:
    for m in _EMAIL_RE.finditer(text):
        yield Finding("e-post", m.group(0), _ctx(text, m.start(), m.end()))


# ── fødselsnummer og D-nummer ─────────────────────────────────────────────────

_FNR_RAW = re.compile(
    r"\b(\d{11})\b"           # 11 siffer uten mellomrom: 21057234161
    r"|\b(\d{6})[ ](\d{5})\b"  # 6+space+5: 210572 34161
)

_K1_WEIGHTS = [3, 7, 6, 1, 8, 9, 4, 5, 2]
_K2_WEIGHTS = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def _validate_fnr_or_dnr(s: str) -> str | None:
    """Returnerer 'fødselsnummer', 'd-nummer' eller None."""
    if len(s) != 11 or not s.isdigit():
        return None
    d = [int(c) for c in s]

    day = d[0] * 10 + d[1]
    month = d[2] * 10 + d[3]
    is_dnr = 40 < day <= 71
    if is_dnr:
        day -= 40

    if not (1 <= day <= 31) or not (1 <= month <= 12):
        return None

    k1 = _mod11(d[:9], _K1_WEIGHTS)
    if k1 == -1 or k1 != d[9]:
        return None
    k2 = _mod11(d[:10], _K2_WEIGHTS)
    if k2 == -1 or k2 != d[10]:
        return None

    return "d-nummer" if is_dnr else "fødselsnummer"


def _looks_like_fnr_date(s: str) -> bool:
    """Kontrollerer om de første 6 sifrene ser ut som en gyldig norsk fødselsdato
    (inkl. D-nummer), men uten å kreve gyldig mod-11-kontrollsiffer.

    Brukes som fallback-detektor for tall som «ser ut som» personnummer
    selv om kontrollsifrene er feil (f.eks. testdata, feilskrevne numre).
    """
    if len(s) != 11 or not s.isdigit():
        return False
    d = [int(c) for c in s]
    day   = d[0] * 10 + d[1]
    month = d[2] * 10 + d[3]
    if 40 < day <= 71:          # D-nummer: trekk fra 40 for datokontroll
        day -= 40
    return (1 <= day <= 31) and (1 <= month <= 12)


def find_fnr(text: str) -> Iterator[Finding]:
    """Finner fødselsnumre og D-numre.

    To nivåer:
      1. Gyldig mod-11 → kategori «fødselsnummer»/«d-nummer» (svart)
      2. Ugyldig checksum men gyldig datoformat → «mulig personnummer (format)» (gul)
         Fanger f.eks. testdata eller feilskrevne numre som «210572 12345».
    """
    for m in _FNR_RAW.finditer(text):
        if m.group(1):
            raw     = m.group(1)
            display = m.group(1)
        else:
            raw     = m.group(2) + m.group(3)   # 6+5 uten mellomrom
            display = m.group(0).strip()          # vis med mellomrom
        kind = _validate_fnr_or_dnr(raw)
        if kind:
            yield Finding(kind, display, _ctx(text, m.start(), m.end()))
        elif _looks_like_fnr_date(raw):
            # Format-match men ugyldig sjekksiffer: lavere alvorlighetsgrad
            yield Finding(
                "mulig personnummer (format)",
                display,
                _ctx(text, m.start(), m.end()),
            )


# ── organisasjonsnummer ───────────────────────────────────────────────────────

_ORGNR_RAW = re.compile(
    r"\b([89]\d{2})\s?(\d{3})\s?(\d{3})\b"
)
_ORGNR_WEIGHTS = [3, 2, 7, 6, 5, 4, 3, 2]


def _validate_orgnr(s: str) -> bool:
    if len(s) != 9 or not s.isdigit():
        return False
    d = [int(c) for c in s]
    k = _mod11(d[:8], _ORGNR_WEIGHTS)
    return k != -1 and k == d[8]


def find_orgnr(text: str) -> Iterator[Finding]:
    for m in _ORGNR_RAW.finditer(text):
        digits = m.group(1) + m.group(2) + m.group(3)
        if _validate_orgnr(digits):
            yield Finding(
                "organisasjonsnummer",
                m.group(0).strip(),
                _ctx(text, m.start(), m.end()),
            )


# ── kontonummer ───────────────────────────────────────────────────────────────

_KONTO_RAW = re.compile(
    # 4-2-5 med punkt eller mellomrom: 1234.56.78901 / 1234 56 78901
    r"\b(\d{4})[.\s](\d{2})[.\s](\d{5})\b"
    # 4-4-3 med punkt eller mellomrom: 1730.1777.922 / 1234 5678 910
    r"|\b(\d{4})[. ](\d{4})[. ](\d{3})\b"
    # 11 siffer uten skilletegn: 17301777922
    r"|\b(\d{11})\b"
)
_KONTO_WEIGHTS = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def _validate_konto(s: str) -> bool:
    if len(s) != 11 or not s.isdigit():
        return False
    d = [int(c) for c in s]
    k = _mod11(d[:10], _KONTO_WEIGHTS)
    return k != -1 and k == d[10]


def find_kontonummer(text: str) -> Iterator[Finding]:
    for m in _KONTO_RAW.finditer(text):
        if m.group(1) is not None:
            digits = m.group(1) + m.group(2) + m.group(3)   # 4-2-5
        elif m.group(4) is not None:
            digits = m.group(4) + m.group(5) + m.group(6)   # 4-4-3
        else:
            digits = m.group(7)                               # rå 11 siffer
        if not _validate_konto(digits):
            continue
        # Hopp over tall som OGSÅ validerer som fødselsnummer/D-nummer —
        # kontrollsiffer-vektene overlapper, og fnr-validering er strengere
        # (K1 + K2 + datovalidering). Fnr-detektoren har prioritet.
        if _validate_fnr_or_dnr(digits):
            continue
        yield Finding(
            "kontonummer",
            m.group(0).strip(),
            _ctx(text, m.start(), m.end()),
        )


# ── telefonnummer ─────────────────────────────────────────────────────────────

_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:"
        # Med eksplisitt landkode (+47 / 0047): alle 8-sifret varianter aksepteres
        r"(?:\+47|0047)[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{3}"               # 3+2+3: +47 912 34 567
        r"|(?:\+47|0047)[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}"  # 2+2+2+2: +47 91 23 45 67
        r"|(?:\+47|0047)[\s\-]?\d{8}"                                         # 8 samlet: 0047 12345678
        # Uten landkode: kun kjente norske prefixer
        r"|[49]\d{2}[\s\-]?\d{2}[\s\-]?\d{3}"            # mobil 3+2+3: 912 34 567
        r"|[49]\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}"   # mobil 2+2+2+2: 91 23 45 67
        r"|[49]\d{7}"                                     # mobil 8 samlet
        r"|[2357]\d[\s\-]?\d{2}[\s\-]?\d{2}[\s\-]?\d{2}"  # fast 2+2+2+2: 22 34 56 78
        r"|[2357]\d{7}"                                   # fast 8 samlet
    r")"
    r"(?!\d)",
)


def find_telefon(text: str) -> Iterator[Finding]:
    for m in _PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        # Fjern landkode for visning av råverdi
        yield Finding("telefonnummer", raw, _ctx(text, m.start(), m.end()))


# ── samlet ────────────────────────────────────────────────────────────────────

def detect_no_specific(text: str) -> list[Finding]:
    """Norske mønstre uten e-post (e-post dekkes av find_emails for alle språk)."""
    findings: list[Finding] = []
    for fn in (find_fnr, find_orgnr, find_kontonummer, find_telefon):
        findings.extend(fn(text))
    return findings


def detect_all(text: str) -> list[Finding]:
    """Alle norske mønstre inkludert e-post. Brukes kun ved direkte kall."""
    findings: list[Finding] = []
    for fn in (find_emails, find_fnr, find_orgnr, find_kontonummer, find_telefon):
        findings.extend(fn(text))
    return findings
