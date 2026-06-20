param(
    [string]$BtxRepo = "btxchain/btx",
    [string]$ReleaseTag = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $env:GITHUB_WORKSPACE "dist"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($ReleaseTag)) {
    $release = gh api "repos/$BtxRepo/releases/latest" | ConvertFrom-Json
} else {
    $release = gh api "repos/$BtxRepo/releases/tags/$ReleaseTag" | ConvertFrom-Json
}

$names = @("snapshot.dat", "snapshot.manifest.json")
foreach ($name in $names) {
    $asset = $release.assets | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $asset) {
        throw "Release $($release.tag_name) on $BtxRepo does not include $name"
    }
    $dest = Join-Path $OutputDir $name
    Write-Host "Downloading $name from $($release.tag_name)..."
    gh release download $release.tag_name --repo $BtxRepo --pattern $name --dir $OutputDir --clobber
    if (-not (Test-Path -LiteralPath $dest)) {
        throw "Failed to download $name"
    }
}

Write-Host "Snapshots ready in $OutputDir"