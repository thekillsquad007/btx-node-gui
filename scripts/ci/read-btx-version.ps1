param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir
)

$cmake = Join-Path $SourceDir "CMakeLists.txt"
if (-not (Test-Path -LiteralPath $cmake)) {
    throw "CMakeLists.txt not found under $SourceDir"
}

$major = $null
$minor = $null
$build = $null
$rc = 0

Get-Content -LiteralPath $cmake | ForEach-Object {
    if ($_ -match 'set\(CLIENT_VERSION_MAJOR\s+(\d+)\)') { $major = $Matches[1] }
    if ($_ -match 'set\(CLIENT_VERSION_MINOR\s+(\d+)\)') { $minor = $Matches[1] }
    if ($_ -match 'set\(CLIENT_VERSION_BUILD\s+(\d+)\)') { $build = $Matches[1] }
    if ($_ -match 'set\(CLIENT_VERSION_RC\s+(\d+)\)') { $rc = [int]$Matches[1] }
}

if ($null -eq $major -or $null -eq $minor -or $null -eq $build) {
    throw "Could not parse CLIENT_VERSION_* from $cmake"
}

$version = "$major.$minor.$build"
if ($rc -gt 0) {
    $version += "rc$rc"
}
Write-Output $version