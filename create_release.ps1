param(
    [string]$Owner = "telboth",
    [string]$RepoName = "",
    [string]$Version = "",
    [string]$Tag = "",
    [string]$ReleaseTitle = "",
    [string]$ReleaseNotes = "",
    [switch]$AutoCommit,
    [string]$CommitMessage = "chore: prepare release",
    [switch]$GenerateReleaseNotes = $true,
    [switch]$UploadAssets = $true,
    [switch]$OverwriteAssets = $true,
    [string[]]$AssetGlobs = @(
        "artifacts/windows/installer/*",
        "artifacts/macos/installer/*",
        "scripts/install_windows.ps1",
        "scripts/install_macos.sh"
    )
)

$ErrorActionPreference = "Stop"
$FixedRemoteUrl = "https://github.com/telboth/xlent-scanner.git"
$Owner = "telboth"
$RepoName = "xlent-scanner"

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$ArgList
    )
    & git @ArgList
    if ($LASTEXITCODE -ne 0) {
        throw "git-kommando feilet: git $($ArgList -join ' ')"
    }
}

function Get-GitHubHeaders {
    $credRequest = "protocol=https`nhost=github.com`n`n"
    $raw = $credRequest | git credential fill 2>$null
    if (-not $raw) {
        throw "Fant ingen GitHub-credentials via 'git credential fill'."
    }

    $kv = @{}
    foreach ($line in ($raw -split "`r?`n")) {
        if ($line -match "=") {
            $parts = $line.Split("=", 2)
            $kv[$parts[0]] = $parts[1]
        }
    }

    if (-not $kv.ContainsKey("username") -or -not $kv.ContainsKey("password")) {
        throw "Ufullstendige GitHub-credentials (mangler username/password)."
    }

    $basic = [Convert]::ToBase64String(
        [Text.Encoding]::ASCII.GetBytes("$($kv['username']):$($kv['password'])")
    )

    return @{
        Authorization          = "Basic $basic"
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent"           = "create_release.ps1"
    }
}

function Get-VersionFromCode {
    $initPath = Join-Path (Get-Location) "src\xlent_scanner\__init__.py"
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

function Ensure-Owner {
    param(
        [hashtable]$Headers,
        [string]$Owner
    )
    $me = Invoke-RestMethod -Method GET -Uri "https://api.github.com/user" -Headers $Headers
    if ($me.login -ne $Owner) {
        throw "Innlogget GitHub-bruker er '$($me.login)', ikke '$Owner'."
    }
}

function Get-ReleaseByTag {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$RepoName,
        [string]$Tag
    )
    $uri = "https://api.github.com/repos/$Owner/$RepoName/releases/tags/$Tag"
    try {
        return Invoke-RestMethod -Method GET -Uri $uri -Headers $Headers
    } catch {
        return $null
    }
}

function Get-ContentTypeForFile {
    param([string]$Path)
    $ext = [IO.Path]::GetExtension($Path).ToLowerInvariant()
    switch ($ext) {
        ".dmg" { return "application/x-apple-diskimage" }
        ".pkg" { return "application/octet-stream" }
        ".zip" { return "application/zip" }
        ".exe" { return "application/vnd.microsoft.portable-executable" }
        ".msi" { return "application/x-msi" }
        default { return "application/octet-stream" }
    }
}

function Resolve-AssetFiles {
    param(
        [string]$RepoRoot,
        [string[]]$Globs
    )
    $result = New-Object System.Collections.Generic.List[string]
    foreach ($pattern in $Globs) {
        $fullPattern = Join-Path $RepoRoot $pattern
        $parent = Split-Path -Path $fullPattern -Parent
        $leaf = Split-Path -Path $fullPattern -Leaf
        if (-not (Test-Path $parent)) {
            continue
        }
        $files = Get-ChildItem -Path $parent -Filter $leaf -File -ErrorAction SilentlyContinue
        foreach ($f in $files) {
            $result.Add($f.FullName)
        }
    }
    return $result | Sort-Object -Unique
}

function Filter-AssetsForVersion {
    param(
        [string[]]$Files,
        [string]$Version
    )

    if (-not $Version) {
        return $Files
    }

    $versionToken = "-$Version"
    $filtered = New-Object System.Collections.Generic.List[string]
    foreach ($f in $Files) {
        $name = [IO.Path]::GetFileName($f)
        # Keep installer assets only when they match current version.
        # Keep helper scripts regardless of version.
        if (
            ($name -like "xlent-scanner-setup-*.exe") -or
            ($name -like "xlent-scanner-macos-*.dmg") -or
            ($name -like "xlent-scanner-macos-*.pkg")
        ) {
            if ($name.Contains($versionToken)) {
                $filtered.Add($f)
            }
            continue
        }
        $filtered.Add($f)
    }

    return $filtered | Sort-Object -Unique
}

function Remove-ReleaseAssetIfExists {
    param(
        [hashtable]$Headers,
        [object]$Release,
        [string]$AssetName
    )
    $existing = $Release.assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
    if (-not $existing) {
        return
    }
    $deleteUrl = "https://api.github.com/repos/$Owner/$RepoName/releases/assets/$($existing.id)"
    Invoke-RestMethod -Method DELETE -Uri $deleteUrl -Headers $Headers | Out-Null
}

function Upload-ReleaseAsset {
    param(
        [hashtable]$Headers,
        [object]$Release,
        [string]$FilePath
    )
    $fileName = [IO.Path]::GetFileName($FilePath)
    $uploadTemplate = [string]$Release.upload_url
    $baseUploadUrl = $uploadTemplate.Split("{")[0].Trim()
    if (-not $baseUploadUrl) {
        throw "Ugyldig upload_url i release-data: '$uploadTemplate'"
    }
    $uploadUrl = "{0}?name={1}" -f $baseUploadUrl, [uri]::EscapeDataString($fileName)
    $contentType = Get-ContentTypeForFile -Path $FilePath
    Invoke-RestMethod `
        -Method POST `
        -Uri $uploadUrl `
        -Headers @{ Authorization = $Headers.Authorization; "User-Agent" = $Headers["User-Agent"] } `
        -ContentType $contentType `
        -InFile $FilePath | Out-Null
}

$RepoRoot = Resolve-Path (Get-Location)
Invoke-Git -ArgList @("rev-parse", "--is-inside-work-tree") | Out-Null

if (-not $Version) {
    $Version = Get-VersionFromCode
}
if (-not $Tag) {
    $Tag = "v$Version"
}
if (-not $ReleaseTitle) {
    $ReleaseTitle = $Tag
}

$statusLines = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Kunne ikke lese git status."
}
if ($statusLines -and -not $AutoCommit) {
    throw "Arbeidstreet er ikke rent. Kjør med -AutoCommit eller commit manuelt."
}
if ($statusLines -and $AutoCommit) {
    Invoke-Git -ArgList @("add", "-u")
    & git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        Invoke-Git -ArgList @("commit", "-m", $CommitMessage)
    }
}

$branch = ((& git branch --show-current).Trim())
if ($LASTEXITCODE -ne 0 -or -not $branch) {
    throw "Fant ingen aktiv branch."
}

if ((& git remote) -contains "origin") {
    if ($LASTEXITCODE -ne 0) {
        throw "Kunne ikke lese git remotes."
    }
    Invoke-Git -ArgList @("remote", "set-url", "origin", $FixedRemoteUrl)
} else {
    Invoke-Git -ArgList @("remote", "add", "origin", $FixedRemoteUrl)
}

Invoke-Git -ArgList @("push", "origin", $branch)

$localTag = (& git tag --list $Tag)
if ($LASTEXITCODE -ne 0) {
    throw "Kunne ikke lese git tags."
}
if (-not $localTag) {
    Invoke-Git -ArgList @("tag", "-a", $Tag, "-m", "Release $Tag")
}

Invoke-Git -ArgList @("push", "origin", $Tag)

$headers = Get-GitHubHeaders
Ensure-Owner -Headers $headers -Owner $Owner

$release = Get-ReleaseByTag -Headers $headers -Owner $Owner -RepoName $RepoName -Tag $Tag
if (-not $release) {
    $payload = @{
        tag_name = $Tag
        target_commitish = $branch
        name = $ReleaseTitle
        draft = $false
        prerelease = $false
    }

    if ($GenerateReleaseNotes) {
        $payload["generate_release_notes"] = $true
    }
    if ($ReleaseNotes) {
        $payload["body"] = $ReleaseNotes
    }

    $release = Invoke-RestMethod `
        -Method POST `
        -Uri "https://api.github.com/repos/$Owner/$RepoName/releases" `
        -Headers $headers `
        -Body ($payload | ConvertTo-Json -Depth 10)

    Write-Host "Release opprettet: $($release.html_url)"
} else {
    Write-Host "Release finnes allerede: $($release.html_url)"
}

if ($UploadAssets) {
    $assetFiles = Resolve-AssetFiles -RepoRoot $RepoRoot -Globs $AssetGlobs
    $assetFiles = Filter-AssetsForVersion -Files $assetFiles -Version $Version
    if (-not $assetFiles -or $assetFiles.Count -eq 0) {
        Write-Host "Ingen release-assets funnet for globs: $($AssetGlobs -join ', ')"
    } else {
        foreach ($assetPath in $assetFiles) {
            $assetName = [IO.Path]::GetFileName($assetPath)
            if ($OverwriteAssets) {
                Remove-ReleaseAssetIfExists -Headers $headers -Release $release -AssetName $assetName
                $release = Get-ReleaseByTag -Headers $headers -Owner $Owner -RepoName $RepoName -Tag $Tag
            }
            Upload-ReleaseAsset -Headers $headers -Release $release -FilePath $assetPath
            Write-Host "Asset lastet opp: $assetName"
            $release = Get-ReleaseByTag -Headers $headers -Owner $Owner -RepoName $RepoName -Tag $Tag
        }
    }
}
