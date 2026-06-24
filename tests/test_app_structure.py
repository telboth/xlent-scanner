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
