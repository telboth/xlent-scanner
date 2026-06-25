"""Felles hjelpe-funksjoner brukt av detektorer og andre moduler."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def ctx(text: str, start: int, end: int, radius: int = 40) -> str:
    """Returner et kontekstutdrag rundt [start, end] i teksten."""
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi].replace("\n", " ")
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(text) else "")


def open_path(path: Path) -> None:
    """Åpne en fil med operativsystemets standardprogram."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_path(path: Path) -> None:
    """Vis en fil i operativsystemets filbehandler."""
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
