from xlent_scanner import app as app_module
from xlent_scanner.models import Finding
from xlent_scanner.whitelist import (
    category_allows_whitelist,
    filter_by_whitelist,
    get_whitelist_entries,
    mark_whitelist_findings,
    save_whitelist_entries,
)


def test_budget_project_sum_and_birth_date_categories_cannot_be_whitelisted(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("xlent_scanner.whitelist.app_data_dir", lambda: tmp_path)
    save_whitelist_entries(["4,5 MNOK", "01.02.1980", "1200000"])

    findings = [
        Finding(category="prosjektsum", text="4,5 MNOK", severity="gul"),
        Finding(category="fødselsdato", text="01.02.1980", severity="gul"),
        Finding(category="🤖 Budsjettall", text="1200000", severity="gul"),
    ]

    marked = mark_whitelist_findings(findings)
    filtered = filter_by_whitelist(findings)

    assert [finding.severity for finding in marked] == ["gul", "gul", "gul"]
    assert filtered == findings


def test_normal_categories_can_still_be_whitelisted(monkeypatch, tmp_path):
    monkeypatch.setattr("xlent_scanner.whitelist.app_data_dir", lambda: tmp_path)
    save_whitelist_entries(["safe@example.com"])

    findings = [Finding(category="e-post", text="safe@example.com", severity="gul")]

    assert mark_whitelist_findings(findings)[0].severity == "grønn"
    assert filter_by_whitelist(findings) == []


def test_category_allows_whitelist_normalises_ai_prefix():
    assert not category_allows_whitelist("🤖 Budsjettall")
    assert not category_allows_whitelist("prosjektsum")
    assert not category_allows_whitelist("fødselsdato")
    assert category_allows_whitelist("🤖 Selskapsnavn")


def test_add_to_whitelist_endpoint_rejects_blocked_category(monkeypatch, tmp_path):
    monkeypatch.setattr("xlent_scanner.whitelist.app_data_dir", lambda: tmp_path)

    client = app_module.flask_app.test_client()
    response = client.post(
        "/add-to-whitelist",
        json={"text": "1200000", "category": "🤖 Budsjettall"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is False
    assert data["error_code"] == "whitelistCategoryBlocked"
    assert get_whitelist_entries() == []


def test_add_to_whitelist_endpoint_accepts_allowed_category(monkeypatch, tmp_path):
    monkeypatch.setattr("xlent_scanner.whitelist.app_data_dir", lambda: tmp_path)

    client = app_module.flask_app.test_client()
    response = client.post(
        "/add-to-whitelist",
        json={"text": "Shearwater", "category": "🤖 Selskapsnavn"},
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert get_whitelist_entries() == ["Shearwater"]
