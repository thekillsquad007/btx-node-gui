param(
    [Parameter(Mandatory = $true)]
    [string]$BtxSourceDir
)

$ErrorActionPreference = "Stop"
$manifestPath = Join-Path $BtxSourceDir "vcpkg.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Missing vcpkg.json in $BtxSourceDir"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$defaults = @($manifest.'default-features')
if ($defaults -contains "qt5") {
    Write-Host 'NOTE: vcpkg default-features includes qt5; CI must pass VCPKG_MANIFEST_NO_DEFAULT_FEATURES=ON and wallet-only features.'
}

$requiredScript = Join-Path $PSScriptRoot "build-windows-node.ps1"
$scriptText = Get-Content -LiteralPath $requiredScript -Raw
if ($scriptText -notmatch "VCPKG_MANIFEST_NO_DEFAULT_FEATURES=ON") {
    throw "build-windows-node.ps1 must disable vcpkg default features"
}
if ($scriptText -notmatch "VCPKG_MANIFEST_FEATURES=wallet") {
    throw "build-windows-node.ps1 must request wallet feature only"
}
if ($scriptText -notmatch "BUILD_GUI=OFF") {
    throw "build-windows-node.ps1 must disable BUILD_GUI"
}
if ($scriptText -match "windows-clangcl-static") {
    throw 'build-windows-node.ps1 must not use windows-clangcl-static preset'
}
if ($scriptText -match "cmake\s+--preset") {
    throw 'build-windows-node.ps1 must not use cmake presets (they enable vcpkg default features)'
}
if ($scriptText -notmatch 'Get-CmakeVsGenerator') {
    throw 'build-windows-node.ps1 must resolve the Visual Studio generator from vswhere'
}
if ($scriptText -notmatch 'CMAKE_GENERATOR_INSTANCE') {
    throw 'build-windows-node.ps1 must pin the Visual Studio generator instance for CI'
}
if ($scriptText -notmatch '\$env:VCPKG_ROOT = \$VcpkgRoot') {
    throw 'build-windows-node.ps1 must override the Visual Studio bundled vcpkg root'
}
if ($scriptText -notmatch "Assert-HeadlessVcpkgInstall") {
    throw 'build-windows-node.ps1 must verify the headless vcpkg install'
}

Write-Host 'CI build config validation passed (headless wallet build, no Qt).'