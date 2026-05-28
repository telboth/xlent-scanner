"""Nedlasting og lagring av spaCy-språkmodeller for navnegjenkjenning (NER).

Modellene lagres i:  %APPDATA%\\xlent-scanner\\models\\{modell_navn}\\
og lastes via:       spacy.load(str(models_dir / modell_navn))

Bruker bare standardbibliotek — ingen ekstra avhengigheter utover spaCy.
"""
from __future__ import annotations

import os
import platform
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from xlent_scanner.language import SPACY_CONFIG

# Modellversjoner som er kompatible med spaCy 3.8.x
_MODEL_VERSIONS: dict[str, str] = {
    "nb_core_news_sm": "3.8.0",
    "sv_core_news_sm": "3.8.0",
    "en_core_web_sm":  "3.8.0",
}

# Omtrentlig størrelse i MB (til visning i UI)
_MODEL_SIZE_MB: dict[str, int] = {
    "nb_core_news_sm": 15,
    "sv_core_news_sm": 90,
    "en_core_web_sm":  12,
}

_BASE_URL = "https://github.com/explosion/spacy-models/releases/download"

_progress_lock = threading.Lock()
_progress: dict[str, str] = {}


# ── Hjelpefunksjoner ──────────────────────────────────────────────────────────

def _models_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / "Library" / "Application Support"
    d = base / "xlent-scanner" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _set_progress(model_name: str, msg: str) -> None:
    with _progress_lock:
        _progress[model_name] = msg


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
    with _progress_lock:
        current = _progress.get(model_name, "")
    # Ikke start en ny nedlasting om en allerede pågår
    if current and not current.startswith("error") and current not in ("done", ""):
        return False

    _set_progress(model_name, "Forbereder nedlasting…")
    t = threading.Thread(
        target=_download_model,
        args=(model_name,),
        daemon=True,
        name=f"model-dl-{model_name}",
    )
    t.start()
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
                for name in zf.namelist():
                    parts = name.split("/")
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
                for member in zf.namelist():
                    if not member.startswith(prefix) or member == prefix:
                        continue
                    rel = member[len(prefix):]
                    if not rel:
                        continue
                    target = dest_tmp / rel
                    if member.endswith("/"):
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src:
                            target.write_bytes(src.read())
                        extracted += 1

                if extracted == 0:
                    shutil.rmtree(dest_tmp, ignore_errors=True)
                    _set_progress(model_name, "error:Ingen filer ble pakket ut")
                    return

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
        if dest.exists():
            shutil.rmtree(dest)
        dest_tmp.rename(dest)

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
