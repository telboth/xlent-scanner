param(
    [string]$Owner = "telboth",
    [string]$RepoName = "",
    [string]$Version = "",
    [string]$Tag = "",
    [string]$ReleaseTitle = "",
    [string]$ReleaseNotes = "",
    [switch]$AutoCommit,
    [string]$CommitMessage = "chore: prepare release",
    [switch]$GenerateReleaseNotes = $true
)

$ErrorActionPreference = "Stop"
$FixedRemoteUrl = "https://github.com/telboth/xlent-scanner.git"
$Owner = "telboth"
$RepoName = "xlent-scanner"

function Invoke-Git {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git-kommando feilet: git $($Args -join ' ')"
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

function Test-ReleaseExists {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$RepoName,
        [string]$Tag
    )
    $uri = "https://api.github.com/repos/$Owner/$RepoName/releases/tags/$Tag"
    try {
        $existing = Invoke-RestMethod -Method GET -Uri $uri -Headers $Headers
        return $existing
    } catch {
        return $null
    }
}

Invoke-Git @("rev-parse", "--is-inside-work-tree") | Out-Null

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
    Invoke-Git @("add", "-A")
    & git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        Invoke-Git @("commit", "-m", $CommitMessage)
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
    Invoke-Git @("remote", "set-url", "origin", $FixedRemoteUrl)
} else {
    Invoke-Git @("remote", "add", "origin", $FixedRemoteUrl)
}

Invoke-Git @("push", "origin", $branch)

$localTag = (& git tag --list $Tag)
if ($LASTEXITCODE -ne 0) {
    throw "Kunne ikke lese git tags."
}
if (-not $localTag) {
    Invoke-Git @("tag", "-a", $Tag, "-m", "Release $Tag")
}

Invoke-Git @("push", "origin", $Tag)

$headers = Get-GitHubHeaders
Ensure-Owner -Headers $headers -Owner $Owner

$existingRelease = Test-ReleaseExists -Headers $headers -Owner $Owner -RepoName $RepoName -Tag $Tag
if ($existingRelease) {
    Write-Host "Release finnes allerede: $($existingRelease.html_url)"
    exit 0
}

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
