from __future__ import annotations

from xlent_scanner import app as app_module
from xlent_scanner.app_state import AppState


def test_app_uses_explicit_state_and_expected_blueprints():
    assert isinstance(app_module.app_state, AppState)
    assert {
        "background",
        "diagnostics",
        "folders",
        "microsoft",
        "ollama",
        "api",
        "reports",
        "scanning",
        "settings",
    }.issubset(app_module.flask_app.blueprints)


def test_no_duplicate_route_and_method_pairs():
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []

    for rule in app_module.flask_app.url_map.iter_rules():
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            key = (rule.rule, method)
            if key in seen:
                duplicates.append(key)
            seen.add(key)

    assert duplicates == []


def test_app_only_keeps_core_routes_directly_registered():
    direct_rules = {
        rule.rule
        for rule in app_module.flask_app.url_map.iter_rules()
        if rule.endpoint.startswith("index")
        or rule.endpoint in {"startup_file", "logo_svg"}
    }

    assert direct_rules == {"/", "/startup-file", "/logo.svg"}


def test_scan_categories_endpoint_exposes_backend_category_order():
    client = app_module.flask_app.test_client()

    response = client.get("/scan-categories")

    assert response.status_code == 200
    data = response.get_json()
    assert [item["key"] for item in data["categories"][:5]] == [
        "navn",
        "epost",
        "telefon",
        "id",
        "klient",
    ]
    assert data["profiles"]["lowfp"] == [
        "id",
        "konto",
        "hemmeligheter",
        "konfidensielt",
        "orgnummer",
    ]


def test_legacy_scan_category_keys_map_to_merged_categories():
    from xlent_scanner.scan_categories import normalise_scan_categories

    assert normalise_scan_categories(["fodselsdato", "kredittkort"]) == frozenset({"id", "konto"})


def test_open_in_browser_endpoint_opens_current_local_url(monkeypatch):
    opened = []
    monkeypatch.setattr(app_module.app_state, "port", 51291)
    monkeypatch.setattr(app_module.webbrowser, "open", lambda url: opened.append(url) or True)

    response = app_module.flask_app.test_client().post("/open-in-browser")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "url": "http://127.0.0.1:51291"}
    assert opened == ["http://127.0.0.1:51291"]
