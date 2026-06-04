param(
    [string]$Owner = "telboth",
    [string]$RepoName = "xlent-scanner",
    [string]$Tag = "",
    [string]$AssetPattern = "xlent-scanner-setup-*.exe",
    [string]$DownloadDir = "$env:TEMP\xlent-scanner-install",
    [switch]$Silent
)

$ErrorActionPreference = "Stop"

if ([Net.ServicePointManager]::SecurityProtocol -notmatch "Tls12") {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}

function Get-ReleaseInfo {
    param(
        [string]$Owner,
        [string]$RepoName,
        [string]$Tag
    )

    if ($Tag) {
        $url = "https://api.github.com/repos/$Owner/$RepoName/releases/tags/$Tag"
    } else {
        $url = "https://api.github.com/repos/$Owner/$RepoName/releases/latest"
    }

    return Invoke-RestMethod -Method GET -Uri $url -Headers @{ "User-Agent" = "xlent-scanner-install" }
}

function Resolve-InstallerAsset {
    param(
        [object]$ReleaseInfo,
        [string]$Pattern
    )

    $asset = $ReleaseInfo.assets | Where-Object { $_.name -like $Pattern } | Select-Object -First 1
    if (-not $asset) {
        throw "Fant ingen installer-asset som matcher '$Pattern' i release '$($ReleaseInfo.tag_name)'."
    }
    return $asset
}

$release = Get-ReleaseInfo -Owner $Owner -RepoName $RepoName -Tag $Tag
$asset = Resolve-InstallerAsset -ReleaseInfo $release -Pattern $AssetPattern

New-Item -ItemType Directory -Path $DownloadDir -Force | Out-Null
$installerPath = Join-Path $DownloadDir $asset.name

Write-Host "Laster ned $($asset.name) fra $($release.tag_name)..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installerPath
Unblock-File -Path $installerPath -ErrorAction SilentlyContinue

$args = @()
if ($Silent) {
    $args = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
}

Write-Host "Starter installasjon..."
$process = Start-Process -FilePath $installerPath -ArgumentList $args -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "Installer feilet med exit-kode $($process.ExitCode). Installer brukt: $installerPath"
}

Write-Host "Ferdig. Installer brukt: $installerPath"
