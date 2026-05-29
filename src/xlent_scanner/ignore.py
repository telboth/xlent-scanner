"""Laster og anvender ignore-listen fra ignore.toml.

Brukeren kan overstyre med en lokal fil:
  Windows: %APPDATA%\\xlent-scanner\\ignore.toml
  Mac:     ~/Library/Application Support/xlent-scanner/ignore.toml
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from xlent_scanner.models import Finding
from xlent_scanner.paths import app_data_dir

_BUNDLED = Path(__file__).parent / "data" / "ignore.toml"


def _user_override_path() -> Path:
    return app_data_dir() / "ignore.toml"


def ignore_path_str() -> str:
    return str(_user_override_path())


def get_ignore_toml_text() -> str:
    """Return editable TOML text for ignore config.

    Preference order:
    1) user override file (if it exists)
    2) bundled default file
    """
    user_path = _user_override_path()
    if user_path.exists():
        return user_path.read_text(encoding="utf-8")
    return _BUNDLED.read_text(encoding="utf-8")


def save_ignore_toml_text(content: str) -> None:
    """Validate and save user override ignore.toml."""
    parsed = tomllib.loads(content)
    for key in ("email_domains", "names"):
        if key in parsed:
            value = parsed[key]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"Ugyldig format for '{key}'. Forventet liste med tekstverdier.")

    user_path = _user_override_path()
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text(content, encoding="utf-8")


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
