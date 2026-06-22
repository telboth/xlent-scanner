"""Overvåket mappe: skanner automatisk nye og endrede filer i en valgt mappe.

Polling-basert (kun stdlib — ingen watchdog-avhengighet):
  - Hvert intervall tas et øyeblikksbilde {sti: (mtime, størrelse)} av støttede
    filer i mappen (ikke rekursivt).
  - Nye/endrede filer skannes først når de har vært stabile i to runder
    (samme mtime+størrelse) — unngår å lese halvskrevne nedlastinger.
  - Midlertidige filer (~$, .tmp, .crdownload, .partial, .download) hoppes over.
  - Rød/svart gir systemvarsel; alle resultater legges i historikken og i en
    intern resultatliste som GUI-et kan vise.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("xlent_scanner")

_POLL_SECONDS = 5.0
_ALERT_LEVELS = ("rød", "svart")
_MAX_RESULTS = 50
_MAX_WATCHED_FOLDERS = 3

_SKIP_PREFIXES = ("~$", ".")
_SKIP_SUFFIXES = (".tmp", ".crdownload", ".partial", ".download", ".part")


def _is_temp_file(name: str) -> bool:
    lower = name.lower()
    return name.startswith(_SKIP_PREFIXES) or lower.endswith(_SKIP_SUFFIXES)


def snapshot_folder(folder: Path) -> dict[str, tuple[float, int]]:
    """Øyeblikksbilde av støttede filer: {sti: (mtime, størrelse)}."""
    from xlent_scanner.scanner import SUPPORTED_SUFFIXES  # noqa: PLC0415

    snap: dict[str, tuple[float, int]] = {}
    try:
        for p in folder.iterdir():
            if not p.is_file() or _is_temp_file(p.name):
                continue
            if p.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            snap[str(p)] = (st.st_mtime, st.st_size)
    except OSError as exc:
        LOGGER.warning("Mappeovervåking: klarte ikke å lese mappen: %s", exc)
    return snap


def changed_paths(
    previous: dict[str, tuple[float, int]],
    current: dict[str, tuple[float, int]],
) -> list[str]:
    """Stier som er nye eller endret (mtime/størrelse) siden forrige runde."""
    out: list[str] = []
    for path, meta in current.items():
        if previous.get(path) != meta:
            out.append(path)
    return out


class FolderWatcher:
    """Overvåker én mappe. Trådsikker start/stop/status."""

    def __init__(self, notifier: Callable[[str, str], Any] | None = None) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._folder: Path | None = None
        self._ignore_xlent = False
        self._language = "auto"
        self._started_at: float = 0.0
        self._scanned_count = 0
        self._results: list[dict] = []
        self._notifier = notifier

    # — offentlig API —

    def start(self, folder: str, ignore_xlent: bool = False, language: str = "auto") -> dict[str, Any]:
        p = Path(folder)
        if not p.is_dir():
            return {"ok": False, "error": f"Ikke en mappe: {folder}"}
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                # Bytt mappe: stopp gammel tråd først
                self._stop_event.set()
                self._thread.join(timeout=2 * _POLL_SECONDS)
            self._stop_event = threading.Event()
            self._folder = p
            self._ignore_xlent = bool(ignore_xlent)
            self._language = language or "auto"
            self._started_at = time.time()
            self._scanned_count = 0
            self._results = []
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="folder-watch",
            )
            self._thread.start()
        LOGGER.info("Mappeovervåking startet: %s", p)
        return {"ok": True, "folder": str(p)}

    def stop(self) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._stop_event.set()
        LOGGER.info("Mappeovervåking stoppet")
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()
            return {
                "running": running,
                "folder": str(self._folder) if self._folder else None,
                "started_at": self._started_at if running else None,
                "scanned_count": self._scanned_count,
                "recent_results": list(self._results),
            }

    # — intern —

    def _scan_one(self, path_str: str) -> None:
        from xlent_scanner.history import add_history_entry  # noqa: PLC0415
        from xlent_scanner.scanner import scan_file  # noqa: PLC0415

        result = scan_file(path_str, ignore_xlent=self._ignore_xlent, language=self._language)
        entry = {
            "file_name": result.file_name,
            "path": path_str,
            "risk_level": result.risk_level,
            "finding_count": len([f for f in result.findings if not f.category.startswith("⚠")]),
            "error": result.error,
            "timestamp": time.time(),
        }
        with self._lock:
            self._scanned_count += 1
            self._results.append(entry)
            del self._results[:-_MAX_RESULTS]

        try:
            add_history_entry(
                file_name=result.file_name,
                risk_level=result.risk_level,
                finding_count=entry["finding_count"],
                file_size=result.file_size,
                source="watch",
            )
        except Exception:  # noqa: BLE001
            pass

        if result.error is None and result.risk_level in _ALERT_LEVELS:
            icon = "⛔" if result.risk_level == "svart" else "🚫"
            notifier = self._notifier
            if notifier is None:
                from xlent_scanner.notify import notify as notifier  # noqa: PLC0415
            notifier(
                f"{icon} XLENT Scanner: sensitiv fil i overvåket mappe",
                f"{result.file_name} — nivå {result.risk_level.upper()} "
                f"({entry['finding_count']} funn).",
            )
            LOGGER.info(
                "Mappeovervåking-varsel: fil=%s nivå=%s funn=%d",
                result.file_name, result.risk_level, entry["finding_count"],
            )

    def _run(self) -> None:
        folder = self._folder
        if folder is None:
            return
        # Baseline: eksisterende filer skannes ikke — kun det som kommer til
        previous = snapshot_folder(folder)
        pending: dict[str, tuple[float, int]] = {}

        while not self._stop_event.wait(_POLL_SECONDS):
            try:
                current = snapshot_folder(folder)
                fresh = changed_paths(previous, current)

                # Stabilitetssjekk: skann først når fil er uendret én hel runde
                ready: list[str] = []
                for path in list(pending):
                    if current.get(path) == pending[path]:
                        ready.append(path)
                        del pending[path]
                    elif path in current:
                        pending[path] = current[path]   # fortsatt i endring
                    else:
                        del pending[path]               # forsvant (slettet/flyttet)

                for path in fresh:
                    if path not in ready:
                        pending[path] = current[path]

                previous = current

                for path in ready:
                    if self._stop_event.is_set():
                        return
                    try:
                        self._scan_one(path)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning("Mappeovervåking: skann feilet for %s: %s", path, exc)
            except Exception as exc:  # noqa: BLE001 — vakten skal aldri dø
                LOGGER.warning("Mappeovervåking: feil i runde: %s", exc)


class FolderWatchManager:
    """Holder opptil tre samtidige FolderWatcher-instanser."""

    def __init__(self, max_folders: int = _MAX_WATCHED_FOLDERS) -> None:
        self._lock = threading.Lock()
        self._watchers: dict[str, FolderWatcher] = {}
        self._max_folders = max_folders

    def start(self, folder: str, ignore_xlent: bool = False, language: str = "auto") -> dict[str, Any]:
        p = Path(folder)
        if not p.is_dir():
            return {"ok": False, "error": f"Ikke en mappe: {folder}"}
        key = str(p.resolve())
        with self._lock:
            if key not in self._watchers and len(self._watchers) >= self._max_folders:
                return {"ok": False, "error": f"Maks {_MAX_WATCHED_FOLDERS} mapper kan overvåkes samtidig."}
            watcher = self._watchers.get(key)
            if watcher is None:
                watcher = FolderWatcher()
                self._watchers[key] = watcher
        return watcher.start(key, ignore_xlent=ignore_xlent, language=language)

    def stop(self, folder: str | None = None) -> bool:
        with self._lock:
            if folder:
                key = str(Path(folder).resolve())
                watchers = [(key, self._watchers.get(key))]
            else:
                watchers = list(self._watchers.items())
        stopped = False
        for key, watcher in watchers:
            if watcher is None:
                continue
            stopped = watcher.stop() or stopped
            with self._lock:
                status = watcher.status()
                if not status.get("running"):
                    self._watchers.pop(key, None)
        return stopped

    def status(self) -> dict[str, Any]:
        folders = []
        recent_results = []
        scanned_count = 0
        with self._lock:
            items = list(self._watchers.items())
        for key, watcher in items:
            status = watcher.status()
            if not status.get("running"):
                with self._lock:
                    self._watchers.pop(key, None)
                continue
            folders.append({
                "folder": status.get("folder") or key,
                "started_at": status.get("started_at"),
                "scanned_count": status.get("scanned_count", 0),
            })
            scanned_count += int(status.get("scanned_count") or 0)
            recent_results.extend(status.get("recent_results") or [])
        recent_results.sort(key=lambda r: float(r.get("timestamp") or 0))
        del recent_results[:-_MAX_RESULTS]
        first_folder = folders[0]["folder"] if folders else None
        return {
            "running": bool(folders),
            "folder": first_folder,
            "folders": folders,
            "started_at": folders[0]["started_at"] if folders else None,
            "scanned_count": scanned_count,
            "recent_results": recent_results,
            "max_folders": self._max_folders,
        }


# Global singleton brukt av Flask-endepunktene
watcher = FolderWatchManager()
