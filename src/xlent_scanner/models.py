from __future__ import annotations
from dataclasses import dataclass, field


LEVELS = ("grønn", "gul", "rød", "svart")


@dataclass
class Finding:
    category: str
    text: str          # vises i rapport; secrets er maskert her
    context: str = ""
    severity: str = "gul"   # grønn / gul / rød / svart
    raw_text: str = ""      # original umasket verdi – brukes til anonymisering


@dataclass
class ScanResult:
    file_name: str
    file_size: int
    text_length: int
    text_preview: str
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None
    risk_level: str = "grønn"         # grønn / gul / rød / svart
    risk_summary: str = ""
    recommended_action: str = ""
    original_text: str = ""           # full ekstrahert tekst – brukes til anonymisering
    language: str = ""                # detektert/valgt språk: nb / sv / en
    warning: str | None = None        # advarsel om tom/bilde-basert fil
    warning_code: str | None = None   # stabil kode som GUI/API kan oversette
