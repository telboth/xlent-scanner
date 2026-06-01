"""Ekstra detektorer for sensitiv informasjon som ikke er dekket av de
   nasjonalspesifikke detektorene.

Kategorier:
  - IP-adresse (IPv4 og IPv6)       → gul   (kan avsløre intern infrastruktur)
  - SWIFT/BIC-kode                  → gul   (bankidentifikator)
  - Passnummer (norsk format)        → svart (biometrisk dokument-ID)
  - Dato med fødselsdato-kontekst   → gul   (personopplysning)
  - Kjøretøyregistrering (NO)       → gul   (kan knyttes til person)
  - Lønn/salary med beløp           → gul   (forretningssensitivt)
"""
from __future__ import annotations

import re
from typing import Iterator

from xlent_scanner.models import Finding
from xlent_scanner.utils import ctx as _ctx_base


def _ctx(text: str, start: int, end: int, radius: int = 55) -> str:
    return _ctx_base(text, start, end, radius)


# ── IPv4 ─────────────────────────────────────────────────────────────────────
# Krever at alle fire oktetter er 0-255; ingen løse desimalord matches.
_IPV4_RE = re.compile(
    r"(?<!\d)"
    r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
    r"(?!\d)"
)

# Oktett-sett som aldri er interessante alene (broadcast, loopback, test-net)
_IPV4_SKIP = {
    "0.0.0.0", "255.255.255.255", "127.0.0.1",
    "192.168.0.0", "192.168.255.255",
}


def find_ipv4(text: str) -> Iterator[Finding]:
    for m in _IPV4_RE.finditer(text):
        ip = m.group()
        if ip in _IPV4_SKIP:
            continue
        yield Finding("ip-adresse (IPv4)", ip, _ctx(text, m.start(), m.end()), severity="gul")


# ── IPv6 ─────────────────────────────────────────────────────────────────────
# Matcher komplett og forkortet IPv6. Krav: minst 3 kolon-separate grupper.
_IPV6_RE = re.compile(
    r"(?<![:\w])"
    r"("
    r"(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"             # full
    r"|(?:[0-9a-fA-F]{1,4}:){1,7}:"                           # ::suffix
    r"|::(?:[0-9a-fA-F]{1,4}:){0,5}[0-9a-fA-F]{1,4}"         # ::prefix
    r"|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}"          # mixed ::
    r"|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}" # shorter
    r")"
    r"(?![:\w])"
)


def find_ipv6(text: str) -> Iterator[Finding]:
    for m in _IPV6_RE.finditer(text):
        candidate = m.group(1)
        if candidate.count(":") < 3:
            continue
        yield Finding("ip-adresse (IPv6)", candidate, _ctx(text, m.start(), m.end()), severity="gul")


# ── SWIFT/BIC-kode ────────────────────────────────────────────────────────────
# Format: 4 bokstaver (bank) + 2 (land) + 2 (lokasjon) + valgfrie 3 (filial)
# Eksempler: DNBANOKK, HANDNL2A, SWEBSESS
_SWIFT_RE = re.compile(
    r"(?<![A-Z0-9])"
    r"([A-Z]{4}"          # bank-kode
    r"[A-Z]{2}"           # lands-kode (ISO 3166-1)
    r"[A-Z0-9]{2}"        # lokasjonskode
    r"(?:[A-Z0-9]{3})?)"  # valgfri filial-kode
    r"(?![A-Z0-9])"
)

# Kjente norske bank-prefikser for ekstra presisjon
_KNOWN_SWIFT_BANKS = {"DNBA", "HAND", "SWED", "SPSA", "KLBU", "NOBA", "SPAR"}

# Nøkkelord som indikerer bankkontekst
_SWIFT_CONTEXT_RE = re.compile(
    r"(?i)(?:swift|bic|bankidentifikator|bank\s*code|iban|wire\s*transfer|"
    r"overf[oø]ring|betalingsinfo|remittance)",
)


def find_swift(text: str) -> Iterator[Finding]:
    context_positions = {m.start() for m in _SWIFT_CONTEXT_RE.finditer(text)}

    for m in _SWIFT_RE.finditer(text):
        code = m.group(1)
        # Filtrer: krev nøkkelord-kontekst ELLER kjent norsk bankprefiks
        bank_prefix = code[:4]
        nearby_context = any(abs(m.start() - cp) < 200 for cp in context_positions)
        if not (nearby_context or bank_prefix in _KNOWN_SWIFT_BANKS):
            continue
        # Landkoden må være gyldig (ikke mer enn 2 tilfeldige bokstaver)
        country = code[4:6]
        if not country.isalpha():
            continue
        yield Finding("SWIFT/BIC-kode", code, _ctx(text, m.start(), m.end()), severity="gul")


# ── Passnummer (norsk format) ─────────────────────────────────────────────────
# Norske pass: 2 bokstaver + 7 siffer, f.eks. PA1234567, AB1234567
# Krev nøkkelord nær funnet for å unngå falske positiver
_PASSPORT_RE = re.compile(
    r"(?<![A-Z])"
    r"([A-Z]{2}[0-9]{7})"
    r"(?!\d)"
)

_PASSPORT_KW_RE = re.compile(
    r"(?i)(?:pass(?:port|nummer)?|reisedokument|travel\s*doc|passport\s*no)",
)


def find_passport(text: str) -> Iterator[Finding]:
    kw_positions = {m.start() for m in _PASSPORT_KW_RE.finditer(text)}
    for m in _PASSPORT_RE.finditer(text):
        nearby = any(abs(m.start() - kp) < 100 for kp in kw_positions)
        if not nearby:
            continue
        yield Finding(
            "passnummer",
            m.group(1),
            _ctx(text, m.start(), m.end()),
            severity="svart",
        )


# ── Norsk kjøretøyregistreringsnummer ────────────────────────────────────────
# Format: AB 12345 eller AB12345 (2 bokstaver + 5 siffer)
# Spesialtilganger: El-biler EK, EL, EV + vanlige prefikser
_REG_RE = re.compile(
    r"(?<![A-Z0-9])"
    r"([A-Z]{2}[\s]?[0-9]{5})"
    r"(?!\d)"
)

_REG_KW_RE = re.compile(
    r"(?i)(?:reg(?:istrerings)?\s*\.?\s*(?:nummer|nr\.?|skilt)|"
    r"bilskilt|kj[øo]ret[øo]y(?:ident)?|vehicle\s*reg|license\s*plate|numberplate)",
)


def find_vehicle_reg(text: str) -> Iterator[Finding]:
    kw_positions = {m.start() for m in _REG_KW_RE.finditer(text)}
    for m in _REG_RE.finditer(text):
        nearby = any(abs(m.start() - kp) < 80 for kp in kw_positions)
        if not nearby:
            continue
        yield Finding(
            "kjøretøyregistrering",
            m.group(1).replace(" ", ""),
            _ctx(text, m.start(), m.end()),
            severity="gul",
        )


# ── Lønn / salary ────────────────────────────────────────────────────────────
# Matcher «Årslønn: 850 000 kr», «salary: NOK 1 200 000», «lønn: 650000»
_CCY = r"(?:NOK|kr|SEK|EUR|USD|£|€|\$)"
_SALARY_KW_RE = re.compile(
    r"(?i)(?:"
    r"[åa]rsl[øo]nn|m[åa]nedsl[øo]nn|l[øo]nn(?:\s*per\s*(?:m[åa]ned|[åa]r))?"
    r"|salary|annual\s*pay|monthly\s*pay|gross\s*salary|net\s*salary"
    r"|kompensasjon|godtgj[oø]relse"
    r")"
    r"\s*:?\s*"
    + _CCY + r"?\s*"
    r"(\d{1,3}(?:[., \t]\d{3})*(?:[.,]\d{1,2})?)"
    r"(?:\s*" + _CCY + r")?",
    re.IGNORECASE,
)


def find_salary(text: str) -> Iterator[Finding]:
    seen: set[str] = set()
    for m in _SALARY_KW_RE.finditer(text):
        amount = m.group(1)
        if amount not in seen:
            seen.add(amount)
            yield Finding(
                "lønn",
                amount,
                _ctx(text, m.start(), m.end()),
                severity="gul",
            )


# ── Fødselsdato med kontekstnøkkelord ────────────────────────────────────────
_DOB_DATE_RE = re.compile(
    r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})",
)

_DOB_KW_RE = re.compile(
    r"(?i)(?:f[øo]dselsdato|f[øo]dt|date\s*of\s*birth|born\s*(?:on|:)|dob\s*:)",
)


def find_date_of_birth(text: str) -> Iterator[Finding]:
    """Fanger datoer som opptrer nær fødselsdato-nøkkelord.
    Unngår dobbelt-flagging av fødselsnumre (allerede svart)."""
    for kw_m in _DOB_KW_RE.finditer(text):
        # Søk etter dato innen 60 tegn etter nøkkelordet
        window = text[kw_m.end():kw_m.end() + 60]
        date_m = _DOB_DATE_RE.search(window)
        if date_m:
            d, mo, y = date_m.group(1), date_m.group(2), date_m.group(3)
            try:
                day = int(d); month = int(mo); year = int(y)
                if not (1 <= day <= 31 and 1 <= month <= 12):
                    continue
            except ValueError:
                continue
            abs_start = kw_m.start()
            yield Finding(
                "fødselsdato",
                date_m.group(0),
                _ctx(text, abs_start, kw_m.end() + date_m.end()),
                severity="gul",
            )


# ── Samlet ────────────────────────────────────────────────────────────────────

def detect_extra(text: str) -> list[Finding]:
    """Kjører alle ekstra detektorer."""
    findings: list[Finding] = []
    for fn in (find_ipv4, find_ipv6, find_swift,
               find_passport, find_vehicle_reg, find_salary, find_date_of_birth):
        findings.extend(fn(text))
    return findings
