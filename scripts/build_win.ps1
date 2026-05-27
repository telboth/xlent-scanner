param(
    [string]$PythonExe = "",
    [string]$OutputRoot = "artifacts\windows\app",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Mangler kommando '$Name' i PATH."
    }
}

function Invoke-External {
    param(
        [string]$Exe,
        [string[]]$Args
    )
    & $Exe @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Kommando feilet: $Exe $($Args -join ' ')"
    }
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not $PythonExe) {
    $candidate = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $candidate)) {
        throw "Fant ikke python i .venv. Kjør 'uv sync' først, eller oppgi -PythonExe."
    }
    $PythonExe = $candidate
}

if (-not (Test-Path $PythonExe)) {
    throw "Ugyldig PythonExe: $PythonExe"
}

Assert-Command "uv"

$OutRootAbs = Join-Path $RepoRoot $OutputRoot
$BuildDir = Join-Path $OutRootAbs "build"
$DistDir = Join-Path $OutRootAbs "dist"
$SpecDir = Join-Path $OutRootAbs "spec"
$EntryScript = Join-Path $BuildDir "entrypoint_build.py"
$AppName = "XLENTScanner"

if ($Clean -and (Test-Path $OutRootAbs)) {
    Remove-Item -LiteralPath $OutRootAbs -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $BuildDir, $DistDir, $SpecDir | Out-Null

@'
from xlent_scanner.app import main

if __name__ == "__main__":
    main()
'@ | Set-Content -LiteralPath $EntryScript -Encoding UTF8

Invoke-External "uv" @(
    "pip", "install",
    "--python", $PythonExe,
    "pyinstaller>=6.0.0",
    "pyinstaller-hooks-contrib>=2024.0"
)

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $AppName,
    "--paths", (Join-Path $RepoRoot "src"),
    "--collect-data", "xlent_scanner",
    "--hidden-import", "webview.platforms.winforms",
    "--hidden-import", "webview.platforms.edgechromium",
    "--distpath", $DistDir,
    "--workpath", $BuildDir,
    "--specpath", $SpecDir,
    $EntryScript
)

Invoke-External $PythonExe $pyiArgs

$OutputDir = Join-Path $DistDir $AppName
if (-not (Test-Path $OutputDir)) {
    throw "Fant ikke forventet build-output: $OutputDir"
}

Write-Host "Build fullført: $OutputDir"
