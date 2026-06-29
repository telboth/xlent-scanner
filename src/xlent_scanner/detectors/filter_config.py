"""Konfigurasjon for false-positive-filtre i detektorene."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
import tomllib


@dataclass(frozen=True)
class PersonNameFilters:
    stopwords: frozenset[str]
    org_keywords: frozenset[str]
    org_names: frozenset[str]
    generic_title_case_words: frozenset[str]
    technical_title_case_words: frozenset[str]
    place_or_thing_preceders: frozenset[str]
    place_or_thing_followers: frozenset[str]


def _as_frozenset(data: dict, key: str, fallback: tuple[str, ...] = ()) -> frozenset[str]:
    values = data.get(key, fallback)
    if not isinstance(values, list | tuple):
        values = fallback
    return frozenset(str(value).casefold() for value in values if str(value).strip())


@lru_cache(maxsize=1)
def load_person_name_filters() -> PersonNameFilters:
    """Last personnavn-postfiltre fra pakkedata."""
    try:
        raw = (
            resources.files("xlent_scanner.data")
            .joinpath("person_name_filters.toml")
            .read_bytes()
        )
        root = tomllib.loads(raw.decode("utf-8"))
        data = root.get("person_names", {}) if isinstance(root, dict) else {}
    except Exception:
        data = {}

    return PersonNameFilters(
        stopwords=_as_frozenset(data, "stopwords", ("api", "data", "system")),
        org_keywords=_as_frozenset(data, "org_keywords", ("as", "ltd", "kommune")),
        org_names=_as_frozenset(data, "org_names", ("microsoft", "google", "xlent")),
        generic_title_case_words=_as_frozenset(
            data,
            "generic_title_case_words",
            ("analysis", "figure", "table", "system", "price"),
        ),
        technical_title_case_words=_as_frozenset(
            data,
            "technical_title_case_words",
            ("code", "batch", "machine", "development"),
        ),
        place_or_thing_preceders=_as_frozenset(data, "place_or_thing_preceders", ("the", "of", "in")),
        place_or_thing_followers=_as_frozenset(data, "place_or_thing_followers", ("field", "basin", "unit")),
    )
