param(
    [string]$InnoCompilerPath = "",
    [string]$BuildOutputDir = "artifacts\windows\app\dist\XLENTScanner",
    [string]$InstallerOutputDir = "artifacts\windows\installer",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

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

function Resolve-InnoCompiler {
    param([string]$ExplicitPath)
    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) {
            throw "Fant ikke ISCC.exe på: $ExplicitPath"
        }
        return (Resolve-Path $ExplicitPath).Path
    }

    $candidates = @(
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )

    foreach ($p in $candidates) {
        if (Test-Path $p) {
            return $p
        }
    }

    $fromPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    throw "Fant ikke Inno Setup compiler (ISCC.exe). Installer Inno Setup 6."
}

function Get-VersionFromCode {
    param([string]$RepoRoot)
    $initPath = Join-Path $RepoRoot "src\xlent_scanner\__init__.py"
    if (-not (Test-Path $initPath)) {
        throw "Fant ikke versjonsfil: $initPath"
    }
    $content = Get-Content -LiteralPath $initPath -Raw
    $m = [regex]::Match($content, '__version__\s*=\s*"([^"]+)"')
    if (-not $m.Success) {
        throw "Fant ikke __version__ i $initPath"
    }
    return $m.Groups[1].Value
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not $Version) {
    $Version = Get-VersionFromCode -RepoRoot $RepoRoot
}

$BuildOutputAbs = Join-Path $RepoRoot $BuildOutputDir
if (-not (Test-Path $BuildOutputAbs)) {
    throw "Build-output mangler: $BuildOutputAbs. Kjør scripts\\build_win.ps1 først."
}

$InstallerOutAbs = Join-Path $RepoRoot $InstallerOutputDir
New-Item -ItemType Directory -Force -Path $InstallerOutAbs | Out-Null

$IssPath = Join-Path $RepoRoot "installer\windows\xlent_scanner.iss"
if (-not (Test-Path $IssPath)) {
    throw "Fant ikke Inno Setup-script: $IssPath"
}

$iscc = Resolve-InnoCompiler -ExplicitPath $InnoCompilerPath

$args = @(
    "/DAppVersion=$Version",
    "/DSourceDir=$BuildOutputAbs",
    "/DOutputDir=$InstallerOutAbs",
    $IssPath
)

Invoke-External $iscc $args

Write-Host "Installer bygget i: $InstallerOutAbs"
