"""Detektor for API-nøkler, secrets og høy-entropistenger.

Strategi:
  1. Kjente mønstre (høy presisjon) — AWS, OpenAI, Anthropic, GitHub, JWT, private keys m.fl.
  2. Entropy-basert fallback — lange alphanumeriske strenger med Shannon-entropi > terskel.
"""
from __future__ import annotations

import math
import re
from typing import Iterator

from xlent_scanner.models import Finding


# ── kontekst-hjelper ──────────────────────────────────────────────────────────

def _ctx(text: str, start: int, end: int, radius: int = 40) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi].replace("\n", " ")
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(text) else "")


# ── kjente mønstre ────────────────────────────────────────────────────────────

_KNOWN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # AWS
    ("AWS Access Key ID",
     re.compile(r"\b(?:AKIA|ASIA|AROA|AIDA|AIPA|ANPA|ANVA|APKA)[0-9A-Z]{16}\b")),
    # OpenAI
    ("OpenAI API Key",
     re.compile(r"\bsk-[a-zA-Z0-9]{48}\b")),
    ("OpenAI API Key (project)",
     re.compile(r"\bsk-proj-[a-zA-Z0-9_\-]{40,}\b")),
    # Anthropic
    ("Anthropic API Key",
     re.compile(r"\bsk-ant-(?:api03-)?[a-zA-Z0-9_\-]{40,}\b")),
    # GitHub
    ("GitHub Token",
     re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b")),
    # Azure Storage
    ("Azure Storage Key",
     re.compile(r"DefaultEndpointsProtocol=https?;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{80,}")),
    # Generic Bearer / Authorization header
    ("Bearer Token",
     re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-]{30,})")),
    # JWT
    ("JWT Token",
     re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),
    # Private keys
    ("Private Key (PEM)",
     re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    # Generic connection strings / passwords i config-format
    ("Passord i konfig",
     re.compile(r"(?i)(?:password|passwd|secret|token|api[_\-]?key)\s*[=:]\s*['\"]?([^\s'\"]{8,})")),
]


def find_known_secrets(text: str) -> Iterator[Finding]:
    for label, pattern in _KNOWN_PATTERNS:
        for m in pattern.finditer(text):
            # Bruk capture-gruppe (verdien alene) der den finnes, ellers hele matchen
            sensitive = m.group(1) if (m.lastindex and m.lastindex >= 1) else m.group(0)
            masked = _mask(sensitive)
            f = Finding(label, masked, _ctx(text, m.start(), m.end()))
            f.raw_text = sensitive
            yield f


def _mask(s: str, keep: int = 6) -> str:
    """Viser de første og siste tegnene, maskerer midten."""
    if len(s) <= keep * 2:
        return "*" * len(s)
    return s[:keep] + "…" + s[-keep:]


# ── entropi-basert fallback ───────────────────────────────────────────────────

def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


# Matcher lange sekvenser som ligner base64 eller hex
_HIGH_ENTROPY_RE = re.compile(
    r"(?<![A-Za-z0-9+/=])"
    r"([A-Za-z0-9+/=_\-]{28,80})"
    r"(?![A-Za-z0-9+/=])"
)

_ENTROPY_THRESHOLD = 4.2   # bits per tegn; base64-random er ~6, leselig tekst ~3–3.5


def find_high_entropy(text: str) -> Iterator[Finding]:
    for m in _HIGH_ENTROPY_RE.finditer(text):
        candidate = m.group(1)
        entropy = _shannon_entropy(candidate)
        if entropy >= _ENTROPY_THRESHOLD:
            f = Finding(
                "Høy-entropisteng (mulig secret)",
                _mask(candidate),
                _ctx(text, m.start(), m.end()),
            )
            f.raw_text = candidate
            yield f


# ── samlet ────────────────────────────────────────────────────────────────────

def detect_secrets(text: str) -> list[Finding]:
    known = list(find_known_secrets(text))
    known_raws = {f.raw_text for f in known if f.raw_text}
    entropy_findings = [
        f for f in find_high_entropy(text)
        if f.raw_text not in known_raws
    ]
    return known + entropy_findings
