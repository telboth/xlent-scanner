"""Felles scan-kategori-konfig for backend, API og frontend.

Denne modulen er den sentrale kategoriseamen: nye kategorier skal legges inn
her først, ikke kopieres manuelt mellom scanner.py og web/index.html.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from xlent_scanner.models import Finding, SuppressedFinding


@dataclass(frozen=True)
class ScanCategory:
    key: str
    label_key: str
    default_checked: bool = True
    ai_categories: tuple[str, ...] = ()
    regex_covered_for_ai: bool = False
    match_prefixes: tuple[str, ...] = ()


SCAN_CATEGORIES: tuple[ScanCategory, ...] = (
    ScanCategory("navn", "scanCatNavn", ai_categories=("navn",), match_prefixes=("navn (person)",)),
    ScanCategory("epost", "dstCatEpost", regex_covered_for_ai=True, ai_categories=("epost",), match_prefixes=("e-post",)),
    ScanCategory("telefon", "dstCatTelefon", regex_covered_for_ai=True, ai_categories=("telefon",), match_prefixes=("telefonnummer",)),
    ScanCategory("fodselsdato", "scanCatFodselsdato", match_prefixes=("fødselsdato",)),
    ScanCategory("id", "scanCatId", regex_covered_for_ai=True, ai_categories=("personnummer", "passnummer"), match_prefixes=(
        "fødselsnummer",
        "d-nummer",
        "personnummer",
        "samordningsnummer",
        "cpr-nummer",
        "uk national insurance",
        "us social security",
        "mulig personnummer",
        "passnummer",
        "tax identification number",
    )),
    ScanCategory("klient", "scanCatKlient", ai_categories=("selskapsnavn",), match_prefixes=("kundenavn",)),
    ScanCategory("orgnummer", "scanCatOrgnummer", regex_covered_for_ai=True, match_prefixes=("organisasjonsnummer",)),
    ScanCategory("nettadresse", "dstCatNettadresse", regex_covered_for_ai=True, ai_categories=("nettadresse",), match_prefixes=("nettadresse", "ip-adresse")),
    ScanCategory("konto", "scanCatKonto", ai_categories=("bankkonto", "swift"), match_prefixes=("kontonummer", "bankgiro", "plusgiro", "iban", "swift/bic")),
    ScanCategory("kredittkort", "scanCatKredittkort", regex_covered_for_ai=True, match_prefixes=("kredittkort",)),
    ScanCategory("hemmeligheter", "scanCatHemmeligheter", match_prefixes=(
        "openai",
        "anthropic",
        "github",
        "jwt",
        "bearer",
        "aws",
        "private key",
        "azure storage",
        "passord i konfig",
        "konfigurasjonsord",
        "høy-entropisteng",
    )),
    ScanCategory("finansielt", "scanCatFinansielt", ai_categories=("budsjett_tall", "lonn"), match_prefixes=(
        "timepris",
        "dagspris",
        "prosjektsum",
        "enhetspris",
        "margin",
        "rabatt",
        "budsjett",
        "lønn",
    )),
    ScanCategory("medisinsk", "dstCatMedisinsk", default_checked=False, ai_categories=("medisinsk",), match_prefixes=(
        "medisinsk",
        "medicinsk",
        "medical",
        "diagnose",
        "diagnosis",
        "legemiddel",
        "läkemedel",
        "medication",
    )),
    ScanCategory("konfidensielt", "scanCatKonfidensielt", regex_covered_for_ai=True, match_prefixes=("konfidensielt dokument",)),
    ScanCategory("adresse", "scanCatAdresse", ai_categories=("adresse",), match_prefixes=("fysisk adresse",)),
)

_CATEGORY_BY_KEY = {category.key: category for category in SCAN_CATEGORIES}
SCAN_CATEGORY_KEYS = frozenset(_CATEGORY_BY_KEY)

PROFILE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "lowfp": ("id", "konto", "kredittkort", "hemmeligheter", "konfidensielt", "orgnummer"),
    "normal": tuple(category.key for category in SCAN_CATEGORIES if category.default_checked and category.key != "medisinsk"),
    "strict": tuple(category.key for category in SCAN_CATEGORIES if category.default_checked or category.key == "medisinsk"),
}


def normalise_scan_categories(categories: Iterable[str] | None) -> frozenset[str] | None:
    """Normaliser valgte scan-kategorier.

    None betyr bakoverkompatibelt "kjør alt". En tom liste betyr at brukeren
    eksplisitt har valgt bort alle kategorier.
    """
    if categories is None:
        return None
    return frozenset(
        str(category).strip().lower()
        for category in categories
        if str(category).strip().lower() in SCAN_CATEGORY_KEYS
    )


def category_enabled(selected: frozenset[str] | None, *keys: str) -> bool:
    return selected is None or any(key in selected for key in keys)


def finding_matches_scan_categories(
    finding: Finding | SuppressedFinding,
    selected: frozenset[str] | None,
) -> bool:
    if selected is None:
        return True
    cat = str(finding.category or "").casefold()
    if cat.startswith("⚠"):
        return True
    for key in selected:
        category = _CATEGORY_BY_KEY.get(key)
        if category and any(cat.startswith(prefix) for prefix in category.match_prefixes):
            return True
    return False


def categories_payload() -> dict:
    return {
        "categories": [
            {
                "key": category.key,
                "label_key": category.label_key,
                "default_checked": category.default_checked,
                "ai_categories": list(category.ai_categories),
                "regex_covered_for_ai": category.regex_covered_for_ai,
                "match_prefixes": list(category.match_prefixes),
            }
            for category in SCAN_CATEGORIES
        ],
        "profiles": {name: list(keys) for name, keys in PROFILE_CATEGORIES.items()},
    }
