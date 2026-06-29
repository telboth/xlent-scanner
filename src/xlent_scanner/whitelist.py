"""Brukerdefinert hviteliste for false positives.

Lagret i:
  Windows: %APPDATA%\\xlent-scanner\\whitelist.toml
  Mac:     ~/Library/Application Support/xlent-scanner/whitelist.toml

Format:
  texts = ["john@example.com", "Firma AS", ...]
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from xlent_scanner.models import Finding
from xlent_scanner.paths import app_data_dir


_NON_WHITELISTABLE_CATEGORY_TOKENS = (
    "prosjektsum",
    "fødselsdato",
    "fodselsdato",
    "fødselsdata",
    "fodselsdata",
    "budsjettall",
    "budsjett",
)


def _whitelist_path() -> Path:
    return app_data_dir() / "whitelist.toml"


def _toml_str(s: str) -> str:
    """Pakk inn en streng som TOML basic string med korrekt escaping."""
    # Rekkefølge: backslash må escapes først
    s = s.replace("\\", "\\\\")
    s = s.replace('"',  '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    s = s.replace("\b", "\\b")
    s = s.replace("\f", "\\f")
    # Øvrige kontrolltegn (U+0000–U+001F) som TOML ikke tillater i strenger
    s = "".join(
        c if ord(c) >= 0x20 else f"\\u{ord(c):04X}"
        for c in s
    )
    return '"' + s + '"'


def load_whitelist() -> set[str]:
    """Les hvitelisten fra disk. Returnerer lowercase-sett for matching.

    Dersom filen er korrupt (f.eks. ukescapede kontrolltegn), flyttes den til
    whitelist.toml.bak og en ny tom fil opprettes automatisk.
    """
    p = _whitelist_path()
    if not p.exists():
        return set()
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
        return {t.lower() for t in data.get("texts", [])}
    except tomllib.TOMLDecodeError:
        # Korrupt fil – arkiver den og start på nytt
        bak = p.with_suffix(".toml.bak")
        try:
            p.rename(bak)
        except OSError:
            p.unlink(missing_ok=True)
        return set()


def whitelist_path_str() -> str:
    return str(_whitelist_path())


def get_whitelist_entries() -> list[str]:
    """Returner whitelist-verdier i opprinnelig casing/rekkefølge."""
    p = _whitelist_path()
    if not p.exists():
        return []
    try:
        with open(p, "rb") as f:
            data = tomllib.load(f)
        texts = data.get("texts", [])
        return [str(t) for t in texts if isinstance(t, str)]
    except tomllib.TOMLDecodeError:
        bak = p.with_suffix(".toml.bak")
        try:
            p.rename(bak)
        except OSError:
            p.unlink(missing_ok=True)
        return []


def save_whitelist_entries(entries: list[str]) -> None:
    """Overskriv whitelist med ny liste (deduplisert, tomme linjer fjernet)."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in entries:
        text = str(raw).strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)

    p = _whitelist_path()
    lines = [
        "# Brukerdefinert hviteliste\n",
        "# Verdier her vil ikke varsles om i fremtidige skanninger\n",
        "# Rediger eller slett linjer manuelt for å fjerne oppføringer\n\n",
        "texts = [\n",
    ]
    for t in cleaned:
        lines.append(f"  {_toml_str(t)},\n")
    lines.append("]\n")
    p.write_text("".join(lines), encoding="utf-8")


def add_to_whitelist(text: str) -> None:
    """Legg til en verdi i hvitelisten. Ignorerer duplikater."""
    existing = get_whitelist_entries()
    if text in existing:
        return
    existing.append(text)
    save_whitelist_entries(existing)


def category_allows_whitelist(category: str) -> bool:
    """Returner False for funnkategorier der whitelist ikke gir faglig mening."""
    normalized = str(category or "").casefold().replace("🤖", "").strip()
    return not any(token in normalized for token in _NON_WHITELISTABLE_CATEGORY_TOKENS)


def filter_by_whitelist(findings: list[Finding]) -> list[Finding]:
    """Fjern funn der f.text (lowercase) finnes i hvitelisten.
    Beholdt for bakoverkompatibilitet; bruk mark_whitelist_findings() for ny kode."""
    wl = load_whitelist()
    if not wl:
        return findings
    return [
        f
        for f in findings
        if f.text.lower() not in wl or not category_allows_whitelist(f.category)
    ]


def mark_whitelist_findings(findings: list[Finding]) -> list[Finding]:
    """Markerer hvitelistede funn som grønne i stedet for å fjerne dem.

    Grønne funn vises i listen (brukeren ser at de ble funnet men er godkjent)
    og påvirker ikke det overordnede risikonivået (grønn = 0 i risikovektingen).
    """
    import dataclasses  # noqa: PLC0415
    wl = load_whitelist()
    if not wl:
        return findings
    result: list[Finding] = []
    for f in findings:
        if f.text.lower() in wl and category_allows_whitelist(f.category):
            # Merk som grønn – preserve all other fields
            result.append(dataclasses.replace(f, severity="grønn"))
        else:
            result.append(f)
    return result
