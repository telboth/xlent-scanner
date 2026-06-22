from __future__ import annotations

from pathlib import Path

from scripts import release_gate


def test_release_gate_validates_windows_artifact_and_script(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    installer = tmp_path / "artifacts" / "windows" / "installer"
    installer.mkdir(parents=True)
    (installer / "xlent-scanner-setup-1.0.0.exe").write_bytes(b"exe")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "install_windows.ps1").write_text("Write-Host ok", encoding="utf-8")

    release_gate.main_args = None
    monkeypatch.setattr("sys.argv", ["release_gate.py", "--platform", "windows"])
    release_gate.main()


def test_release_gate_fails_when_artifact_missing(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["release_gate.py", "--platform", "linux"])

    try:
        release_gate.main()
    except RuntimeError as exc:
        assert "Expected exactly one match" in str(exc)
    else:
        raise AssertionError("release gate accepted missing artifact")
