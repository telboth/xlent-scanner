"""Anonymisering: erstatter valgte funn i tekst med nøytrale plassholdere."""
from __future__ import annotations

from xlent_scanner.models import Finding

_PLACEHOLDERS: list[tuple[str, str]] = [
    ("fødselsnummer",               "<fødselsnummer>"),
    ("d-nummer",                    "<d-nummer>"),
    ("kontonummer",                 "<kontonummer>"),
    ("e-post",                      "<e-post>"),
    ("telefonnummer",               "<tlf-nummer>"),
    ("organisasjonsnummer",         "<orgnr>"),
    ("navn (person)",               "<navn>"),
    ("kundenavn",                   "<kundenavn>"),
    ("aws access key",              "<api-nøkkel>"),
    ("openai api key",              "<api-nøkkel>"),
    ("anthropic api key",           "<api-nøkkel>"),
    ("github token",                "<api-nøkkel>"),
    ("azure storage key",           "<api-nøkkel>"),
    ("jwt token",                   "<token>"),
    ("bearer token",                "<token>"),
    ("passord i konfig",            "<passord>"),
    ("private key",                 "<private-nøkkel>"),
    ("høy-entropisteng",            "<secret>"),
    ("konfigurasjonsord",           "<konfig-nøkkel>"),
    ("konfidensielt dokument",      "<[KONFIDENSIELT]>"),
]


def _placeholder(category: str) -> str:
    cat = category.lower()
    for prefix, ph in _PLACEHOLDERS:
        if cat.startswith(prefix):
            return ph
    return "<sensitiv-info>"


def build_replacements(findings: list[Finding]) -> dict[str, str]:
    """Bygg {original_verdi: plassholder} dict fra valgte funn.

    Brukes av både anonymize_text og patch.py (in-place filredigering).
    """
    result: dict[str, str] = {}
    for f in findings:
        target = f.raw_text if f.raw_text else f.text
        if not target or "…" in target or f.category.startswith("⚠"):
            continue
        if target not in result:
            result[target] = _placeholder(f.category)
    return result


def anonymize_text(text: str, findings: list[Finding]) -> str:
    """Erstatter alle valgte funn i teksten med plassholdere."""
    replacements = build_replacements(findings)
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result
