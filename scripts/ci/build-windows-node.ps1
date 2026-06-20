param(
    [Parameter(Mandatory = $true)]
    [string]$BtxSourceDir,
    [string]$VcpkgRoot = "C:\vcpkg",
    [string]$VcpkgBuildtrees = "C:\vcpkg-buildtrees"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[ci] $Message"
}

function Import-VsDevEnvironment {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere)) {
        throw "vswhere.exe not found — Visual Studio C++ tools are required on the runner"
    }
    $installationPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        throw "Visual Studio 2022 C++ tools were not found"
    }
    $vsDevCmd = Join-Path $installationPath.Trim() "Common7\Tools\VsDevCmd.bat"
    Write-Step "Loading MSVC environment from $vsDevCmd"
    cmd.exe /c "`"$vsDevCmd`" -arch=x64 -host_arch=x64 >nul && set" |
        ForEach-Object {
            if ($_ -match "^(?<key>[^=]+)=(?<value>.*)$") {
                Set-Item -Path "env:$($Matches.key)" -Value $Matches.value
            }
        }
}

function Ensure-Tool([string]$Name, [string]$ChocoId) {
    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        return
    }
    if (-not (Get-Command choco.exe -ErrorAction SilentlyContinue)) {
        throw "$Name not found and choco is unavailable to install $ChocoId"
    }
    Write-Step "Installing $ChocoId via choco"
    & choco install $ChocoId -y --no-progress
    if ($LASTEXITCODE -ne 0) {
        throw "choco install $ChocoId failed"
    }
}

function Ensure-Vcpkg([string]$Root) {
    $toolchain = Join-Path $Root "scripts\buildsystems\vcpkg.cmake"
    $bootstrap = Join-Path $Root "bootstrap-vcpkg.bat"
    $vcpkgExe = Join-Path $Root "vcpkg.exe"

    if (-not (Test-Path -LiteralPath $bootstrap)) {
        Write-Step "Cloning vcpkg into $Root"
        if (Test-Path -LiteralPath $Root) {
            Remove-Item -LiteralPath $Root -Recurse -Force
        }
        git clone --depth 1 https://github.com/microsoft/vcpkg.git $Root
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to clone vcpkg"
        }
    }

    if (-not (Test-Path -LiteralPath $vcpkgExe)) {
        Write-Step "Bootstrapping vcpkg"
        Push-Location $Root
        try {
            cmd.exe /c "bootstrap-vcpkg.bat -disableMetrics"
            if ($LASTEXITCODE -ne 0) {
                throw "vcpkg bootstrap failed with exit code $LASTEXITCODE"
            }
        } finally {
            Pop-Location
        }
    }

    if (-not (Test-Path -LiteralPath $toolchain)) {
        throw "Missing vcpkg toolchain file at $toolchain"
    }
}

if (-not (Test-Path -LiteralPath $BtxSourceDir)) {
    throw "BTX source directory not found: $BtxSourceDir"
}

Import-VsDevEnvironment
Ensure-Tool -Name "cmake" -ChocoId "cmake"
Ensure-Tool -Name "ninja" -ChocoId "ninja"
Ensure-Tool -Name "clang-cl" -ChocoId "llvm"

if (Test-Path "C:\Program Files\LLVM\bin") {
    $env:Path = "C:\Program Files\LLVM\bin;C:\Program Files\Ninja;$env:Path"
}

Ensure-Vcpkg -Root $VcpkgRoot
$env:VCPKG_ROOT = $VcpkgRoot
$env:VCPKG_INSTALL_OPTIONS = "--x-buildtrees-root=$VcpkgBuildtrees"

Write-Step "Configuring BTX (windows-clangcl-static preset)"
Push-Location $BtxSourceDir
try {
    cmake --preset windows-clangcl-static `
        "-DVCPKG_INSTALL_OPTIONS=--x-buildtrees-root=$VcpkgBuildtrees"
    if ($LASTEXITCODE -ne 0) {
        throw "cmake configure failed"
    }

    Write-Step "Building btxd and btx-cli"
    cmake --build build --target btxd btx-cli --parallel
    if ($LASTEXITCODE -ne 0) {
        throw "cmake build failed"
    }
} finally {
    Pop-Location
}

$daemon = Get-ChildItem -Path (Join-Path $BtxSourceDir "build") -Recurse -Filter "btxd.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
$cli = Get-ChildItem -Path (Join-Path $BtxSourceDir "build") -Recurse -Filter "btx-cli.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $daemon -or -not $cli) {
    throw "Build finished but btxd.exe / btx-cli.exe were not found under $($BtxSourceDir)\build"
}

Write-Step "Built daemon: $($daemon.FullName)"
Write-Step "Built cli:    $($cli.FullName)"
"BTXD_PATH=$($daemon.FullName)" >> $env:GITHUB_ENV
"BTX_CLI_PATH=$($cli.FullName)" >> $env:GITHUB_ENV