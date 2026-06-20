param(
    [Parameter(Mandatory = $true)]
    [string]$BtxSourceDir,
    [string]$BuildDir = "",
    [string]$VcpkgRoot = "C:\vcpkg",
    [string]$VcpkgInstalledDir = "C:\vcpkg-installed\btx-node",
    [string]$VcpkgBuildtrees = "C:\vcpkg-buildtrees",
    [ValidateSet("Release", "RelWithDebInfo", "Debug")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[ci] $Message"
}

function Get-VsDevCmdPath {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere)) {
        throw "vswhere.exe not found"
    }
    $installationPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ([string]::IsNullOrWhiteSpace($installationPath)) {
        throw "Visual Studio 2022 C++ tools were not found"
    }
    $vsDevCmd = Join-Path $installationPath.Trim() "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $vsDevCmd)) {
        throw "VsDevCmd.bat not found at $vsDevCmd"
    }
    return $vsDevCmd
}

function Invoke-VsBatch([string]$VsDevCmd, [string[]]$Lines, [string]$Label) {
    $tempFile = Join-Path $env:TEMP ("btx-ci-" + [Guid]::NewGuid().ToString("N") + ".cmd")
    try {
        $script = @(
            "@echo off",
            "setlocal enableextensions",
            "call `"$VsDevCmd`" -arch=x64 -host_arch=x64 >nul || exit /b 1",
            "set VCPKG_ROOT=$VcpkgRoot"
        ) + $Lines
        Set-Content -LiteralPath $tempFile -Encoding Ascii -Value ($script -join "`r`n")
        Write-Step $Label
        cmd.exe /d /s /c "`"$tempFile`""
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
    } finally {
        Remove-Item -LiteralPath $tempFile -ErrorAction SilentlyContinue
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
        New-Item -ItemType Directory -Force -Path (Split-Path $Root -Parent) | Out-Null
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
    return $toolchain
}

function Assert-HeadlessVcpkgInstall([string]$InstalledDir, [string]$BuildDir) {
    $forbidden = @("qt5-base", "qt5-tools", "qt5", "libqrencode")
    if (Test-Path -LiteralPath $InstalledDir) {
        foreach ($pkg in $forbidden) {
            $matches = Get-ChildItem -Path $InstalledDir -Recurse -Directory -Filter $pkg -ErrorAction SilentlyContinue
            if ($matches) {
                throw "Headless build must not install $pkg (found under $InstalledDir)"
            }
        }
    }

    $installLog = Join-Path $BuildDir "vcpkg-manifest-install.log"
    if (Test-Path -LiteralPath $installLog) {
        $logText = Get-Content -LiteralPath $installLog -Raw
        foreach ($pkg in $forbidden) {
            if ($logText -match "Installing\s+$pkg[:/]" -or $logText -match "Building\s+$pkg[:/]") {
                throw "vcpkg manifest install pulled $pkg; disable default features and BUILD_GUI"
            }
        }
    }

    $cacheFile = Join-Path $BuildDir "CMakeCache.txt"
    if (Test-Path -LiteralPath $cacheFile) {
        $cache = Get-Content -LiteralPath $cacheFile -Raw
        if ($cache -notmatch "VCPKG_MANIFEST_NO_DEFAULT_FEATURES:BOOL=ON") {
            throw "CMake cache missing VCPKG_MANIFEST_NO_DEFAULT_FEATURES=ON"
        }
        if ($cache -notmatch "VCPKG_MANIFEST_FEATURES:STRING=wallet") {
            throw "CMake cache must request wallet feature only"
        }
        if ($cache -match "BUILD_GUI:BOOL=ON") {
            throw "BUILD_GUI must remain OFF for headless node CI"
        }
    }
}

function Find-Binary([string]$Root, [string]$Name) {
    $candidates = @(
        (Join-Path $Root "bin\$Configuration\$Name.exe"),
        (Join-Path $Root "bin\$Name.exe"),
        (Join-Path $Root "bin\Release\$Name.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    $found = Get-ChildItem -Path $Root -Recurse -Filter "$Name.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        return $found.FullName
    }
    throw "Expected binary was not produced: $Name.exe under $Root"
}

if (-not (Test-Path -LiteralPath $BtxSourceDir)) {
    throw "BTX source directory not found: $BtxSourceDir"
}

if ([string]::IsNullOrWhiteSpace($BuildDir)) {
    $BuildDir = Join-Path (Split-Path $BtxSourceDir -Parent) "btx-build"
}
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
New-Item -ItemType Directory -Force -Path $VcpkgInstalledDir | Out-Null
New-Item -ItemType Directory -Force -Path $VcpkgBuildtrees | Out-Null

$vsDevCmd = Get-VsDevCmdPath
$toolchain = Ensure-Vcpkg -Root $VcpkgRoot

Write-Step "Configuring headless wallet-enabled BTX build (no Qt/GUI)"
$configureArgs = @(
    "cmake",
    "-S `"$BtxSourceDir`"",
    "-B `"$BuildDir`"",
    "-G `"Visual Studio 17 2022`"",
    "-A x64",
    "-DCMAKE_TOOLCHAIN_FILE=`"$toolchain`"",
    "-DVCPKG_TARGET_TRIPLET=x64-windows",
    "-DVCPKG_INSTALLED_DIR=`"$VcpkgInstalledDir`"",
    "-DVCPKG_INSTALL_OPTIONS=--x-buildtrees-root=$VcpkgBuildtrees",
    "-DVCPKG_MANIFEST_NO_DEFAULT_FEATURES=ON",
    "-DVCPKG_MANIFEST_FEATURES=wallet",
    "-DBUILD_DAEMON=ON",
    "-DBUILD_CLI=ON",
    "-DBUILD_UTIL=ON",
    "-DBUILD_TX=ON",
    "-DBUILD_WALLET_TOOL=OFF",
    "-DBUILD_GUI=OFF",
    "-DBUILD_BENCH=OFF",
    "-DBUILD_TESTS=OFF",
    "-DENABLE_WALLET=ON",
    "-DWITH_SQLITE=ON",
    "-DBTX_ENABLE_CUDA_EXPERIMENTAL=OFF",
    "-DWARN_INCOMPATIBLE_BDB=OFF"
) -join " "

Invoke-VsBatch -VsDevCmd $vsDevCmd -Lines @($configureArgs) -Label "CMake configure"
Assert-HeadlessVcpkgInstall -InstalledDir $VcpkgInstalledDir -BuildDir $BuildDir

Write-Step "Building btxd and btx-cli ($Configuration)"
$buildArgs = "cmake --build `"$BuildDir`" --config $Configuration --parallel --target btxd btx-cli"
Invoke-VsBatch -VsDevCmd $vsDevCmd -Lines @($buildArgs) -Label "CMake build"

$daemon = Find-Binary -Root $BuildDir -Name "btxd"
$cli = Find-Binary -Root $BuildDir -Name "btx-cli"

Write-Step "Built daemon: $daemon"
Write-Step "Built cli:    $cli"
"BTXD_PATH=$daemon" >> $env:GITHUB_ENV
"BTX_CLI_PATH=$cli" >> $env:GITHUB_ENV