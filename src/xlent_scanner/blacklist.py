"""Brukerdefinert blacklist for tekst som alltid skal fjernes.

Lagret i:
  Windows: %APPDATA%\\xlent-scanner\\blacklist.toml
  Mac:     ~/Library/Application Support/xlent-scanner/blacklist.toml

Format:
  texts = ["Project Raven", "kundeintern kode", ...]
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from xlent_scanner.models import Finding
from xlent_scanner.paths import app_data_dir
from xlent_scanner.utils import ctx as _ctx_base
from xlent_scanner.whitelist import _toml_str


def _blacklist_path() -> Path:
    return app_data_dir() / "blacklist.toml"


def blacklist_path_str() -> str:
    return str(_blacklist_path())


def get_blacklist_entries() -> list[str]:
    """Returner blacklist-verdier i opprinnelig casing/rekkefølge."""
    p = _blacklist_path()
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


def save_blacklist_entries(entries: list[str]) -> None:
    """Overskriv blacklist med ny liste (deduplisert case-insensitivt)."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in entries:
        text = str(raw).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)

    p = _blacklist_path()
    lines = [
        "# Brukerdefinert blacklist\n",
        "# Verdier her flagges alltid og fjernes ved anonymisering/redaction\n\n",
        "texts = [\n",
    ]
    for t in cleaned:
        lines.append(f"  {_toml_str(t)},\n")
    lines.append("]\n")
    p.write_text("".join(lines), encoding="utf-8")


def _ctx(text: str, start: int, end: int) -> str:
    return _ctx_base(text, start, end, radius=70)


def detect_blacklist(text: str) -> list[Finding]:
    """Finn brukerdefinerte blacklist-ord/uttrykk i tekst.

    Matching er case-insensitiv substring-match. Det er bevisst: listen er en
    eksplisitt "fjern alltid"-liste, ikke en heuristisk detektor.
    """
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for term in get_blacklist_entries():
        if not term:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        for m in pattern.finditer(text):
            key = (m.group(0).casefold(), m.start())
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(
                category="Blacklist",
                text=m.group(0),
                context=_ctx(text, m.start(), m.end()),
                severity="rød",
                raw_text=m.group(0),
            ))
    return findings
