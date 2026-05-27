"""Risk engine: beregner alvorlighetsgrad per funn og samlet vurdering."""
from __future__ import annotations

from xlent_scanner.models import Finding, ScanResult

# Alvorlighetsgrad per kategori-prefiks (case-insensitive startswith-match)
_SEVERITY_MAP: list[tuple[str, str]] = [
    # ── SVART ──────────────────────────────────────────────────────────────
    ("fødselsnummer",               "svart"),
    ("d-nummer",                    "svart"),
    ("personnummer",                "svart"),   # norsk/svensk term (SV-detektor)
    ("samordningsnummer",           "svart"),
    ("kontonummer",                 "svart"),
    ("bankgiro",                    "svart"),
    ("plusgiro",                    "svart"),
    ("kredittkort",                 "svart"),
    ("uk national insurance",       "svart"),
    ("us social security",          "svart"),
    ("private key",                 "svart"),
    ("aws access key",              "svart"),

    # ── RØD ────────────────────────────────────────────────────────────────
    ("iban",                        "rød"),
    ("openai api key",              "rød"),
    ("anthropic api key",           "rød"),
    ("github token",                "rød"),
    ("azure storage key",           "rød"),
    ("jwt token",                   "rød"),
    ("bearer token",                "rød"),
    ("passord i konfig",            "rød"),
    ("konfidensielt dokument (overskrift)", "rød"),

    # ── GUL ────────────────────────────────────────────────────────────────
    ("e-post",                      "gul"),
    ("telefonnummer",               "gul"),
    ("organisasjonsnummer",         "gul"),
    ("navn (person)",               "gul"),
    ("kundenavn",                   "gul"),
    ("konfidensielt dokument",      "gul"),   # fanger brødtekst-varianten
    ("konfigurasjonsord",           "gul"),
    ("høy-entropisteng",            "gul"),
    ("⚠ ner ikke tilgjengelig",     "gul"),
    ("⚠ detektor-feil",             "gul"),
    ("timepris",                    "gul"),
    ("dagspris",                    "gul"),
    ("prosjektsum",                 "gul"),
    ("margin",                      "gul"),
    ("rabatt",                      "gul"),
]

_LEVEL_ORDER = {"grønn": 0, "gul": 1, "rød": 2, "svart": 3}

_ACTIONS: dict[str, str] = {
    "grønn": (
        "Ingen sensitive funn oppdaget. Dokumentet ser trygt ut å laste opp "
        "til det valgte AI-verktøyet."
    ),
    "gul": (
        "Dokumentet inneholder informasjon som bør vurderes før deling. "
        "Vurder å anonymisere eller fjerne de merkede feltene, eller bruk "
        "et AI-verktøy med sterk datahåndteringspolicy."
    ),
    "rød": (
        "Dokumentet inneholder sensitiv informasjon (API-nøkler, secrets "
        "eller konfidensielle markører). IKKE last opp til online AI-verktøy "
        "uten å fjerne de markerte seksjonene."
    ),
    "svart": (
        "Dokumentet inneholder kritisk sensitiv informasjon (personnummer, "
        "kontonummer og/eller private kryptografiske nøkler). "
        "IKKE del dette dokumentet. Anonymiser eller bruk kun godkjente, "
        "lokale verktøy."
    ),
}

_SUMMARIES: dict[str, str] = {
    "grønn": "Ingen sensitive funn",
    "gul":   "Funn som bør vurderes",
    "rød":   "Sensitive funn — ikke del uten redigering",
    "svart": "Kritisk sensitiv informasjon — ikke del",
}


def _category_severity(category: str) -> str:
    cat = category.lower()
    for prefix, level in _SEVERITY_MAP:
        if cat.startswith(prefix):
            return level
    return "gul"   # ukjent kategori: konservativt gul


def assess(result: ScanResult) -> ScanResult:
    """Beriker ScanResult med risk_level, risk_summary og recommended_action."""
    overall = "grønn"
    for f in result.findings:
        sev = _category_severity(f.category)
        f.severity = sev
        if _LEVEL_ORDER[sev] > _LEVEL_ORDER[overall]:
            overall = sev

    result.risk_level = overall
    result.risk_summary = _SUMMARIES[overall]
    result.recommended_action = _ACTIONS[overall]
    return result
