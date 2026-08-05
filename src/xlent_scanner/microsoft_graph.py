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


def detect_cloud_sync_context(
    local_path: str | Path,
    sync_root: str | None = None,
) -> dict[str, Any] | None:
    """Finn Microsoft 365-synkkontekst uten å lese filinnhold eller kontakte Graph."""
    roots = configured_sync_roots(sync_root)
    if not roots:
        return None
    try:
        root, rel = _relative_to_any_root(Path(local_path), roots)
    except GraphConfigError:
        return None
    relative_path = "/".join(rel.parts)
    first_part = rel.parts[0].casefold() if rel.parts else ""
    return {
        "provider": "microsoft_365",
        "sync_root": str(root),
        "relative_path": relative_path,
        "shortcut_candidate": first_part in {"shortcuts", "snarveier"},
    }


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
        _drive_root_path(drive, item_path, "?$select=id,name,webUrl,parentReference,sharepointIds,remoteItem"),
    )
    remote = item.get("remoteItem") if isinstance(item.get("remoteItem"), dict) else {}
    remote_parent = remote.get("parentReference") if isinstance(remote.get("parentReference"), dict) else {}
    effective_drive = str(remote_parent.get("driveId") or drive).strip()
    item_id = str(remote.get("id") or item.get("id") or "").strip()
    if not item_id:
        raise GraphRequestError("GET", _graph_url(_drive_root_path(drive, item_path)), 404, "Graph-respons manglet item id.")
    return {
        "drive_id": effective_drive,
        "item_id": item_id,
        "source_drive_id": drive,
        "shortcut_resolved": bool(remote),
        "sync_root": str(root),
        "relative_path": item_path,
        "item": item,
    }


def read_drive_item_permissions(drive_id: str, item_id: str) -> dict[str, Any]:
    """Les alle tilgjengelige tillatelsessider for et driveItem."""
    path = _drive_item_path(drive_id, item_id, "/permissions")
    values: list[dict[str, Any]] = []
    pages = 0
    while path and pages < 20:
        page = _graph_request("GET", path)
        values.extend(value for value in page.get("value", []) if isinstance(value, dict))
        path = str(page.get("@odata.nextLink") or "")
        pages += 1
    return {"value": values, "pages": pages}


def _permission_identity(permission: dict[str, Any]) -> tuple[str, str] | None:
    containers: list[dict[str, Any]] = []
    for key in ("grantedToV2", "grantedTo"):
        value = permission.get(key)
        if isinstance(value, dict):
            containers.append(value)
    for key in ("grantedToIdentitiesV2", "grantedToIdentities"):
        value = permission.get(key)
        if isinstance(value, list):
            containers.extend(item for item in value if isinstance(item, dict))
    invitation = permission.get("invitation")
    if isinstance(invitation, dict) and invitation.get("email"):
        return "person", str(invitation["email"])
    for container in containers:
        for kind in ("user", "group", "siteUser", "siteGroup", "application"):
            identity = container.get(kind)
            if not isinstance(identity, dict):
                continue
            name = str(identity.get("displayName") or identity.get("email") or identity.get("id") or "").strip()
            if name:
                return ("group" if "group" in kind.casefold() else "person"), name
    return None


def summarise_sharepoint_permissions(payload: dict[str, Any]) -> dict[str, Any]:
    """Normaliser Graph permissions til en liten, stabil rapportmodell."""
    permissions = [value for value in payload.get("value", []) if isinstance(value, dict)]
    entries: list[dict[str, Any]] = []
    people: set[str] = set()
    groups: set[str] = set()
    public_link = False
    organization_access = False
    for permission in permissions:
        link = permission.get("link") if isinstance(permission.get("link"), dict) else {}
        link_scope = str(link.get("scope") or "").casefold()
        public_link = public_link or link_scope == "anonymous"
        organization_access = organization_access or link_scope == "organization"
        identity = _permission_identity(permission)
        if identity:
            (groups if identity[0] == "group" else people).add(identity[1])
        entries.append({
            "id": str(permission.get("id") or ""),
            "roles": [str(role) for role in permission.get("roles", [])],
            "link_scope": link_scope,
            "identity_type": identity[0] if identity else "",
            "identity": identity[1] if identity else "",
            "inherited": isinstance(permission.get("inheritedFrom"), dict),
        })
    level = (
        "public" if public_link else
        "organization" if organization_access else
        "group" if groups else
        "specific" if people else
        "restricted"
    )
    inherited = sum(1 for entry in entries if entry["inherited"])
    return {
        "available": True,
        "ok": True,
        "source": "sharepoint_graph",
        "access_level": level,
        "public_link": public_link,
        "organization_access": organization_access,
        "group_identities": sorted(groups),
        "person_identities": sorted(people),
        "entries_total": len(entries),
        "direct_entries": len(entries) - inherited,
        "inherited_entries": inherited,
        "entries": entries[:30],
        "truncated": len(entries) > 30,
        "person_count_estimate": None,
        "person_count_note": (
            "Ikke beregnet: SharePoint-grupper er ikke ekspandert. Graph kan dessuten vise "
            "bare tillatelser som gjelder innlogget bruker dersom brukeren ikke er eier."
        ),
    }


def sharepoint_access_for_local_path(
    local_path: str | Path,
    drive_id: str | None = None,
    sync_root: str | None = None,
    cache: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any] | None:
    """Returner SharePoint-tilgang for en synkronisert sti, ellers ``None``."""
    context = detect_cloud_sync_context(local_path, sync_root=sync_root)
    if context is None:
        return None
    cache_key = f"{context['sync_root']}|{context['relative_path']}|{drive_id or ''}".casefold()
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    try:
        token = graph_token()
        drive = configured_drive_id(drive_id)
        del token
        resolved = resolve_local_drive_item(local_path, drive_id=drive, sync_root=context["sync_root"])
        summary = summarise_sharepoint_permissions(
            read_drive_item_permissions(resolved["drive_id"], resolved["item_id"])
        )
        summary.update({
            "scope": "sharepoint_item",
            "scope_path": context["relative_path"],
            "sync_root": context["sync_root"],
            "shortcut_resolved": resolved["shortcut_resolved"],
            "web_url": str((resolved.get("item") or {}).get("webUrl") or ""),
        })
    except (GraphConfigError, GraphRequestError, OSError, ValueError) as exc:
        summary = {
            "available": False,
            "ok": False,
            "source": "sharepoint_graph",
            "access_level": "not_checked",
            "reason": f"SharePoint-tilgang er ikke kontrollert: {exc}",
            "scope": "sharepoint_item",
            "scope_path": context["relative_path"],
            "sync_root": context["sync_root"],
            "shortcut_candidate": context["shortcut_candidate"],
        }
    if cache is not None:
        cache[cache_key] = summary
    return summary


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
