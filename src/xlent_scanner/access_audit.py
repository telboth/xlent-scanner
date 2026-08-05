"""Best-effort lokal tilgangssjekk for scan-rapporter.

Dette er med vilje konservativt: lokale ACL-er og POSIX-modus kan vise
brukere/grupper som har tilgang, men ekspanderer ikke grupper til faktisk
personantall.
"""
from __future__ import annotations

import platform
import stat
import subprocess
from pathlib import Path

_BROAD_IDENTITY_MARKERS = (
    "everyone",
    "alle",
    "authenticated users",
    "domain users",
    "builtin\\users",
    "\\users",
    "brukere",
)


def _is_broad_identity(identity: str) -> bool:
    lowered = identity.strip().lower()
    return any(marker in lowered for marker in _BROAD_IDENTITY_MARKERS)


def _parse_icacls_output(output: str, path: str = "") -> dict:
    entries: list[dict] = []
    path_text = str(path or "").strip()
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("successfully processed") or lowered.startswith("failed processing"):
            continue
        if path_text and line.startswith(path_text):
            line = line[len(path_text):].strip()
        if ":" not in line:
            continue
        identity, rights = line.split(":", 1)
        identity = identity.strip()
        rights = rights.strip()
        if not identity or not rights:
            continue
        entries.append({
            "identity": identity,
            "rights": rights,
            "inherited": "(I)" in rights,
            "broad": _is_broad_identity(identity),
        })

    broad_identities = sorted({entry["identity"] for entry in entries if entry["broad"]})
    return {
        "entries_total": len(entries),
        "direct_entries": sum(1 for entry in entries if not entry["inherited"]),
        "inherited_entries": sum(1 for entry in entries if entry["inherited"]),
        "broad_access": bool(broad_identities),
        "broad_identities": broad_identities,
        "entries": entries[:30],
        "truncated": len(entries) > 30,
    }


def _windows_access_audit(path: Path) -> dict:
    completed = subprocess.run(
        ["icacls", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "available": False,
            "ok": False,
            "source": "local_windows_acl",
            "reason": (completed.stderr or completed.stdout or "icacls feilet").strip(),
        }
    parsed = _parse_icacls_output(completed.stdout, str(path))
    return {
        "available": True,
        "ok": True,
        "source": "local_windows_acl",
        "path_type": "folder" if path.is_dir() else "file",
        "person_count_estimate": None,
        "person_count_note": "Ikke beregnet: lokale ACL-er inneholder ofte grupper som ikke ekspanderes til faktiske personer.",
        **parsed,
    }


def _posix_access_audit(path: Path) -> dict:
    st = path.stat()
    mode = stat.S_IMODE(st.st_mode)
    world_bits = mode & 0o007
    group_bits = mode & 0o070
    entries = [
        {"identity": f"owner:{st.st_uid}", "rights": stat.filemode(st.st_mode)[1:4], "inherited": False, "broad": False},
        {"identity": f"group:{st.st_gid}", "rights": stat.filemode(st.st_mode)[4:7], "inherited": False, "broad": bool(group_bits)},
        {"identity": "others", "rights": stat.filemode(st.st_mode)[7:10], "inherited": False, "broad": bool(world_bits)},
    ]
    broad_identities = [entry["identity"] for entry in entries if entry["broad"]]
    return {
        "available": True,
        "ok": True,
        "source": "local_posix_mode",
        "path_type": "folder" if path.is_dir() else "file",
        "entries_total": len(entries),
        "direct_entries": len(entries),
        "inherited_entries": 0,
        "broad_access": bool(group_bits or world_bits),
        "broad_identities": broad_identities,
        "person_count_estimate": None,
        "person_count_note": "Ikke beregnet: POSIX-modus viser eier/gruppe/andre, ikke faktisk personantall.",
        "mode_octal": oct(mode),
        "entries": entries,
        "truncated": False,
    }


def uploaded_copy_access_summary() -> dict:
    """Forklar hvorfor original tilgang ikke kan leses fra en opplastet kopi."""
    return {
        "available": False,
        "ok": False,
        "source": "uploaded_copy",
        "reason": (
            "Originalfilens tilgang kan ikke kontrolleres etter opplasting. "
            "Den midlertidige kopiens rettigheter rapporteres ikke fordi de ikke sier "
            "hvem som har tilgang til originalfilen. Bruk mappeskanning for en lokal tilgangssjekk."
        ),
    }


def audit_containing_folder_access(path: str | Path, cache: dict[str, dict]) -> dict:
    """Kontroller inneholdende mappe og gjenbruk resultatet for filer i samme mappe."""
    parent = Path(path).parent
    try:
        cache_key = str(parent.resolve())
    except OSError:
        cache_key = str(parent.absolute())
    if cache_key not in cache:
        cache[cache_key] = audit_path_access(parent)
    return {
        **cache[cache_key],
        "scope": "containing_folder",
        "scope_path": cache_key,
        "scope_note": (
            "Mappeskann: vurderingen gjelder rettighetene til filens inneholdende mappe. "
            "Filer i samme mappe gjenbruker denne kontrollen."
        ),
    }


def audit_path_access(path: str | Path) -> dict:
    """Returner JSON-serialiserbar tilgangsoversikt. Kaster ikke feil."""
    p = Path(path)
    try:
        if not p.exists():
            return {"available": False, "ok": False, "reason": f"Sti finnes ikke: {p}"}
        if platform.system().lower() == "windows":
            return _windows_access_audit(p)
        return _posix_access_audit(p)
    except subprocess.TimeoutExpired:
        return {"available": False, "ok": False, "reason": "Tilgangssjekk tidsavbrutt."}
    except (OSError, ValueError) as exc:
        return {"available": False, "ok": False, "reason": str(exc)}
