"""Laster og anvender ignore-listen fra ignore.toml.

Brukeren kan overstyre med en lokal fil:
  Windows: %APPDATA%\\xlent-scanner\\ignore.toml
  Mac:     ~/Library/Application Support/xlent-scanner/ignore.toml
"""
from __future__ import annotations

import os
import platform
import tomllib
from pathlib import Path

from xlent_scanner.models import Finding

_BUNDLED = Path(__file__).parent / "data" / "ignore.toml"


def _user_override_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / "Library" / "Application Support"
    return base / "xlent-scanner" / "ignore.toml"


def load_ignore_list() -> dict:
    data: dict = {"email_domains": [], "names": []}
    for path in [_BUNDLED, _user_override_path()]:
        if path.exists():
            with open(path, "rb") as f:
                loaded = tomllib.load(f)
            data["email_domains"] = list({
                *data["email_domains"],
                *loaded.get("email_domains", []),
            })
            data["names"] = list({
                *data["names"],
                *loaded.get("names", []),
            })
    return data


def filter_findings(findings: list[Finding], ignore: dict) -> list[Finding]:
    """Fjerner funn som matcher ignore-listen."""
    domains = {d.lower() for d in ignore.get("email_domains", [])}
    names_raw = ignore.get("names", [])
    ignore_names = {n.lower() for n in names_raw}
    ignore_name_parts = {
        part.lower()
        for name in names_raw
        for part in name.split()
        if len(part) > 2
    }

    result = []
    for f in findings:
        val = f.text.lower()

        if f.category == "e-post":
            domain = val.split("@")[-1] if "@" in val else ""
            if any(domain == d or domain.endswith("." + d) for d in domains):
                continue

        if f.category == "navn (person)":
            if val in ignore_names or val in ignore_name_parts:
                continue

        result.append(f)
    return result
