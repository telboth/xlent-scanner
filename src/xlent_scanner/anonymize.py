"""Anonymisering: erstatter valgte funn i tekst med nøytrale plassholdere.

Konsistent anonymisering:
  - Personnavn       → <Person A>, <Person B>, … (samme navn → samme label)
  - Kundenavn        → <Selskap A>, <Selskap B>, …
  - Bankkontonummer  → <Konto 1>, <Konto 2>, …
  - E-post           → <Epost 1>, <Epost 2>, …
  - Telefonnummer    → <Tlf 1>, <Tlf 2>, …
  - Andre kategorier → fast plassholder (se _FIXED_PLACEHOLDER)
"""
from __future__ import annotations

from xlent_scanner.models import Finding

_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Kategorier med konsistent, alfabetisk merking
_ALPHA_CATEGORIES: dict[str, str] = {
    "navn (person)": "Person",
    "kundenavn":     "Selskap",
}

# Kategorier med konsistent, numerisk merking
_NUM_CATEGORIES: dict[str, str] = {
    "kontonummer":   "Konto",
    "bankgiro":      "Konto",
    "e-post":        "Epost",
    "telefonnummer": "Tlf",
    "fødselsnummer": "FNR",
    "d-nummer":      "DNR",
    "cpr-nummer":    "CPR",
    "personnummer":  "PNR",
    "organisasjonsnummer": "OrgNr",
    "iban":          "IBAN",
}

# Fast plassholder for alt annet
_FIXED_PLACEHOLDER: list[tuple[str, str]] = [
    ("kredittkort",           "<kredittkort>"),
    ("aws access key",        "<api-nøkkel>"),
    ("openai api key",        "<api-nøkkel>"),
    ("anthropic api key",     "<api-nøkkel>"),
    ("github token",          "<api-nøkkel>"),
    ("azure storage key",     "<api-nøkkel>"),
    ("jwt token",             "<token>"),
    ("bearer token",          "<token>"),
    ("passord i konfig",      "<passord>"),
    ("private key",           "<private-nøkkel>"),
    ("høy-entropisteng",      "<secret>"),
    ("konfigurasjonsord",     "<konfig-nøkkel>"),
    ("konfidensielt dokument","<[KONFIDENSIELT]>"),
    ("timepris",              "<timepris>"),
    ("dagspris",              "<dagspris>"),
    ("prosjektsum",           "<prosjektsum>"),
    ("margin",                "<margin>"),
    ("rabatt",                "<rabatt>"),
]

# AI-funn (fra dybdeskann) bruker [ANONYMISERT]
_AI_PREFIX = "🤖"


def _fixed_placeholder(category: str) -> str:
    cat = category.lower()
    for prefix, ph in _FIXED_PLACEHOLDER:
        if cat.startswith(prefix):
            return ph
    return "<sensitiv-info>"


def _label_alpha(prefix: str, index: int) -> str:
    if index < 26:
        return f"<{prefix} {_ALPHA[index]}>"
    return f"<{prefix} {index + 1}>"


def _label_num(prefix: str, index: int) -> str:
    return f"<{prefix} {index + 1}>"


def build_replacements(findings: list[Finding]) -> dict[str, str]:
    """Bygg {original_verdi: plassholder} dict fra valgte funn.

    Konsistent: samme tekst i samme dokument → samme plassholder.
    Brukes av anonymize_text() og patch.py (in-place filredigering).
    """
    result: dict[str, str] = {}
    # Registre for konsistent merking
    alpha_reg: dict[str, dict[str, str]] = {}  # label_prefix → {text: label}
    num_reg:   dict[str, dict[str, str]] = {}  # label_prefix → {text: label}

    for f in findings:
        target = f.raw_text if f.raw_text else f.text
        if not target or "…" in target or f.category.startswith("⚠"):
            continue
        if target in result:
            continue

        cat = f.category.lower().lstrip("🤖 ")

        # AI-funn: konsekvent [ANONYMISERT]
        if f.category.startswith(_AI_PREFIX):
            result[target] = "[ANONYMISERT]"
            continue

        # Sjekk alfa-kategorier (navn, selskap)
        matched = False
        for prefix_key, label_prefix in _ALPHA_CATEGORIES.items():
            if cat.startswith(prefix_key):
                reg = alpha_reg.setdefault(label_prefix, {})
                if target not in reg:
                    reg[target] = _label_alpha(label_prefix, len(reg))
                result[target] = reg[target]
                matched = True
                break

        if not matched:
            # Sjekk num-kategorier (kontonummer, epost, etc.)
            for prefix_key, label_prefix in _NUM_CATEGORIES.items():
                if cat.startswith(prefix_key):
                    reg = num_reg.setdefault(label_prefix, {})
                    if target not in reg:
                        reg[target] = _label_num(label_prefix, len(reg))
                    result[target] = reg[target]
                    matched = True
                    break

        if not matched:
            result[target] = _fixed_placeholder(f.category)

    return result


def anonymize_text(text: str, findings: list[Finding]) -> str:
    """Erstatter alle valgte funn i teksten med plassholdere.

    To-fase strategi for å unngå kollisjon mellom erstatninger:
    1. Erstatt originalverdier (lengste-først) med midlertidige null-byte-tokens.
    2. Erstatt tokens med de endelige lesbare plassholderne.

    Dette hindrer at f.eks. «Per Hansen» → «<Person A>» → «<Person B>son A>»
    fordi «Per» i plassholderen ikke tilhører originalteksten.
    """
    replacements = build_replacements(findings)
    if not replacements:
        return text

    # Fase 1: midlertidige tokens (null-bytes kan ikke oppstå i vanlig tekst)
    tokens: list[tuple[str, str]] = []
    result = text
    for i, (old, new) in enumerate(
        sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
    ):
        token = f"\x00{i}\x00"
        result = result.replace(old, token)
        tokens.append((token, new))

    # Fase 2: bytt tokens med endelige plassholdere
    for token, new in tokens:
        result = result.replace(token, new)
    return result
