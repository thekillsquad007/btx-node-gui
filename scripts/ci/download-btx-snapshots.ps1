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
    $encoded = [uri]::EscapeDataString($ReleaseTag)
    $release = gh api "repos/$BtxRepo/releases/tags/$encoded" | ConvertFrom-Json
}

$tag = $release.tag_name
$names = @("snapshot.dat", "snapshot.manifest.json")
$assetMap = @{}
foreach ($asset in $release.assets) {
    $assetMap[$asset.name] = $asset
}

foreach ($name in $names) {
    if (-not $assetMap.ContainsKey($name)) {
        throw "Release $tag on $BtxRepo does not include $name"
    }
}

Write-Host "Downloading snapshots from $BtxRepo release $tag ..."
gh release download $tag --repo $BtxRepo --pattern "snapshot.dat" --pattern "snapshot.manifest.json" --dir $OutputDir --clobber
if ($LASTEXITCODE -ne 0) {
    throw "gh release download failed for $BtxRepo $tag"
}

foreach ($name in $names) {
    $dest = Join-Path $OutputDir $name
    if (-not (Test-Path -LiteralPath $dest)) {
        throw "Expected file missing after download: $dest"
    }
    $sizeMb = [math]::Round((Get-Item -LiteralPath $dest).Length / 1MB, 1)
    Write-Host "  $name ($sizeMb MB)"
}

Write-Host "Snapshots ready in $OutputDir"