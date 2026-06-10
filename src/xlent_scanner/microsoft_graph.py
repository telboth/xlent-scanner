"""Microsoft 365 / Graph-integrasjon for dokumentlabels og metadata.

Dette laget er bevisst valgfritt. Scanneren skal fungere 100 % lokalt uten
Graph-token. Når token er satt, kan brukeren koble en scan til en SharePoint /
OneDrive driveItem via drive_id + item_id.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GRAPH_BASE = os.environ.get("XLENT_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0").rstrip("/")
TOKEN_ENV_NAMES = ("XLENT_GRAPH_TOKEN", "MICROSOFT_GRAPH_TOKEN")
DRIVE_ID_ENV_NAMES = ("XLENT_GRAPH_DRIVE_ID", "MICROSOFT_GRAPH_DRIVE_ID")
SYNC_ROOT_ENV_NAMES = ("XLENT_GRAPH_SYNC_ROOT", "MICROSOFT_GRAPH_SYNC_ROOT")
ONEDRIVE_SYNC_ROOT_ENV_NAMES = ("OneDriveCommercial", "OneDrive")

RED_LABEL_KEYWORDS = tuple(
    value.strip().casefold()
    for value in os.environ.get(
        "XLENT_GRAPH_RED_LABEL_KEYWORDS",
        "confidential,konfidensiell,restricted,hemmelig,secret,highly confidential",
    ).split(",")
    if value.strip()
)


class GraphConfigError(RuntimeError):
    """Graph-integrasjonen er ikke konfigurert."""


class GraphRequestError(RuntimeError):
    """Microsoft Graph returnerte feil."""

    def __init__(self, method: str, url: str, status: int, body: str):
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        super().__init__(f"Graph {method} {url} feilet ({status}): {body[:500]}")


def graph_token() -> str:
    for name in TOKEN_ENV_NAMES:
        token = os.environ.get(name, "").strip()
        if token:
            return token
    raise GraphConfigError(f"Mangler Graph-token. Sett {TOKEN_ENV_NAMES[0]} eller {TOKEN_ENV_NAMES[1]}.")


def graph_status() -> dict[str, Any]:
    configured_env = next((name for name in TOKEN_ENV_NAMES if os.environ.get(name, "").strip()), "")
    drive_env = next((name for name in DRIVE_ID_ENV_NAMES if os.environ.get(name, "").strip()), "")
    return {
        "configured": bool(configured_env),
        "token_env": configured_env,
        "graph_base": GRAPH_BASE,
        "drive_id_configured": bool(drive_env),
        "drive_id_env": drive_env,
        "sync_roots": [str(path) for path in configured_sync_roots()],
        "red_label_keywords": list(RED_LABEL_KEYWORDS),
    }


def _graph_url(path: str) -> str:
    if path.startswith("https://"):
        return path
    return f"{GRAPH_BASE}/{path.lstrip('/')}"


def _graph_request(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    url = _graph_url(path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {graph_token()}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else {}
            if isinstance(payload, dict):
                payload.setdefault("_status", resp.status)
                location = resp.headers.get("Location")
                if location:
                    payload["_location"] = location
            return payload if isinstance(payload, dict) else {"value": payload, "_status": resp.status}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise GraphRequestError(method, url, exc.code, raw) from exc


def _drive_item_path(drive_id: str, item_id: str, suffix: str = "") -> str:
    drive = urllib.parse.quote(str(drive_id).strip(), safe="")
    item = urllib.parse.quote(str(item_id).strip(), safe="")
    return f"/drives/{drive}/items/{item}{suffix}"


def _drive_root_path(drive_id: str, item_path: str, suffix: str = "") -> str:
    drive = urllib.parse.quote(str(drive_id).strip(), safe="")
    encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in item_path.replace("\\", "/").split("/") if part)
    return f"/drives/{drive}/root:/{encoded_path}:{suffix}"


def configured_drive_id(drive_id: str | None = None) -> str:
    value = str(drive_id or "").strip()
    if value:
        return value
    for name in DRIVE_ID_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise GraphConfigError(f"Mangler driveId. Oppgi drive_id eller sett {DRIVE_ID_ENV_NAMES[0]}.")


def configured_sync_roots(sync_root: str | None = None) -> list[Path]:
    candidates: list[str] = []
    if sync_root:
        candidates.append(sync_root)
    for name in (*SYNC_ROOT_ENV_NAMES, *ONEDRIVE_SYNC_ROOT_ENV_NAMES):
        value = os.environ.get(name, "").strip()
        if value:
            candidates.append(value)

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            path = Path(candidate).expanduser().resolve()
        except OSError:
            path = Path(candidate).expanduser().absolute()
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            roots.append(path)
    return roots


def _relative_to_any_root(local_path: Path, roots: list[Path]) -> tuple[Path, Path]:
    try:
        resolved = local_path.expanduser().resolve()
    except OSError:
        resolved = local_path.expanduser().absolute()

    for root in roots:
        try:
            rel = resolved.relative_to(root)
            return root, rel
        except ValueError:
            continue
    root_text = ", ".join(str(root) for root in roots) or "(ingen)"
    raise GraphConfigError(f"Lokal fil er ikke under konfigurert sync-root. Fil: {resolved}. Sync-root: {root_text}.")


def resolve_local_drive_item(
    local_path: str | Path,
    drive_id: str | None = None,
    sync_root: str | None = None,
) -> dict[str, Any]:
    """Map en lokal OneDrive/SharePoint-synket fil til Graph driveItem.

    Dette krever at lokal sync-root og driveId peker til samme dokumentbibliotek.
    """
    drive = configured_drive_id(drive_id)
    roots = configured_sync_roots(sync_root)
    if not roots:
        raise GraphConfigError(f"Mangler sync-root. Oppgi sync_root eller sett {SYNC_ROOT_ENV_NAMES[0]}.")
    root, rel = _relative_to_any_root(Path(local_path), roots)
    item_path = "/".join(rel.parts)
    if not item_path:
        raise GraphConfigError("Lokal sti peker på sync-root, ikke en fil under sync-root.")
    item = _graph_request(
        "GET",
        _drive_root_path(drive, item_path, "?$select=id,name,webUrl,parentReference,sharepointIds"),
    )
    item_id = str(item.get("id") or "").strip()
    if not item_id:
        raise GraphRequestError("GET", _graph_url(_drive_root_path(drive, item_path)), 404, "Graph-respons manglet item id.")
    return {
        "drive_id": drive,
        "item_id": item_id,
        "sync_root": str(root),
        "relative_path": item_path,
        "item": item,
    }


def read_document_tags_for_local_path(
    local_path: str | Path,
    drive_id: str | None = None,
    sync_root: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_local_drive_item(local_path, drive_id=drive_id, sync_root=sync_root)
    tags = read_document_tags(resolved["drive_id"], resolved["item_id"])
    tags["resolved"] = resolved
    return tags


def _extract_label_names(raw: Any) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            keys = {k.casefold() for k in value}
            if {"name", "id"} & keys and any("label" in k for k in keys):
                labels.append(value)
            elif "sensitivitylabel" in keys or "sensitivitylabelid" in keys:
                nested = value.get("sensitivityLabel") or value.get("SensitivityLabel")
                labels.append(nested if isinstance(nested, dict) else value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(raw)
    # De-dupe på id/name for robuste, ulike Graph-responser.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for label in labels:
        key = str(label.get("id") or label.get("labelId") or label.get("name") or label).casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(label)
    return out


def read_document_tags(drive_id: str, item_id: str) -> dict[str, Any]:
    if not drive_id or not item_id:
        raise ValueError("drive_id og item_id må oppgis.")
    item = _graph_request("GET", _drive_item_path(drive_id, item_id, "?$select=id,name,webUrl,parentReference"))
    try:
        sensitivity_raw = _graph_request("POST", _drive_item_path(drive_id, item_id, "/extractSensitivityLabels"))
    except GraphRequestError as exc:
        sensitivity_raw = {"error": str(exc), "_status": exc.status}
    try:
        retention = _graph_request("GET", _drive_item_path(drive_id, item_id, "/retentionLabel"))
    except GraphRequestError as exc:
        retention = {"error": str(exc), "_status": exc.status}
    try:
        fields = _graph_request("GET", _drive_item_path(drive_id, item_id, "/listItem/fields"))
    except GraphRequestError as exc:
        fields = {"error": str(exc), "_status": exc.status}
    sensitivity_labels = _extract_label_names(sensitivity_raw)
    return {
        "drive_id": drive_id,
        "item_id": item_id,
        "item": item,
        "sensitivity": {
            "raw": sensitivity_raw,
            "labels": sensitivity_labels,
        },
        "retention": retention,
        "fields": fields,
        "policy_warning": policy_warning_for_tags({"sensitivity": {"labels": sensitivity_labels}, "retention": retention}),
    }


def assign_sensitivity_label(
    drive_id: str,
    item_id: str,
    sensitivity_label_id: str,
    assignment_method: str = "standard",
    justification_text: str = "Set by XLENT Scanner",
) -> dict[str, Any]:
    if not sensitivity_label_id:
        raise ValueError("sensitivity_label_id må oppgis.")
    body = {
        "sensitivityLabelId": sensitivity_label_id,
        "assignmentMethod": assignment_method or "standard",
        "justificationText": justification_text or "Set by XLENT Scanner",
    }
    return _graph_request("POST", _drive_item_path(drive_id, item_id, "/assignSensitivityLabel"), body)


def set_retention_label(drive_id: str, item_id: str, name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("Retention label-navn må oppgis.")
    return _graph_request("PATCH", _drive_item_path(drive_id, item_id, "/retentionLabel"), {"name": name})


def update_sharepoint_fields(drive_id: str, item_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if not fields:
        raise ValueError("Ingen SharePoint-felt oppgitt.")
    return _graph_request("PATCH", _drive_item_path(drive_id, item_id, "/listItem/fields"), fields)


def suggested_label_for_risk(risk_level: str) -> dict[str, str]:
    risk = (risk_level or "").casefold()
    if risk in {"svart", "rød"}:
        return {"name": "Highly Confidential", "reason": "Rød/svart risiko i XLENT Scanner"}
    if risk == "gul":
        return {"name": "Confidential", "reason": "Gule funn i XLENT Scanner"}
    return {"name": "Internal", "reason": "Ingen eller lav risiko i XLENT Scanner"}


def scan_metadata_fields(
    risk_level: str,
    finding_count: int,
    suggested_label: str,
    status: str = "Scanned",
) -> dict[str, Any]:
    return {
        "XLENTScanStatus": status,
        "XLENTRiskLevel": risk_level,
        "XLENTFindingCount": int(finding_count),
        "XLENTSuggestedLabel": suggested_label,
        "XLENTLastScanned": datetime.now(timezone.utc).isoformat(),
    }


def _label_text(label: dict[str, Any]) -> str:
    values = [
        label.get("name"),
        label.get("displayName"),
        label.get("labelName"),
        label.get("sensitivityLabelName"),
        label.get("id"),
        label.get("sensitivityLabelId"),
    ]
    return " ".join(str(v) for v in values if v).casefold()


def policy_warning_for_tags(tags: dict[str, Any]) -> str:
    labels = tags.get("sensitivity", {}).get("labels", []) if isinstance(tags.get("sensitivity"), dict) else []
    for label in labels:
        text = _label_text(label)
        if any(keyword in text for keyword in RED_LABEL_KEYWORDS):
            return "Microsoft 365-label tilsier konfidensielt dokument. Kontroller manuelt før deling."
    return ""
