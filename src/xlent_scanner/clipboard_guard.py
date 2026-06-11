"""Utklippstavle-vakt: overvåker utklippstavlen og varsler ved sensitivt innhold.

Designprinsipper:
  - 100 % lokal: utklippstavle-innhold forlater aldri maskinen og lagres aldri.
    Kun en hash av sist varslede innhold holdes i minne (for å unngå re-varsling).
  - Opt-in: startes/stoppes eksplisitt fra GUI (Innstillinger).
  - Lav kost ved inaktivitet: på Windows polles GetClipboardSequenceNumber
    (et rent ctypes-kall) og innholdet leses kun når nummeret endres.
  - Best-effort: feil i lesing/skanning logges og hopper over runden.

Varsling skjer ved rød/svart risikonivå via notify.notify() + en hendelseslogg
(`recent_alerts`) som GUI-et kan vise.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import threading
import time
from typing import Any, Callable

LOGGER = logging.getLogger("xlent_scanner")

_POLL_SECONDS = 2.0
_MIN_TEXT_LEN = 15           # korte snutter («ja», en URL-bit) gir bare støy
_MAX_TEXT_LEN = 50_000       # skann maks 50k tegn per utklipp
_ALERT_COOLDOWN_SECONDS = 8  # ikke spam ved hurtige kopieringer
_ALERT_LEVELS = ("rød", "svart")
_MAX_RECENT_ALERTS = 20


# ── Plattformspesifikk utklippstavle-lesing (kun stdlib) ─────────────────────

def _clipboard_sequence_windows() -> int | None:
    try:
        import ctypes  # noqa: PLC0415
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        return None


def _read_clipboard_windows() -> str | None:
    import ctypes  # noqa: PLC0415
    import ctypes.wintypes as w  # noqa: PLC0415

    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [w.HGLOBAL]
    user32.GetClipboardData.restype = w.HGLOBAL

    if not user32.OpenClipboard(0):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _read_clipboard_macos() -> str | None:
    try:
        out = subprocess.run(
            ["pbpaste"], capture_output=True, timeout=5,
        )
        return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None
    except Exception:
        return None


def _read_clipboard_linux() -> str | None:
    for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]):
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=5)
            if out.returncode == 0:
                return out.stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            continue
        except Exception:
            return None
    return None


def read_clipboard_text() -> str | None:
    """Leser utklippstavlen som tekst. None ved feil eller ikke-tekst-innhold."""
    try:
        if sys.platform == "win32":
            return _read_clipboard_windows()
        if sys.platform == "darwin":
            return _read_clipboard_macos()
        return _read_clipboard_linux()
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("Utklippstavle-lesing feilet: %s", exc)
        return None


# ── Vurdering av ett utklipp ─────────────────────────────────────────────────

def evaluate_clipboard_text(text: str) -> dict[str, Any] | None:
    """Skanner utklippstekst og returnerer varselinfo hvis rød/svart, ellers None.

    Returnerer aldri selve teksten — kun risikonivå, antall funn og
    kategoriliste, slik at varselet ikke selv lekker sensitivt innhold.
    """
    if not text or len(text.strip()) < _MIN_TEXT_LEN:
        return None
    from xlent_scanner.scanner import scan_text  # noqa: PLC0415

    result = scan_text(text[:_MAX_TEXT_LEN], language="auto", source_name="Utklippstavle")
    if result.risk_level not in _ALERT_LEVELS:
        return None
    categories: list[str] = []
    for f in result.findings:
        if f.severity in _ALERT_LEVELS and not f.category.startswith("⚠"):
            if f.category not in categories:
                categories.append(f.category)
    return {
        "risk_level": result.risk_level,
        "finding_count": len([f for f in result.findings if f.severity in _ALERT_LEVELS]),
        "categories": categories[:6],
        "timestamp": time.time(),
    }


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ── Vakt-tråden ───────────────────────────────────────────────────────────────

class ClipboardGuard:
    """Polling-basert utklippstavle-vakt. Trådsikker start/stop/status."""

    def __init__(self, notifier: Callable[[str, str], Any] | None = None) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_hash: str = ""
        self._last_alert_hash: str = ""
        self._last_alert_at: float = 0.0
        self._last_sequence: int | None = None
        self._started_at: float = 0.0
        self._checks = 0
        self._alerts: list[dict] = []
        self._notifier = notifier

    # — offentlig API —

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._started_at = time.time()
            self._checks = 0
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="clipboard-guard",
            )
            self._thread.start()
        LOGGER.info("Utklippstavle-vakt startet")
        return True

    def stop(self) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._stop_event.set()
        LOGGER.info("Utklippstavle-vakt stoppet")
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()
            return {
                "running": running,
                "started_at": self._started_at if running else None,
                "checks": self._checks,
                "recent_alerts": list(self._alerts),
            }

    # — intern —

    def _clipboard_changed(self) -> bool:
        """Billig endringssjekk der plattformen støtter det (Windows)."""
        if sys.platform == "win32":
            seq = _clipboard_sequence_windows()
            if seq is not None:
                if seq == self._last_sequence:
                    return False
                self._last_sequence = seq
                return True
        return True   # andre plattformer: les og hash-sammenlign

    def _handle_text(self, text: str) -> None:
        h = _content_hash(text)
        if h == self._last_hash:
            return
        self._last_hash = h

        alert = evaluate_clipboard_text(text)
        if alert is None:
            return

        now = time.time()
        if h == self._last_alert_hash:
            return   # samme innhold allerede varslet
        if now - self._last_alert_at < _ALERT_COOLDOWN_SECONDS:
            return
        self._last_alert_hash = h
        self._last_alert_at = now

        with self._lock:
            self._alerts.append(alert)
            del self._alerts[:-_MAX_RECENT_ALERTS]

        cats = ", ".join(alert["categories"][:3]) or "sensitiv informasjon"
        icon = "⛔" if alert["risk_level"] == "svart" else "🚫"
        notifier = self._notifier
        if notifier is None:
            from xlent_scanner.notify import notify as notifier  # noqa: PLC0415
        notifier(
            f"{icon} XLENT Scanner: sensitivt innhold på utklippstavlen",
            f"Nivå: {alert['risk_level'].upper()} — {cats}. "
            "Vurder å anonymisere før du limer inn i AI-verktøy.",
        )
        LOGGER.info(
            "Utklippstavle-varsel: nivå=%s kategorier=%s",
            alert["risk_level"], alert["categories"],
        )

    def _run(self) -> None:
        while not self._stop_event.wait(_POLL_SECONDS):
            try:
                with self._lock:
                    self._checks += 1
                if not self._clipboard_changed():
                    continue
                text = read_clipboard_text()
                if text:
                    self._handle_text(text)
            except Exception as exc:  # noqa: BLE001 — vakten skal aldri dø
                LOGGER.warning("Utklippstavle-vakt: feil i runde: %s", exc)


# Global singleton brukt av Flask-endepunktene
guard = ClipboardGuard()
