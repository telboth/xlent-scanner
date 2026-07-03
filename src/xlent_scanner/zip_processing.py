"""Sikker ZIP-utpakking for batch-skann.

ZIP behandles som en midlertidig mappe. Denne modulen gjør kun validering,
utpakking og opptelling; scanning/redaction gjenbruker eksisterende mappeflyt.
"""
from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from xlent_scanner.scanner import SUPPORTED_SUFFIXES

ZIP_SUFFIXES = {".zip"}
DEFAULT_ZIP_MAX_FILES = 1000
DEFAULT_ZIP_MAX_TOTAL_BYTES = 250 * 1024 * 1024
DEFAULT_ZIP_MAX_MEMBER_BYTES = 100 * 1024 * 1024
DEFAULT_ZIP_CLEANUP_AGE_SECONDS = 24 * 60 * 60
ZIP_LARGE_FILE_COUNT = 100
ZIP_LARGE_TOTAL_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class ZipExtractResult:
    root: Path
    total_files: int
    supported_files: int
    ignored_files: int
    total_uncompressed_bytes: int
    skipped: list[dict] = field(default_factory=list)


def cleanup_old_zip_temp_dirs(
    *,
    temp_root: str | Path | None = None,
    max_age_seconds: int = DEFAULT_ZIP_CLEANUP_AGE_SECONDS,
    now: float | None = None,
) -> int:
    """Slett gamle ZIP-tempmapper laget av appen.

    Vi sletter kun mapper med prefikset ``xlent-zip-`` og bare når de er eldre
    enn terskelen. Aktive batchjobber får dermed beholde kildefilene sine.
    """
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    cutoff = (time.time() if now is None else now) - max_age_seconds
    removed = 0
    if not root.exists():
        return 0
    for path in root.glob("xlent-zip-*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _safe_member_path(root: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/").lstrip("/")
    if not normalized or normalized.endswith("/"):
        raise ValueError("Mappe eller tomt ZIP-medlemsnavn.")
    target = (root / normalized).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"Usikker sti i ZIP: {member_name}")
    return target


def extract_zip_to_temp(
    zip_path: str | Path,
    *,
    max_files: int = DEFAULT_ZIP_MAX_FILES,
    max_total_bytes: int = DEFAULT_ZIP_MAX_TOTAL_BYTES,
    max_member_bytes: int = DEFAULT_ZIP_MAX_MEMBER_BYTES,
) -> ZipExtractResult:
    """Pakk ut ZIP til temp-mappe og returner metadata.

    Caller eier temp-mappen og må slette den når jobben ikke lenger trengs.
    """
    cleanup_old_zip_temp_dirs()
    source = Path(zip_path)
    if source.suffix.lower() not in ZIP_SUFFIXES:
        raise ValueError("Ikke en ZIP-fil.")
    if not zipfile.is_zipfile(source):
        raise ValueError("Filen er ikke en gyldig ZIP-fil.")

    root = Path(tempfile.mkdtemp(prefix="xlent-zip-"))
    total_files = 0
    supported_files = 0
    ignored_files = 0
    total_uncompressed = 0
    skipped: list[dict] = []

    try:
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                total_files += 1
                if total_files > max_files:
                    skipped.append({"file": info.filename, "reason": "Maks antall filer i ZIP er nådd."})
                    ignored_files += 1
                    continue
                if info.file_size > max_member_bytes:
                    skipped.append({"file": info.filename, "reason": "Filen er større enn maks enkeltfilstørrelse."})
                    ignored_files += 1
                    continue
                if total_uncompressed + info.file_size > max_total_bytes:
                    skipped.append({"file": info.filename, "reason": "Maks total ZIP-størrelse er nådd."})
                    ignored_files += 1
                    continue

                target = _safe_member_path(root, info.filename)
                total_uncompressed += info.file_size
                if target.suffix.lower() in SUPPORTED_SUFFIXES:
                    supported_files += 1
                else:
                    ignored_files += 1
                    skipped.append({"file": info.filename, "reason": "Filtypen støttes ikke."})

                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

        return ZipExtractResult(
            root=root,
            total_files=total_files,
            supported_files=supported_files,
            ignored_files=ignored_files,
            total_uncompressed_bytes=total_uncompressed,
            skipped=skipped,
        )
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
