# Start XLENT Scanner – Streamlit-frontend
# Kjøres fra streamlit_app-mappen: .\start.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv er ikke installert. Se https://docs.astral.sh/uv/"
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Setter opp venv..."
    uv sync
}

Write-Host "Starter XLENT Scanner på http://localhost:8501"
uv run streamlit run app.py
