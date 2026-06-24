"""Nedlasting og lagring av spaCy-språkmodeller for navnegjenkjenning (NER).

Modellene lagres i:  %APPDATA%\\xlent-scanner\\models\\{modell_navn}\\
og lastes via:       spacy.load(str(models_dir / modell_navn))

Bruker bare standardbibliotek — ingen ekstra avhengigheter utover spaCy.
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from xlent_scanner.language import SPACY_CONFIG
from xlent_scanner.paths import app_data_dir

# Modellversjoner som er kompatible med spaCy 3.8.x
_MODEL_VERSIONS: dict[str, str] = {
    "nb_core_news_sm": "3.8.0",
    "sv_core_news_sm": "3.8.0",
    "en_core_web_sm":  "3.8.0",
    "de_core_news_sm": "3.8.0",
    "fr_core_news_sm": "3.8.0",
    "es_core_news_sm": "3.8.0",
}

# Omtrentlig størrelse i MB (til visning i UI)
_MODEL_SIZE_MB: dict[str, int] = {
    "nb_core_news_sm": 15,
    "sv_core_news_sm": 90,
    "en_core_web_sm":  12,
    "de_core_news_sm": 15,
    "fr_core_news_sm": 16,
    "es_core_news_sm": 38,
}

_BASE_URL = "https://github.com/explosion/spacy-models/releases/download"

_progress_lock = threading.Lock()
_progress: dict[str, str] = {}
_active_downloads: set[str] = set()


# ── Hjelpefunksjoner ──────────────────────────────────────────────────────────

def _models_dir() -> Path:
    d = app_data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _set_progress(model_name: str, msg: str) -> None:
    with _progress_lock:
        _progress[model_name] = msg


def _safe_archive_target(root: Path, relative_path: str) -> Path:
    """Returner sikker destinasjon for et arkivmedlem under root."""
    relative = Path(relative_path)
    if relative.is_absolute():
        raise RuntimeError(f"Ugyldig absolutt sti i modellarkiv: {relative_path}")
    root_resolved = root.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError(f"Ugyldig sti i modellarkiv: {relative_path}") from exc
    return target


def _zipinfo_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


# ── Offentlig API ─────────────────────────────────────────────────────────────

def model_path(model_name: str) -> Path | None:
    """Returnerer path til modell om den er riktig installert, ellers None.

    En gyldig modell har config.cfg i rot-mappen.
    """
    p = _models_dir() / model_name
    if (p / "config.cfg").exists():
        return p
    return None


def models_status() -> list[dict]:
    """Returnerer statusliste for alle støttede spaCy-modeller.

    Deduplicerer på modellnavn — dersom to språk bruker samme modell
    (f.eks. dansk og norsk begge bruker nb_core_news_sm) vises modellen
    bare én gang (for det første språket i SPACY_CONFIG).
    """
    result = []
    seen_models: set[str] = set()
    for lang, cfg in SPACY_CONFIG.items():
        name = cfg["model"]
        if name in seen_models:
            continue   # Samme modell brukes av et annet språk allerede
        seen_models.add(name)
        path = model_path(name)
        with _progress_lock:
            progress_msg = _progress.get(name, "")
        result.append({
            "lang":      lang,
            "model":     name,
            "size_mb":   _MODEL_SIZE_MB.get(name, 0),
            "installed": path is not None,
            "path":      str(path) if path else None,
            "progress":  progress_msg,
        })
    return result


def download_model_async(model_name: str) -> bool:
    """Starter nedlasting av modell i en bakgrunnstråd.

    Returnerer False hvis nedlasting allerede pågår, True ellers.
    """
    if model_name not in _MODEL_VERSIONS:
        _set_progress(model_name, f"error:Ukjent modell: {model_name}")
        return False

    with _progress_lock:
        if model_name in _active_downloads:
            return False
        _active_downloads.add(model_name)
        _progress[model_name] = "Forbereder nedlasting…"

    try:
        t = threading.Thread(
            target=_download_model,
            args=(model_name,),
            daemon=True,
            name=f"model-dl-{model_name}",
        )
        t.start()
    except Exception:
        with _progress_lock:
            _active_downloads.discard(model_name)
            _progress[model_name] = "error:Klarte ikke å starte nedlasting"
        raise
    return True


# ── Intern nedlastingslogikk ──────────────────────────────────────────────────

def _download_model(model_name: str) -> None:
    """Laster ned og pakker ut en spaCy-modell (kjøres i bakgrunnstråd)."""
    version = _MODEL_VERSIONS.get(model_name)
    if not version:
        _set_progress(model_name, f"error:Ukjent modell: {model_name}")
        return

    url = (
        f"{_BASE_URL}/{model_name}-{version}"
        f"/{model_name}-{version}-py3-none-any.whl"
    )
    dest = _models_dir() / model_name
    dest_tmp = dest.parent / (dest.name + "_installing")
    dest_backup = dest.parent / (dest.name + "_previous")

    try:
        size_mb = _MODEL_SIZE_MB.get(model_name, 0)

        # ── Steg 1: Last ned til midlertidig fil ──────────────────────
        _set_progress(model_name, f"Laster ned {model_name} (~{size_mb} MB)… 0%")

        fd, tmp_path = tempfile.mkstemp(
            suffix=".whl", prefix=f"xlent-{model_name}-"
        )
        os.close(fd)
        tmp = Path(tmp_path)

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "xlent-scanner-model-downloader/1.0"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                chunk_size = 65536  # 64 KB
                with open(tmp_path, "wb") as fout:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        fout.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(99, int(downloaded / total * 100))
                        else:
                            pct = min(99, int(downloaded / max(1, size_mb * 1048576) * 100))
                        _set_progress(
                            model_name,
                            f"Laster ned {model_name} (~{size_mb} MB)… {pct}%",
                        )
        except urllib.error.URLError as exc:
            tmp.unlink(missing_ok=True)
            reason = getattr(exc, "reason", exc)
            _set_progress(model_name, f"error:Nettverksfeil: {reason}")
            return
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            _set_progress(model_name, f"error:Nedlasting feilet: {exc}")
            return

        # ── Steg 2: Pakk ut whl-arkivet ──────────────────────────────
        _set_progress(model_name, f"Pakker ut {model_name}…")

        # Rydd opp fra eventuell forrige mislykket installasjon
        if dest_tmp.exists():
            shutil.rmtree(dest_tmp, ignore_errors=True)
        dest_tmp.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(tmp, "r") as zf:
                # whl-strukturen er:
                #   nb_core_news_sm/__init__.py
                #   nb_core_news_sm/nb_core_news_sm-3.8.0/config.cfg
                #   nb_core_news_sm/nb_core_news_sm-3.8.0/meta.json  ...
                # Vi vil ha innholdet under nb_core_news_sm/{version}/ direkte i dest/

                prefix: str | None = None
                for info in zf.infolist():
                    parts = info.filename.split("/")
                    if (
                        len(parts) >= 2
                        and parts[0] == model_name
                        and parts[1].startswith(model_name + "-")
                        and parts[1] != parts[0]
                    ):
                        prefix = parts[0] + "/" + parts[1] + "/"
                        break

                if prefix is None:
                    shutil.rmtree(dest_tmp, ignore_errors=True)
                    _set_progress(
                        model_name,
                        "error:Fant ikke modelldata i nedlastet fil — prøv igjen",
                    )
                    return

                extracted = 0
                for info in zf.infolist():
                    member = info.filename
                    if not member.startswith(prefix) or member == prefix:
                        continue
                    rel = member[len(prefix):]
                    if not rel:
                        continue
                    if _zipinfo_is_symlink(info):
                        raise RuntimeError(f"Symbolsk lenke er ikke tillatt i modellarkiv: {rel}")
                    target = _safe_archive_target(dest_tmp, rel)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src:
                            target.write_bytes(src.read())
                        extracted += 1

                if extracted == 0:
                    shutil.rmtree(dest_tmp, ignore_errors=True)
                    _set_progress(model_name, "error:Ingen filer ble pakket ut")
                    return
                missing = [
                    name for name in ("config.cfg", "meta.json")
                    if not (dest_tmp / name).is_file()
                ]
                if missing:
                    raise RuntimeError(
                        "Modellarkivet mangler obligatoriske filer: "
                        + ", ".join(missing)
                    )

        except zipfile.BadZipFile:
            shutil.rmtree(dest_tmp, ignore_errors=True)
            _set_progress(model_name, "error:Nedlastet fil er korrupt — prøv igjen")
            return
        except Exception as exc:
            shutil.rmtree(dest_tmp, ignore_errors=True)
            _set_progress(model_name, f"error:Utpakking feilet: {exc}")
            return
        finally:
            tmp.unlink(missing_ok=True)

        # ── Steg 3: Atomisk bytte ─────────────────────────────────────
        if dest_backup.exists():
            if dest.exists():
                shutil.rmtree(dest_backup, ignore_errors=True)
            else:
                dest_backup.rename(dest)
        if dest.exists():
            dest.rename(dest_backup)
        try:
            dest_tmp.rename(dest)
        except Exception:
            if dest_backup.exists() and not dest.exists():
                dest_backup.rename(dest)
            raise
        if dest_backup.exists():
            shutil.rmtree(dest_backup, ignore_errors=True)

        # ── Steg 4: Tøm NER-cache ─────────────────────────────────────
        # Lazy import for å unngå sirkulær avhengighet
        try:
            from xlent_scanner.detectors import ner_names  # noqa: PLC0415
            ner_names.reset_cache_for_model(model_name)
        except Exception:
            pass

        _set_progress(model_name, "done")

    except Exception as exc:
        if dest_tmp.exists():
            shutil.rmtree(dest_tmp, ignore_errors=True)
        _set_progress(model_name, f"error:{exc}")
    finally:
        with _progress_lock:
            _active_downloads.discard(model_name)
