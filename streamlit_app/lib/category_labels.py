"""Norske etiketter for scan-kategorier.

Kategoridefinisjonene (nøkler, profiler) hentes fra xlent_scanner.scan_categories,
mens denne modulen kun holder de norske visningsnavnene for GUI-et.
"""
from __future__ import annotations

from xlent_scanner.scan_categories import PROFILE_CATEGORIES, SCAN_CATEGORIES

# Nøkkel → norsk etikett
CATEGORY_LABELS: dict[str, str] = {
    "navn": "Navn",
    "epost": "E-post",
    "telefon": "Telefon",
    "id": "Personnummer / ID",
    "klient": "Firma / org.nr.",
    "nettadresse": "Nettadresser",
    "konto": "Bankdetaljer",
    "hemmeligheter": "Hemmeligheter / konfidensielt",
    "finansielt": "Budsjettall",
    "medisinsk": "Medisinsk",
    "adresse": "Fysiske adresser",
}

# Profilnøkkel → norsk etikett + kort forklaring
PROFILE_LABELS: dict[str, tuple[str, str]] = {
    "lowfp": ("Få falske positive", "Kun høy-sikkerhet: ID, konto, kort, secrets, org.nr"),
    "normal": ("Normal", "Standard sett med kategorier (anbefalt)"),
    "strict": ("Streng", "Alt inkludert medisinsk – flest funn, flere falske positive"),
}


def label_for(key: str) -> str:
    return CATEGORY_LABELS.get(key, key)


def all_category_keys() -> list[str]:
    return [c.key for c in SCAN_CATEGORIES]


def category_columns() -> tuple[list[str], list[str], list[str]]:
    """Samme kategorioppsett som hovedfrontenden: 4 + 4 + 3 valg."""
    keys = all_category_keys()
    return (keys[:4], keys[4:8], keys[8:])


def default_categories() -> list[str]:
    return list(PROFILE_CATEGORIES["normal"])


def categories_for_profile(profile: str) -> list[str]:
    return list(PROFILE_CATEGORIES.get(profile, PROFILE_CATEGORIES["normal"]))
