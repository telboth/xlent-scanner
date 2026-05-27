"""Brukerdefinert hviteliste for false positives.

Lagret i:
  Windows: %APPDATA%\\xlent-scanner\\whitelist.toml
  Mac:     ~/Library/Application Support/xlent-scanner/whitelist.toml

Format:
  texts = ["john@example.com", "Firma AS", ...]
"""
from __future__ import annotations

import os
import platform
import tomllib
from pathlib import Path

from xlent_scanner.models import Finding


def _whitelist_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / "Library" / "Application Support"
    d = base / "xlent-scanner"
    d.mkdir(parents=True, exist_ok=True)
    return d / "whitelist.toml"


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


def add_to_whitelist(text: str) -> None:
    """Legg til en verdi i hvitelisten. Ignorerer duplikater."""
    p = _whitelist_path()
    existing: list[str] = []
    if p.exists():
        with open(p, "rb") as f:
            data = tomllib.load(f)
        existing = data.get("texts", [])
    if text in existing:
        return
    existing.append(text)
    lines = [
        "# Brukerdefinert hviteliste\n",
        "# Verdier her vil ikke varsles om i fremtidige skanninger\n",
        "# Rediger eller slett linjer manuelt for å fjerne oppføringer\n\n",
        "texts = [\n",
    ]
    for t in existing:
        lines.append(f"  {_toml_str(t)},\n")
    lines.append("]\n")
    p.write_text("".join(lines), encoding="utf-8")


def filter_by_whitelist(findings: list[Finding]) -> list[Finding]:
    """Fjern funn der f.text (lowercase) finnes i hvitelisten."""
    wl = load_whitelist()
    if not wl:
        return findings
    return [f for f in findings if f.text.lower() not in wl]
