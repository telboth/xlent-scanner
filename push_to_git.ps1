param(
    [string]$Owner = "telboth",
    [string]$RepoName = "",
    [ValidateSet("public", "private")]
    [string]$Visibility = "public",
    [string]$CommitMessage = "chore: update project"
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
        Authorization         = "Basic $basic"
        Accept                = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
        "User-Agent"          = "push_to_git.ps1"
    }
}

function Ensure-GitHubRepo {
    param(
        [hashtable]$Headers,
        [string]$Owner,
        [string]$RepoName,
        [string]$Visibility
    )

    $me = Invoke-RestMethod -Method GET -Uri "https://api.github.com/user" -Headers $Headers
    if ($me.login -ne $Owner) {
        throw "Innlogget GitHub-bruker er '$($me.login)', ikke '$Owner'. Bytt owner eller credentials."
    }

    $repoUri = "https://api.github.com/repos/$Owner/$RepoName"
    $exists = $true
    try {
        Invoke-RestMethod -Method GET -Uri $repoUri -Headers $Headers | Out-Null
    } catch {
        $exists = $false
    }

    if (-not $exists) {
        $body = @{
            name   = $RepoName
            private = ($Visibility -eq "private")
        } | ConvertTo-Json

        Invoke-RestMethod -Method POST -Uri "https://api.github.com/user/repos" -Headers $Headers -Body $body | Out-Null
    }

    if ($Visibility -eq "public") {
        $patchBody = @{ private = $false } | ConvertTo-Json
        Invoke-RestMethod -Method PATCH -Uri $repoUri -Headers $Headers -Body $patchBody | Out-Null
    }
}

Invoke-Git -ArgList @("rev-parse", "--is-inside-work-tree") | Out-Null

$headers = Get-GitHubHeaders
Ensure-GitHubRepo -Headers $headers -Owner $Owner -RepoName $RepoName -Visibility $Visibility

Invoke-Git -ArgList @("add", "-A")
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    Invoke-Git -ArgList @("commit", "-m", $CommitMessage)
}

$branch = ((& git branch --show-current).Trim())
if ($LASTEXITCODE -ne 0) {
    throw "Kunne ikke lese aktiv branch."
}
if (-not $branch) {
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

Invoke-Git -ArgList @("push", "-u", "origin", $branch)
Write-Host "Push fullført: $FixedRemoteUrl ($branch)"
