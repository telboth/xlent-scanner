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
        [object[]]$ArgList = @()
    )
    & $Exe @ArgList
    if ($LASTEXITCODE -ne 0) {
        throw "Kommando feilet: $Exe $($ArgList -join ' ')"
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

Invoke-External -Exe "uv" -ArgList @(
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

    # Data-filer: web-grensesnitt + langdetect-profiler
    "--collect-data", "xlent_scanner",
    "--collect-data", "langdetect",
    "--collect-data", "docx",
    "--collect-data", "pptx",

    # Docling (PDF-parsing med layout-analyse og tabellgjenkjenning)
    "--collect-all", "docling",
    "--collect-all", "docling_core",
    "--collect-all", "docling_parse",
    "--collect-data", "docling_ibm_models",

    # PyWebView Windows-backend (dynamisk importert – usynlig for PyInstaller)
    "--hidden-import", "webview.platforms.winforms",
    "--hidden-import", "webview.platforms.edgechromium",

    # Dokumentlesere – lazy-importert inne i funksjoner i scanner.py / patch.py.
    # PyInstaller utfører kun statisk analyse og ser IKKE disse importene.
    "--hidden-import", "docx",
    "--hidden-import", "docx.oxml",
    "--hidden-import", "docx.oxml.ns",
    "--hidden-import", "docx.enum.text",
    "--hidden-import", "docx.shared",
    "--hidden-import", "pptx",
    "--hidden-import", "pptx.util",
    "--hidden-import", "pptx.enum",
    "--hidden-import", "pptx.enum.text",
    "--hidden-import", "pptx.dml.color",
    "--hidden-import", "openpyxl",
    "--hidden-import", "openpyxl.styles",
    "--hidden-import", "openpyxl.utils",
    "--hidden-import", "openpyxl.utils.exceptions",

    # Språkdeteksjon
    "--hidden-import", "langdetect",
    "--hidden-import", "langdetect.detector",
    "--hidden-import", "langdetect.detector_factory",
    "--hidden-import", "langdetect.language",
    "--hidden-import", "langdetect.utils.lang_detect_exception",
    "--hidden-import", "langdetect.utils.unicode_block",

    # PDF-bibliotek
    "--hidden-import", "fitz",

    # Modellnedlasting og dybdeskann (lazy-importert)
    "--hidden-import", "xlent_scanner.model_manager",
    "--hidden-import", "xlent_scanner.deep_scanner",
    # spaCy (NER – selve modellene installeres separat av bruker)
    "--hidden-import", "spacy",
    "--hidden-import", "spacy.lang.nb",
    "--hidden-import", "spacy.lang.sv",
    "--hidden-import", "spacy.lang.en",
    "--hidden-import", "spacy.lang.de",
    "--hidden-import", "spacy.lang.fr",
    "--hidden-import", "spacy.lang.es",
    "--hidden-import", "spacy.lang.da",

    # Ekskluder pakker som ikke er i bruk
    "--exclude-module", "torchvision",

    "--distpath", $DistDir,
    "--workpath", $BuildDir,
    "--specpath", $SpecDir,
    $EntryScript
)

Invoke-External -Exe $PythonExe -ArgList $pyiArgs

$OutputDir = Join-Path $DistDir $AppName
if (-not (Test-Path $OutputDir)) {
    throw "Fant ikke forventet build-output: $OutputDir"
}

Write-Host "Build fullført: $OutputDir"
