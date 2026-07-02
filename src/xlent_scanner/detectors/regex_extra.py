"""Ekstra detektorer for sensitiv informasjon som ikke er dekket av de
   nasjonalspesifikke detektorene.

Kategorier:
  - IP-adresse (IPv4 og IPv6)       → gul   (kan avsløre intern infrastruktur)
  - SWIFT/BIC-kode                  → gul   (bankidentifikator)
  - Passnummer (norsk format)        → svart (biometrisk dokument-ID)
  - Dato med fødselsdato-kontekst   → gul   (personopplysning)
  - Kjøretøyregistrering (NO)       → gul   (kan knyttes til person)
  - Lønn/salary med beløp           → gul   (forretningssensitivt)
  - HR-/personalsaksverdier          → rød/gul (lønn, sykefravær, oppsigelse m.m.)
  - Juridiske/strafferettslige felt  → rød
  - Barn-/elevopplysninger           → rød
  - Lokasjon/device-ID               → gul/rød (GPS, MAC, IMEI)
  - Bank routing/sort code           → svart
  - Medisinske felt uten AI          → rød
  - Telefon/fax etter eksplisitt label → gul
  - PO Box-adresse                  → gul
  - Konfidensielle rene label-linjer → rød
  - Dokumentmetadata-felt            → gul
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

# BIC bruker ISO 3166-1 alpha-2 i posisjon 5–6. Uten denne valideringen kan
# vanlige store ord som HORTENXX mistolkes som bankkode ("EN" er ikke landkode).
_SWIFT_COUNTRY_CODES = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
    BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
    CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
    DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
    GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
    HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP
    KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY
    MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
    NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR
    PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN
    SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW
    TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
    """.split()
)

# Nøkkelord som indikerer bankkontekst
_SWIFT_CONTEXT_RE = re.compile(
    r"(?i)(?:swift|bic|bankidentifikator|bank\s*code|iban|wire\s*transfer|"
    r"bankoverf[oø]ring|internasjonal\s+overf[oø]ring|betalingsinfo|remittance)",
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
        # Landkoden må være en faktisk ISO 3166-1 alpha-2-kode.
        country = code[4:6]
        if country not in _SWIFT_COUNTRY_CODES:
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


# ── Tax ID / Tax Identification Number ──────────────────────────────────────
# Generisk internasjonal regel: krev eksplisitt label, og masker verdien etter
# labelen. Kategorien går under Personnummer / ID i scan_categories.py.
_TAX_ID_RE = re.compile(
    r"(?i)\b(?:"
    r"tax\s*(?:id|identification\s*number|number|no\.?)"
    r"|tin"
    r"|ssn|social\s*security\s*(?:number|no\.?)"
    r"|national\s*insurance\s*(?:number|no\.?)|nino"
    r"|passport\s*(?:no\.?|number)"
    r"|driver'?s?\s*licen[cs]e(?:\s*(?:no\.?|number))?"
    r"|id\s*(?:no\.?|number)"
    r"|personal\s*id"
    r"|resident\s*id"
    r"|vat\s*(?:id|number|no\.?)"
    r")\b\s*[:#.]?\s*"
    r"([A-Z]{0,3}[\s-]*\d[A-Z0-9][A-Z0-9\s./-]{3,28}[A-Z0-9])"
)


def find_tax_id(text: str) -> Iterator[Finding]:
    seen: set[str] = set()
    for m in _TAX_ID_RE.finditer(text):
        raw_value = re.split(r"[.;,]\s+[A-ZÆØÅÄÖÜ]", m.group(1), maxsplit=1)[0]
        value = " ".join(raw_value.strip(" \t\r\n,;:.").split())
        compact = re.sub(r"\s+", "", value).upper()
        digits = re.sub(r"\D", "", value)
        if compact in seen:
            continue
        if not (6 <= len(digits) <= 20):
            continue
        seen.add(compact)
        yield Finding(
            "tax identification number",
            value,
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


# ── HR-/personalsak ─────────────────────────────────────────────────────────
# Krever eksplisitt HR-ledetekst. Beløp går som "lønn"; øvrige HR-verdier
# flagges som personalsak for å dekke oppsigelse, fravær, varsel m.m.
_HR_AMOUNT_RE = re.compile(
    r"(?i)\b(?:salary|annual\s*salary|monthly\s*salary|bonus|compensation|severance|sluttpakke|etterl[øo]nn|"
    r"overtime\s*pay|variable\s*pay)\b\s*[:#-]?\s*"
    + _CCY + r"?\s*"
    r"(\d{1,3}(?:[., \t]\d{3})*(?:[.,]\d{1,2})?)(?:\s*" + _CCY + r")?",
)

_HR_FIELD_RE = re.compile(
    r"(?i)\b(?:"
    r"sick\s*leave|absence\s*rate|sykefrav[æa]r|frav[æa]rsprosent|"
    r"termination|notice\s*period|oppsigelse|oppsigelsestid|"
    r"disciplinary\s*warning|written\s*warning|advarsel|"
    r"performance\s*review|medarbeidersamtale|employee\s*review"
    r")\b\s*[:#-]?\s*([^.\n\r;]{2,80})",
)


def find_hr_personnel_data(text: str) -> Iterator[Finding]:
    for m in _HR_AMOUNT_RE.finditer(text):
        amount = m.group(1).strip()
        yield Finding("lønn", amount, _ctx(text, m.start(), m.end()), severity="gul")

    for m in _HR_FIELD_RE.finditer(text):
        value = m.group(1).strip(" \t\r\n,;:.")
        if not value:
            continue
        yield Finding("personalsak", value, _ctx(text, m.start(), m.end()), severity="rød")


# ── Juridiske/strafferettslige felt ─────────────────────────────────────────
_LEGAL_FIELD_RE = re.compile(
    r"(?i)\b(?:"
    r"criminal\s*case|court\s*case|police\s*report|disciplinary\s*case|"
    r"whistleblowing\s*case|investigation|charged\s*with|convicted\s*of|"
    r"case\s*(?:no\.?|number)|matter\s*(?:no\.?|number)|incident\s*(?:no\.?|number)|"
    r"saksnummer|sak\s*nr\.?|straffesak|politisak|domfelt|siktet|tiltalt|gransking|varslingssak"
    r")\b\s*[:#-]?\s*([A-ZÆØÅÄÖÜ0-9][A-ZÆØÅÄÖÜa-zæøåäöü0-9 _/-]{2,80})",
)


def find_legal_case_data(text: str) -> Iterator[Finding]:
    for m in _LEGAL_FIELD_RE.finditer(text):
        value = m.group(1).strip(" \t\r\n,;:.")
        if not value:
            continue
        yield Finding("juridisk forhold", value, _ctx(text, m.start(), m.end()), severity="rød")


# ── Barn/skole/elev ─────────────────────────────────────────────────────────
_CHILD_SCHOOL_RE = re.compile(
    r"(?i)\b(?:"
    r"student|pupil|child|guardian|parent|school|class|iep|special\s*education|"
    r"elev|foresatt|klasse|skole|barnehage|barnevern|ppt|iop|spesialundervisning"
    r")\b\s*[:#-]?\s*("
    r"[A-ZÆØÅÄÖÜ][A-Za-zÆØÅæøåÄÖäöÜüÉéÈèÁáÀàÓóÒòÍíÌìÑñß '-]{2,50}"
    r"|\d{1,2}[A-ZÆØÅ]?"
    r")",
)


def find_child_school_data(text: str) -> Iterator[Finding]:
    for m in _CHILD_SCHOOL_RE.finditer(text):
        value = m.group(1).strip(" \t\r\n,;:.")
        if not value:
            continue
        yield Finding("barn/elevopplysning", value, _ctx(text, m.start(), m.end()), severity="rød")


# ── Lokasjon og device-identifikatorer ──────────────────────────────────────
_GPS_RE = re.compile(
    r"(?i)\b(?:gps|coordinates?|koordinater|location|lokasjon)\s*[:#-]?\s*"
    r"([-+]?(?:[1-8]?\d(?:\.\d+)?|90(?:\.0+)?))\s*,\s*"
    r"([-+]?(?:1[0-7]\d(?:\.\d+)?|[1-9]?\d(?:\.\d+)?|180(?:\.0+)?))\b"
)

_MAC_RE = re.compile(
    r"(?i)\b(?:mac(?:\s*address)?|device\s*mac)\s*[:#-]?\s*"
    r"((?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2})\b"
)

_IMEI_RE = re.compile(r"(?i)\b(?:imei|device\s*id)\s*[:#-]?\s*(\d{15})\b")


def find_location_device_ids(text: str) -> Iterator[Finding]:
    for m in _GPS_RE.finditer(text):
        value = f"{m.group(1)}, {m.group(2)}"
        yield Finding("lokasjonsdata", value, _ctx(text, m.start(), m.end()), severity="gul")
    for m in _MAC_RE.finditer(text):
        yield Finding("mac-adresse", m.group(1), _ctx(text, m.start(), m.end()), severity="gul")
    for m in _IMEI_RE.finditer(text):
        yield Finding("imei", m.group(1), _ctx(text, m.start(), m.end()), severity="rød")


# ── Bank routing / sort code / account label ────────────────────────────────
_BANK_ROUTING_RE = re.compile(
    r"(?i)\b(?:routing\s*number|sort\s*code|aba|ach|"
    r"beneficiary\s*account|account\s*(?:no\.?|number))\b\s*[:#-]?\s*"
    r"([0-9][0-9 -]{5,25}[0-9])"
)


def find_bank_routing_details(text: str) -> Iterator[Finding]:
    for m in _BANK_ROUTING_RE.finditer(text):
        value = " ".join(m.group(1).strip(" \t\r\n,;:.").split())
        digits = re.sub(r"\D", "", value)
        if not (6 <= len(digits) <= 24):
            continue
        yield Finding("kontonummer", value, _ctx(text, m.start(), m.end()), severity="svart")


# ── Medisinske felt uten AI ─────────────────────────────────────────────────
_MEDICAL_FIELD_RE = re.compile(
    r"(?i)\b(?:"
    r"diagnosis|diagnose|medication|medicine|prescription|"
    r"patient\s*id|journal\s*(?:no\.?|number)|medical\s*record\s*number|mrn|"
    r"legemiddel|medisin|resept|pasient\s*id|journal\s*nr\.?"
    r")\b\s*[:#-]?\s*([^,.\n\r;]{2,80})"
)


def find_medical_fields(text: str) -> Iterator[Finding]:
    for m in _MEDICAL_FIELD_RE.finditer(text):
        value = m.group(1).strip(" \t\r\n,;:.")
        if not value:
            continue
        yield Finding("medisinsk opplysning", value, _ctx(text, m.start(), m.end()), severity="rød")


# ── Konfidensiell ren label-linje ───────────────────────────────────────────
_CONFIDENTIAL_LABEL_LINE_RE = re.compile(
    r"(?im)^\s*(confidential|strictly\s+confidential|internal\s+only|"
    r"restricted|secret|classified|konfidensielt|fortrolig|internt)\s*[:\-]?\s*$"
)


def find_confidential_label_lines(text: str) -> Iterator[Finding]:
    for m in _CONFIDENTIAL_LABEL_LINE_RE.finditer(text):
        yield Finding(
            "konfidensielt dokument (overskrift)",
            m.group(1),
            _ctx(text, m.start(1), m.end(1)),
            severity="rød",
        )


# ── Dokumentmetadata-felt i tekstuttrekk/eksport ────────────────────────────
_METADATA_FIELD_RE = re.compile(
    r"(?im)^\s*(?:author|creator|producer|company|manager|"
    r"last\s*modified\s*by|modified\s*by|forfatter|opprettet\s*av|firma)\s*[:=]\s*"
    r"([^\n\r;]{2,80})\s*$"
)


def find_document_metadata_fields(text: str) -> Iterator[Finding]:
    for m in _METADATA_FIELD_RE.finditer(text):
        value = m.group(1).strip(" \t\r\n,;:.")
        if not value or value.lower() in {"unknown", "none", "n/a"}:
            continue
        yield Finding("dokumentmetadata", value, _ctx(text, m.start(), m.end()), severity="gul")


# ── Telefon/fax etter eksplisitt label ───────────────────────────────────────
# Fanger lokale/internasjonale numre som ikke passer nasjonale regexer, men bare
# når de står rett etter en tydelig label. Dette dekker f.eks. "Tel: 04-7041111"
# uten å åpne for generelle 7-sifrede tall.
_LABELED_PHONE_RE = re.compile(
    r"(?i)\b(?:tel(?:ephone)?|phone|mobile|mob\.?|fax)\s*[:.]?\s*"
    r"(\+?\d[\d\s().-]{5,20}\d)"
)


def find_labeled_phone_or_fax(text: str) -> Iterator[Finding]:
    seen: set[tuple[int, int]] = set()
    for m in _LABELED_PHONE_RE.finditer(text):
        raw = m.group(1).strip()
        number = raw.strip(" .;:,)")
        digits = re.sub(r"\D", "", number)
        if not (7 <= len(digits) <= 15):
            continue
        # Krev minst to siffer etter siste skilletegn for å unngå avkuttede treff.
        if re.search(r"[\s().-]$", number):
            continue
        span = (m.start(1), m.start(1) + len(number))
        if span in seen:
            continue
        seen.add(span)
        yield Finding(
            "telefonnummer",
            number,
            _ctx(text, m.start(), m.end()),
            severity="gul",
        )


# ── PO Box-adresse ───────────────────────────────────────────────────────────
# Fanger postboksadresser med eksplisitt label. Vi tar med kort sted/land-hale
# når den står direkte etter nummeret, slik at "PO Box 27758 * Dubai - United
# Arab Emirates" blir ett redigerbart adressefunn.
_PO_BOX_ADDRESS_RE = re.compile(
    r"(?i)\b(?:p\.?\s*o\.?\s*box|po\s*box|post\s*box|postboks)"
    r"\s*(?:no\.?|nr\.?|#)?\s*[:.]?\s*"
    r"\d{2,10}"
    r"(?:\s*[,;*°•·-]\s*"
    r"[A-ZÆØÅÄÖÜ][A-Za-zÆØÅæøåÄÖäöÜüÉéÈèÁáÀàÓóÒòÍíÌìÑñß .'-]{1,55}"
    r"){0,3}"
)


def find_po_box_address(text: str) -> Iterator[Finding]:
    for m in _PO_BOX_ADDRESS_RE.finditer(text):
        value = m.group(0).strip(" \t\r\n,;")
        yield Finding(
            "fysisk adresse",
            value,
            _ctx(text, m.start(), m.end()),
            severity="gul",
        )


# ── Gateadresse ──────────────────────────────────────────────────────────────
# Presis flerspråklig regel med minst to signaler:
#   1) eksplisitt gate-/vei-/street-/rue-/calle-ord
#   2) husnummer
# Støtter både "Baker Street 221B" og "10 Downing Street".
_ADDRESS_WORD = (
    r"(?i:(?:"
    r"gate|gata|gaten|vei|veien|vegen|plass|brygge|alle|allé|"
    r"street|st\.?|road|rd\.?|avenue|ave\.?|drive|lane|way|boulevard|blvd\.?|"
    r"straße|strasse|weg|platz|allee|"
    r"rue|avenue|chemin|boulevard|"
    r"calle|avenida|paseo|plaza|"
    r"via|viale|piazza"
    r"))"
)
_CAP_WORD = r"[A-ZÆØÅÄÖÜÉÈÁÀÓÒÍÌÑ][A-Za-zÆØÅæøåÄÖäöÜüÉéÈèÁáÀàÓóÒòÍíÌìÑñß.'-]{1,}"
_HOUSE_NO = r"\d{1,5}[A-Za-z]?(?:[-/]\d{1,4}[A-Za-z]?)?"
_POSTAL_TAIL = (
    r"(?:\s*[,;]\s*"
    r"(?:[A-Z]{1,3}[-\s]?)?\d{4,6}\s+"
    r"[A-ZÆØÅÄÖÜÉÈÁÀÓÒÍÌÑ][A-Za-zÆØÅæøåÄÖäöÜüÉéÈèÁáÀàÓóÒòÍíÌìÑñß .'-]{1,40}"
    r")?"
)

_STREET_NAME_BEFORE_NUMBER_RE = re.compile(
    rf"(?<![\w@])"
    rf"({_CAP_WORD}(?:\s+(?:de|del|der|den|la|le|du|of|the|{_CAP_WORD})){{0,5}}\s+{_ADDRESS_WORD}\s+{_HOUSE_NO}{_POSTAL_TAIL})"
    rf"(?![\w@])",
)

_STREET_NUMBER_BEFORE_NAME_RE = re.compile(
    rf"(?<![\w@])"
    rf"({_HOUSE_NO}\s+{_CAP_WORD}(?:\s+(?:de|del|der|den|la|le|du|of|the|{_CAP_WORD})){{0,5}}\s+{_ADDRESS_WORD}{_POSTAL_TAIL})"
    rf"(?![\w@])",
)

_COMPOUND_STREET_BEFORE_NUMBER_RE = re.compile(
    rf"(?<![\w@])"
    rf"({_CAP_WORD}(?:{_ADDRESS_WORD})\s+{_HOUSE_NO}{_POSTAL_TAIL})"
    rf"(?![\w@])",
)

_STREET_WORD_BEFORE_NAME_RE = re.compile(
    rf"(?<![\w@])"
    rf"({_ADDRESS_WORD}\s+(?:(?:de|del|der|den|la|le|du|of|the)\s+)?{_CAP_WORD}(?:\s+{_CAP_WORD}){{0,4}}\s+{_HOUSE_NO}{_POSTAL_TAIL})"
    rf"(?![\w@])",
)

_SUITE_ADDRESS_RE = re.compile(
    rf"(?<![\w@])"
    rf"({_HOUSE_NO}\s+{_CAP_WORD}(?:\s+{_CAP_WORD}){{0,5}}\s+(?i:suite|ste\.?|unit|apt\.?|apartment)\s+{_HOUSE_NO}{_POSTAL_TAIL})"
    rf"(?![\w@])",
)


def find_street_address(text: str) -> Iterator[Finding]:
    seen: set[tuple[int, int]] = set()
    matches: list[tuple[int, Finding]] = []
    for pattern in (
        _STREET_NAME_BEFORE_NUMBER_RE,
        _STREET_NUMBER_BEFORE_NAME_RE,
        _COMPOUND_STREET_BEFORE_NUMBER_RE,
        _STREET_WORD_BEFORE_NAME_RE,
        _SUITE_ADDRESS_RE,
    ):
        for m in pattern.finditer(text):
            span = m.span(1)
            if any(start <= span[0] < end or start < span[1] <= end for start, end in seen):
                continue
            value = m.group(1).strip(" \t\r\n,;.")
            seen.add(span)
            matches.append(
                (
                    span[0],
                    Finding(
                        "fysisk adresse",
                        value,
                        _ctx(text, m.start(1), m.end(1)),
                        severity="gul",
                    ),
                )
            )
    for _start, finding in sorted(matches, key=lambda item: item[0]):
        yield finding


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
            day_text, month_text = date_m.group(1), date_m.group(2)
            try:
                day = int(day_text)
                month = int(month_text)
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
               find_passport, find_tax_id, find_vehicle_reg, find_salary,
               find_hr_personnel_data, find_legal_case_data,
               find_child_school_data, find_location_device_ids,
               find_bank_routing_details, find_medical_fields,
               find_confidential_label_lines, find_document_metadata_fields,
               find_labeled_phone_or_fax, find_po_box_address,
               find_street_address, find_date_of_birth):
        findings.extend(fn(text))
    return findings
