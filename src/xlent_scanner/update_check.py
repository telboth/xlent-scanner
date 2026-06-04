"""Månedlig versjonssjekk mot GitHub Releases."""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from xlent_scanner.paths import app_data_dir

GITHUB_OWNER = "telboth"
GITHUB_REPO = "xlent-scanner"
CHECK_INTERVAL_DAYS = 30
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


def _state_path() -> Path:
    return app_data_dir() / "update_check.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(data: dict[str, Any]) -> None:
    _state_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_version(v: str) -> tuple[int, ...]:
    raw = (v or "").strip().lower()
    if raw.startswith("v"):
        raw = raw[1:]
    raw = raw.split("+", 1)[0].split("-", 1)[0]
    parts = raw.split(".")
    out: list[int] = []
    for part in parts:
        m = re.match(r"(\d+)", part)
        if not m:
            break
        out.append(int(m.group(1)))
    if not out:
        return (0,)
    while len(out) > 1 and out[-1] == 0:
        out.pop()
    return tuple(out)


def _is_newer(latest: str, current: str) -> bool:
    a = list(_normalize_version(latest))
    b = list(_normalize_version(current))
    max_len = max(len(a), len(b))
    a.extend([0] * (max_len - len(a)))
    b.extend([0] * (max_len - len(b)))
    return tuple(a) > tuple(b)


def _platform_installer_suffixes() -> list[str]:
    plat = sys.platform
    if plat.startswith("win"):
        return [".exe", ".msi", ".zip"]
    if plat == "darwin":
        return [".dmg", ".pkg", ".zip"]
    return [".appimage", ".deb", ".rpm", ".tar.gz", ".zip"]


def _pick_installer_asset(assets: list[dict[str, Any]]) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name and url:
            candidates.append((name, url))

    if not candidates:
        return "", ""

    suffixes = _platform_installer_suffixes()
    for suffix in suffixes:
        for name, url in candidates:
            if name.lower().endswith(suffix):
                return name, url

    return candidates[0]


def _platform_install_script_name() -> str:
    plat = sys.platform
    if plat.startswith("win"):
        return "install_windows.ps1"
    if plat == "darwin":
        return "install_macos.sh"
    return ""


def _pick_install_script_asset(assets: list[dict[str, Any]]) -> tuple[str, str]:
    expected_name = _platform_install_script_name()
    if not expected_name:
        return "", ""

    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name == expected_name and url:
            return name, url
    return "", ""


def _fetch_latest_release_payload(timeout: int = 3) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "xlent-scanner-update-check",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_latest_release() -> dict[str, str]:
    payload = _fetch_latest_release_payload()

    latest = payload.get("tag_name") or payload.get("name") or ""
    release_url = payload.get("html_url") or RELEASES_URL
    installer_name, installer_url = _pick_installer_asset(payload.get("assets") or [])
    if not latest:
        raise RuntimeError("Fant ikke gyldig versjon i GitHub release.")
    return {
        "latest_version": str(latest),
        "release_url": str(release_url),
        "installer_url": str(installer_url or release_url),
        "installer_name": str(installer_name),
    }


def fetch_platform_install_script() -> dict[str, str]:
    """Finn installasjonsscriptet som passer denne plattformen i latest release."""
    expected_name = _platform_install_script_name()
    if not expected_name:
        raise RuntimeError("Automatisk installasjonsscript støttes bare på Windows og macOS.")

    payload = _fetch_latest_release_payload(timeout=10)
    latest = payload.get("tag_name") or payload.get("name") or ""
    release_url = payload.get("html_url") or RELEASES_URL
    script_name, script_url = _pick_install_script_asset(payload.get("assets") or [])
    if not latest:
        raise RuntimeError("Fant ikke gyldig versjon i GitHub release.")
    if not script_url:
        raise RuntimeError(f"Fant ikke {expected_name} i latest release.")
    return {
        "latest_version": str(latest),
        "release_url": str(release_url),
        "script_name": script_name,
        "script_url": script_url,
    }


def _fetch_latest_tag() -> dict[str, str]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/tags?per_page=1"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "xlent-scanner-update-check",
        },
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload:
        raise RuntimeError("Fant ingen Git-tags i repo.")
    latest = payload[0].get("name") or ""
    if not latest:
        raise RuntimeError("Fant ikke gyldig versjon i Git-tags.")
    return {
        "latest_version": str(latest),
        "release_url": RELEASES_URL,
        "installer_url": RELEASES_URL,
        "installer_name": "",
    }


def check_for_update(current_version: str, force: bool = False) -> dict[str, Any]:
    now = _utc_now()
    state = _load_state()

    last_checked = _parse_iso(state.get("last_checked_at"))
    next_check_at = (
        (last_checked + timedelta(days=CHECK_INTERVAL_DAYS))
        if last_checked
        else now
    )

    if not force and last_checked and now < next_check_at:
        cached_latest = state.get("latest_version", current_version)
        return {
            "ok": True,
            "checked_now": False,
            "current_version": current_version,
            "latest_version": cached_latest,
            "release_url": state.get(
                "release_url",
                RELEASES_URL,
            ),
            "installer_url": state.get("installer_url", state.get("release_url", RELEASES_URL)),
            "installer_name": state.get("installer_name", ""),
            # Re-evaluer alltid mot gjeldende versjon – cachen kan være utdatert
            # hvis brukeren har oppgradert siden siste nettsjekk.
            "update_available": _is_newer(cached_latest, current_version),
            "last_checked_at": _to_iso(last_checked),
            "next_check_at": _to_iso(next_check_at),
        }

    try:
        try:
            latest = _fetch_latest_release()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                latest = _fetch_latest_tag()
            else:
                raise
        latest_version = latest["latest_version"]
        release_url = latest["release_url"]
        installer_url = latest.get("installer_url", release_url)
        installer_name = latest.get("installer_name", "")
        update_available = _is_newer(latest_version, current_version)

        new_state = {
            "last_checked_at": _to_iso(now),
            "latest_version": latest_version,
            "release_url": release_url,
            "installer_url": installer_url,
            "installer_name": installer_name,
            "update_available": update_available,
        }
        _save_state(new_state)

        return {
            "ok": True,
            "checked_now": True,
            "current_version": current_version,
            "latest_version": latest_version,
            "release_url": release_url,
            "installer_url": installer_url,
            "installer_name": installer_name,
            "update_available": update_available,
            "last_checked_at": new_state["last_checked_at"],
            "next_check_at": _to_iso(now + timedelta(days=CHECK_INTERVAL_DAYS)),
        }
    except RuntimeError as exc:
        if "ingen git-tags" in str(exc).lower():
            new_state = {
                "last_checked_at": _to_iso(now),
                "latest_version": current_version,
                "release_url": RELEASES_URL,
                "installer_url": RELEASES_URL,
                "installer_name": "",
                "update_available": False,
            }
            _save_state(new_state)
            return {
                "ok": True,
                "checked_now": True,
                "current_version": current_version,
                "latest_version": current_version,
                "release_url": new_state["release_url"],
                "installer_url": new_state["installer_url"],
                "installer_name": "",
                "update_available": False,
                "last_checked_at": new_state["last_checked_at"],
                "next_check_at": _to_iso(now + timedelta(days=CHECK_INTERVAL_DAYS)),
            }
        _cached_latest = state.get("latest_version", current_version)
        return {
            "ok": False,
            "checked_now": True,
            "current_version": current_version,
            "latest_version": _cached_latest,
            "release_url": state.get(
                "release_url",
                RELEASES_URL,
            ),
            "installer_url": state.get("installer_url", state.get("release_url", RELEASES_URL)),
            "installer_name": state.get("installer_name", ""),
            # Re-evaluer alltid – aldri bruk den cachede update_available-verdien direkte
            "update_available": _is_newer(_cached_latest, current_version),
            "last_checked_at": state.get("last_checked_at", ""),
            "next_check_at": state.get("next_check_at", ""),
            "error": str(exc),
        }
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        _cached_latest = state.get("latest_version", current_version)
        return {
            "ok": False,
            "checked_now": True,
            "current_version": current_version,
            "latest_version": _cached_latest,
            "release_url": state.get(
                "release_url",
                RELEASES_URL,
            ),
            "installer_url": state.get("installer_url", state.get("release_url", RELEASES_URL)),
            "installer_name": state.get("installer_name", ""),
            # Re-evaluer alltid – aldri bruk den cachede update_available-verdien direkte
            "update_available": _is_newer(_cached_latest, current_version),
            "last_checked_at": state.get("last_checked_at", ""),
            "next_check_at": state.get("next_check_at", ""),
            "error": str(exc),
        }
