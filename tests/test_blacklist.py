from xlent_scanner.blacklist import detect_blacklist, save_blacklist_entries
from xlent_scanner.scanner import scan_text
from xlent_scanner.whitelist import save_whitelist_entries


def test_blacklist_detects_terms_case_insensitive(monkeypatch, tmp_path):
    monkeypatch.setattr("xlent_scanner.blacklist.app_data_dir", lambda: tmp_path)
    save_blacklist_entries(["Project Raven"])

    findings = detect_blacklist("Dette gjelder project raven og skal fjernes.")

    assert len(findings) == 1
    assert findings[0].category == "Blacklist"
    assert findings[0].text == "project raven"
    assert findings[0].severity == "rød"


def test_blacklist_overrides_whitelist_in_scan(monkeypatch, tmp_path):
    monkeypatch.setattr("xlent_scanner.blacklist.app_data_dir", lambda: tmp_path)
    monkeypatch.setattr("xlent_scanner.whitelist.app_data_dir", lambda: tmp_path)
    save_whitelist_entries(["Project Raven"])
    save_blacklist_entries(["Project Raven"])

    result = scan_text("Project Raven skal ikke deles.", language="en")

    matches = [f for f in result.findings if f.category == "Blacklist"]
    assert len(matches) == 1
    assert matches[0].severity == "rød"
    assert result.risk_level == "rød"
