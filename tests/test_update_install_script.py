from pathlib import Path

import xlent_scanner.update_check as update_check


def test_platform_install_script_asset_is_selected_by_exact_name(monkeypatch) -> None:
    assets = [
        {"name": "install_macos.sh", "browser_download_url": "https://github.com/telboth/xlent-scanner/releases/download/v1/install_macos.sh"},
        {"name": "install_windows.ps1", "browser_download_url": "https://github.com/telboth/xlent-scanner/releases/download/v1/install_windows.ps1"},
        {"name": "install_windows.ps1.txt", "browser_download_url": "https://github.com/telboth/xlent-scanner/releases/download/v1/bad.txt"},
    ]

    monkeypatch.setattr(update_check.sys, "platform", "win32")
    assert update_check._pick_install_script_asset(assets) == (
        "install_windows.ps1",
        "https://github.com/telboth/xlent-scanner/releases/download/v1/install_windows.ps1",
    )

    monkeypatch.setattr(update_check.sys, "platform", "darwin")
    assert update_check._pick_install_script_asset(assets) == (
        "install_macos.sh",
        "https://github.com/telboth/xlent-scanner/releases/download/v1/install_macos.sh",
    )


def test_update_install_script_backend_runs_without_shell_eval() -> None:
    app = Path("src/xlent_scanner/app.py").read_text(encoding="utf-8")
    diagnostics = Path("src/xlent_scanner/routes/diagnostics.py").read_text(encoding="utf-8")

    assert '@bp.post("/updates/install-script/run")' in diagnostics
    assert "fetch_platform_install_script()" in diagnostics
    assert 'name not in {"install_windows.ps1", "install_macos.sh"}' in app
    assert 'parsed.scheme != "https" or not parsed.netloc.endswith("github.com")' in app
    assert '"powershell.exe",' in app
    assert '"-ExecutionPolicy",' in app
    assert '"Bypass",' in app
    assert '"osascript",' in app
    assert 'tell application "Terminal" to do script' in app
    assert "shell=True" not in app
    assert "shell=True" not in diagnostics
