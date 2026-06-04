from pathlib import Path


def test_windows_installer_script_downloads_latest_release_asset() -> None:
    script = Path("scripts/install_windows.ps1").read_text(encoding="utf-8")

    assert "https://api.github.com/repos/$Owner/$RepoName/releases/latest" in script
    assert 'xlent-scanner-setup-*.exe' in script
    assert "Invoke-WebRequest" in script
    assert "Unblock-File" in script
    assert "Start-Process" in script
    assert "PassThru = $true" in script
    assert "ExitCode" in script
    assert "$startParams" in script
    assert "ArgumentList = $args" in script
    assert "Start-Process @startParams" in script


def test_github_release_uploads_windows_install_script() -> None:
    workflow = Path(".github/workflows/build-release.yml").read_text(encoding="utf-8")

    assert "scripts/install_windows.ps1" in workflow
