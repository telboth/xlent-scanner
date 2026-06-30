from __future__ import annotations
from dataclasses import dataclass, field


LEVELS = ("grønn", "gul", "rød", "svart")
SCAN_STATUSES = ("success", "partial", "failed")


@dataclass
class Finding:
    category: str
    text: str          # vises i rapport; secrets er maskert her
    context: str = ""
    severity: str = "gul"   # grønn / gul / rød / svart
    raw_text: str = ""      # original umasket verdi – brukes til anonymisering


@dataclass
class SuppressedFinding:
    category: str
    text: str
    context: str = ""
    reason: str = ""
    source: str = "Regelbasert"


@dataclass
class ScanResult:
    file_name: str
    file_size: int
    text_length: int
    text_preview: str
    relative_path: str = ""
    source_path: str = ""
    findings: list[Finding] = field(default_factory=list)
    suppressed_findings: list[SuppressedFinding] = field(default_factory=list)
    error: str | None = None
    risk_level: str = "grønn"         # grønn / gul / rød / svart
    risk_summary: str = ""
    recommended_action: str = ""
    original_text: str = ""           # full ekstrahert tekst – brukes til anonymisering
    language: str = ""                # detektert/valgt språk: nb / sv / en
    warning: str | None = None        # advarsel om tom/bilde-basert fil
    warning_code: str | None = None   # stabil kode som GUI/API kan oversette
    ocr_used: bool = False            # teksten er ekstrahert med OCR
    microsoft_tags: dict = field(default_factory=dict)
    policy_warning: str | None = None
    policy_warning_level: str | None = None
    scan_status: str = "success"      # success / partial / failed
    scan_timings: dict = field(default_factory=dict)
