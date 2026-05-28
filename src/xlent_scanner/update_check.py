"""Månedlig versjonssjekk mot GitHub Releases."""
from __future__ import annotations

import json
import os
import platform
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

GITHUB_OWNER = "telboth"
GITHUB_REPO = "xlent-scanner"
CHECK_INTERVAL_DAYS = 30


def _state_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / "Library" / "Application Support"
    d = base / "xlent-scanner"
    d.mkdir(parents=True, exist_ok=True)
    return d / "update_check.json"


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


def _fetch_latest_release() -> dict[str, str]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "xlent-scanner-update-check",
        },
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    latest = payload.get("tag_name") or payload.get("name") or ""
    release_url = payload.get("html_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    if not latest:
        raise RuntimeError("Fant ikke gyldig versjon i GitHub release.")
    return {"latest_version": str(latest), "release_url": str(release_url)}


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
        "release_url": f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases",
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
                f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases",
            ),
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
        update_available = _is_newer(latest_version, current_version)

        new_state = {
            "last_checked_at": _to_iso(now),
            "latest_version": latest_version,
            "release_url": release_url,
            "update_available": update_available,
        }
        _save_state(new_state)

        return {
            "ok": True,
            "checked_now": True,
            "current_version": current_version,
            "latest_version": latest_version,
            "release_url": release_url,
            "update_available": update_available,
            "last_checked_at": new_state["last_checked_at"],
            "next_check_at": _to_iso(now + timedelta(days=CHECK_INTERVAL_DAYS)),
        }
    except RuntimeError as exc:
        if "ingen git-tags" in str(exc).lower():
            new_state = {
                "last_checked_at": _to_iso(now),
                "latest_version": current_version,
                "release_url": f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases",
                "update_available": False,
            }
            _save_state(new_state)
            return {
                "ok": True,
                "checked_now": True,
                "current_version": current_version,
                "latest_version": current_version,
                "release_url": new_state["release_url"],
                "update_available": False,
                "last_checked_at": new_state["last_checked_at"],
                "next_check_at": _to_iso(now + timedelta(days=CHECK_INTERVAL_DAYS)),
            }
        return {
            "ok": False,
            "checked_now": True,
            "current_version": current_version,
            "latest_version": state.get("latest_version", current_version),
            "release_url": state.get(
                "release_url",
                f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases",
            ),
            "update_available": bool(state.get("update_available", False)),
            "last_checked_at": state.get("last_checked_at", ""),
            "next_check_at": state.get("next_check_at", ""),
            "error": str(exc),
        }
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        return {
            "ok": False,
            "checked_now": True,
            "current_version": current_version,
            "latest_version": state.get("latest_version", current_version),
            "release_url": state.get(
                "release_url",
                f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases",
            ),
            "update_available": bool(state.get("update_available", False)),
            "last_checked_at": state.get("last_checked_at", ""),
            "next_check_at": state.get("next_check_at", ""),
            "error": str(exc),
        }
