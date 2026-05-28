"""Felles hjelpe-funksjoner brukt av detektorer og andre moduler."""
from __future__ import annotations


def ctx(text: str, start: int, end: int, radius: int = 40) -> str:
    """Returner et kontekstutdrag rundt [start, end] i teksten."""
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi].replace("\n", " ")
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(text) else "")
