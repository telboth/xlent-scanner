"""Egendefinerte regex-detektorer fra custom_patterns.toml.

Lar brukeren fange organisasjonsspesifikke mønstre (prosjektkoder, interne
ID-formater, saksnumre) uten kodeendring. Redigeres som rå TOML i
Innstillinger, med server-side validering av regex og alvorlighetsgrad.

Filformat (%APPDATA%/xlent-scanner/custom_patterns.toml):

    [[patterns]]
    name = "Prosjektkode"
    regex = "PRJ-\\\\d{4}"
    severity = "gul"          # grønn / gul / rød / svart
    ignore_case = true        # valgfri, default true

Funn får kategori «Egendefinert: <name>» og beholder konfigurert severity
gjennom risk.assess() (egen unntaksregel der).
"""
from __future__ import annotations

import re
import threading
import tomllib
from pathlib import Path

from xlent_scanner.models import LEVELS, Finding
from xlent_scanner.paths import app_data_dir
from xlent_scanner.utils import ctx as _ctx_base

CATEGORY_PREFIX = "Egendefinert: "

_DEFAULT_TOML = """\
# Egendefinerte mønstre for XLENT Compliance-scanner
#
# Hvert mønster trenger name, regex og severity (grønn/gul/rød/svart).
# ignore_case er valgfri (default true).
#
# Tips: bruk enkle fnutter rundt regex-en ('...') — da trenger du IKKE
# å doble backslash-er. Eksempel:
#
# [[patterns]]
# name = "Prosjektkode"
# regex = 'PRJ-\\d{4}'
# severity = "gul"
"""

_MAX_MATCHES_PER_PATTERN = 200   # vern mot patologiske regexer på store dokumenter

_cache_lock = threading.Lock()
_compiled_cache: list[tuple[str, str, re.Pattern[str]]] | None = None


def custom_patterns_path() -> Path:
    return app_data_dir() / "custom_patterns.toml"


def custom_patterns_path_str() -> str:
    return str(custom_patterns_path())


def get_custom_patterns_text() -> str:
    """Rå TOML-tekst for editor-visning. Mal med eksempler hvis filen mangler."""
    p = custom_patterns_path()
    if p.exists():
        return p.read_text(encoding="utf-8")
    return _DEFAULT_TOML


def validate_custom_patterns_text(content: str) -> list[dict]:
    """Validerer TOML-innhold. Returnerer parsed mønsterliste eller raiser ValueError."""
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Ugyldig TOML: {exc}") from exc

    patterns = parsed.get("patterns", [])
    if not isinstance(patterns, list):
        raise ValueError("«patterns» må være en liste av [[patterns]]-blokker.")

    validated: list[dict] = []
    for i, entry in enumerate(patterns, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Mønster #{i}: må være en [[patterns]]-blokk.")
        name = str(entry.get("name") or "").strip()
        regex = str(entry.get("regex") or "")
        severity = str(entry.get("severity") or "gul").strip().lower()
        ignore_case = entry.get("ignore_case", True)

        if not name:
            raise ValueError(f"Mønster #{i}: «name» mangler.")
        if not regex:
            raise ValueError(f"Mønster #{i} ({name}): «regex» mangler.")
        if severity not in LEVELS:
            raise ValueError(
                f"Mønster #{i} ({name}): ugyldig severity «{severity}». "
                f"Gyldige verdier: {', '.join(LEVELS)}."
            )
        if not isinstance(ignore_case, bool):
            raise ValueError(f"Mønster #{i} ({name}): «ignore_case» må være true/false.")
        try:
            re.compile(regex)
        except re.error as exc:
            raise ValueError(f"Mønster #{i} ({name}): ugyldig regex — {exc}") from exc

        validated.append({
            "name": name,
            "regex": regex,
            "severity": severity,
            "ignore_case": ignore_case,
        })
    return validated


def save_custom_patterns_text(content: str) -> None:
    """Validerer og lagrer TOML-innholdet, og nullstiller detektor-cachen."""
    validate_custom_patterns_text(content)
    p = custom_patterns_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    reset_cache()


def reset_cache() -> None:
    global _compiled_cache
    with _cache_lock:
        _compiled_cache = None


def _get_compiled() -> list[tuple[str, str, re.Pattern[str]]]:
    """(name, severity, compiled_pattern) for alle gyldige mønstre. Cachet."""
    global _compiled_cache
    with _cache_lock:
        if _compiled_cache is not None:
            return _compiled_cache

        compiled: list[tuple[str, str, re.Pattern[str]]] = []
        p = custom_patterns_path()
        if p.exists():
            try:
                entries = validate_custom_patterns_text(p.read_text(encoding="utf-8"))
            except ValueError:
                entries = []   # korrupt fil: ingen mønstre fremfor å velte skann
            for e in entries:
                flags = re.IGNORECASE if e["ignore_case"] else 0
                compiled.append((e["name"], e["severity"], re.compile(e["regex"], flags)))
        _compiled_cache = compiled
        return compiled


def _ctx(text: str, start: int, end: int) -> str:
    return _ctx_base(text, start, end, radius=60)


def detect_custom_patterns(text: str) -> list[Finding]:
    """Kjører alle egendefinerte mønstre mot teksten."""
    findings: list[Finding] = []
    for name, severity, pattern in _get_compiled():
        seen: set[str] = set()
        for n, m in enumerate(pattern.finditer(text)):
            if n >= _MAX_MATCHES_PER_PATTERN:
                break
            value = m.group(0)
            if not value or value in seen:
                continue
            seen.add(value)
            findings.append(Finding(
                category=f"{CATEGORY_PREFIX}{name}",
                text=value,
                context=_ctx(text, m.start(), m.end()),
                severity=severity,
                raw_text=value,
            ))
    return findings
