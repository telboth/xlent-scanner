"""Best-effort lokal tilgangssjekk for scan-rapporter.

Dette er med vilje konservativt: lokale ACL-er og POSIX-modus kan vise
brukere/grupper som har tilgang, men ekspanderer ikke grupper til faktisk
personantall.
"""
from __future__ import annotations

import platform
import re
import stat
import subprocess
from pathlib import Path

_PUBLIC_IDENTITY_MARKERS = (
    "everyone",
    "alle",
    "world",
    "s-1-1-0",
)

_SHARED_IDENTITY_MARKERS = (
    "authenticated users",
    "domain users",
    "builtin\\users",
    "brukere",
)

_ACCESS_RIGHT_TOKENS = {
    "F", "M", "RX", "R", "W", "D", "RD", "WD", "AD", "REA", "WEA",
    "RA", "WA", "DC", "DE", "RC", "WDAC", "WO", "GA", "GR", "GW", "GX",
}


def _identity_scope(identity: str) -> str:
    lowered = identity.strip().lower()
    if any(marker == lowered or lowered.endswith(f"\\{marker}") for marker in _PUBLIC_IDENTITY_MARKERS):
        return "public"
    if any(marker in lowered for marker in _SHARED_IDENTITY_MARKERS) or lowered.endswith("\\users"):
        return "shared_local"
    return "specific"


def _permission_effect(rights: str) -> str:
    return "deny" if "(DENY)" in rights.upper() else "allow"


def _grants_access(rights: str) -> bool:
    if _permission_effect(rights) == "deny":
        return False
    tokens = {token.upper() for token in re.findall(r"\(([^)]+)\)", rights)}
    return bool(tokens & _ACCESS_RIGHT_TOKENS)


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
        scope = _identity_scope(identity)
        effect = _permission_effect(rights)
        grants_access = _grants_access(rights)
        entries.append({
            "identity": identity,
            "rights": rights,
            "inherited": "(I)" in rights,
            "effect": effect,
            "grants_access": grants_access,
            "identity_scope": scope,
            "broad": scope == "public" and grants_access,
            "shared": scope == "shared_local" and grants_access,
        })

    broad_identities = sorted({entry["identity"] for entry in entries if entry["broad"]})
    shared_identities = sorted({entry["identity"] for entry in entries if entry["shared"]})
    denied_identities = sorted({entry["identity"] for entry in entries if entry["effect"] == "deny"})
    access_level = "broad" if broad_identities else "shared_local" if shared_identities else "restricted"
    return {
        "entries_total": len(entries),
        "direct_entries": sum(1 for entry in entries if not entry["inherited"]),
        "inherited_entries": sum(1 for entry in entries if entry["inherited"]),
        "broad_access": bool(broad_identities),
        "broad_identities": broad_identities,
        "shared_local_access": bool(shared_identities),
        "shared_identities": shared_identities,
        "denied_identities": denied_identities,
        "access_level": access_level,
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
        {"identity": f"owner:{st.st_uid}", "rights": stat.filemode(st.st_mode)[1:4], "inherited": False, "effect": "allow", "grants_access": bool(mode & 0o700), "identity_scope": "specific", "broad": False, "shared": False},
        {"identity": f"group:{st.st_gid}", "rights": stat.filemode(st.st_mode)[4:7], "inherited": False, "effect": "allow", "grants_access": bool(group_bits), "identity_scope": "shared_local", "broad": False, "shared": bool(group_bits)},
        {"identity": "others", "rights": stat.filemode(st.st_mode)[7:10], "inherited": False, "effect": "allow", "grants_access": bool(world_bits), "identity_scope": "public", "broad": bool(world_bits), "shared": False},
    ]
    broad_identities = [entry["identity"] for entry in entries if entry["broad"]]
    shared_identities = [entry["identity"] for entry in entries if entry["shared"]]
    return {
        "available": True,
        "ok": True,
        "source": "local_posix_mode",
        "path_type": "folder" if path.is_dir() else "file",
        "entries_total": len(entries),
        "direct_entries": len(entries),
        "inherited_entries": 0,
        "broad_access": bool(world_bits),
        "broad_identities": broad_identities,
        "shared_local_access": bool(group_bits),
        "shared_identities": shared_identities,
        "denied_identities": [],
        "access_level": "broad" if world_bits else "shared_local" if group_bits else "restricted",
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
