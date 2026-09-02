import pytest

from xlent_scanner import audit_trail


@pytest.fixture(autouse=True)
def isolate_audit_storage(monkeypatch, tmp_path):
    """Tester skal aldri skrive audit-hendelser til brukerens virkelige appdata."""
    monkeypatch.setattr(audit_trail, "app_data_dir", lambda: tmp_path / "audit")
