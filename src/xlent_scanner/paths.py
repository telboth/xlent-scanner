"""Sentralisert app-data-mappe for xlent-scanner.

Platform-støtte:
  Windows:  %APPDATA%\\xlent-scanner\\
  macOS:    ~/Library/Application Support/xlent-scanner/
  Linux:    $XDG_DATA_HOME/xlent-scanner/  (fallback: ~/.local/share/xlent-scanner/)
"""
from __future__ import annotations

import os
import platform
from pathlib import Path


def app_data_dir() -> Path:
    """Returnerer (og oppretter) brukerdata-mappen for xlent-scanner."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        # Linux / BSDs: XDG Base Directory Specification
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "xlent-scanner"
    d.mkdir(parents=True, exist_ok=True)
    return d
