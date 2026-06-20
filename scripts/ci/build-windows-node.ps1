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

function Get-CmakeVsGenerator([string]$InstallationPath, [string]$MajorVersion) {
    if ($InstallationPath -match '\\18\\' -or $MajorVersion -match '^18\.') {
        return "Visual Studio 18 2026"
    }
    if ($InstallationPath -match '\\2022\\' -or $MajorVersion -match '^17\.') {
        return "Visual Studio 17 2022"
    }
    throw "Unsupported Visual Studio installation at $InstallationPath (version $MajorVersion)"
}

function Get-VsInstallInfo {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere)) {
        throw "vswhere.exe not found"
    }

    $vsMatches = & $vswhere `
        -latest `
        -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or -not $vsMatches) {
        throw "Visual Studio C++ tools were not found"
    }

    $vsMatch = @($vsMatches)[0]
    $installationPath = [string]$vsMatch.installationPath
    $installationVersion = [string]$vsMatch.installationVersion
    if ([string]::IsNullOrWhiteSpace($installationPath) -or [string]::IsNullOrWhiteSpace($installationVersion)) {
        throw "Visual Studio C++ tools were not found"
    }
    $majorVersion = ($installationVersion -split '\.')[0] + '.' + ($installationVersion -split '\.')[1]

    $vsDevCmd = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $vsDevCmd)) {
        throw "VsDevCmd.bat not found at $vsDevCmd"
    }

    return @{
        InstallationPath = $installationPath
        InstallationVersion = $installationVersion
        MajorVersion = $majorVersion
        Generator = (Get-CmakeVsGenerator -InstallationPath $installationPath -MajorVersion $majorVersion)
        VsDevCmd = $vsDevCmd
    }
}

function Import-VsDevEnvironment([string]$VsDevCmd) {
    cmd.exe /c "`"$VsDevCmd`" -arch=x64 -host_arch=x64 >nul && set" |
        ForEach-Object {
            if ($_ -match "^(?<key>[^=]+)=(?<value>.*)$") {
                Set-Item -Path "env:$($Matches.key)" -Value $Matches.value
            }
        }
}

function Apply-WindowsSourcePatches([string]$SourceDir) {
    $header = Join-Path $SourceDir "src\kernel\chainstatemanager_opts.h"
    if (-not (Test-Path -LiteralPath $header)) {
        throw "Missing BTX header for Windows patch: $header"
    }

    $content = Get-Content -LiteralPath $header -Raw
    if ($content -notmatch '#undef STRICT') {
        $guard = @"

// Windows headers define STRICT as a macro, which breaks ReorgProtectionProfile::STRICT.
#ifdef STRICT
#undef STRICT
#endif

"@
        $content = $content.Replace("#include <optional>", "#include <optional>$guard")
        Set-Content -LiteralPath $header -Value $content -Encoding utf8NoBOM -NoNewline
        Write-Step "Patched chainstatemanager_opts.h for Windows STRICT macro conflict"
    }
}

function Ensure-ClangClOnPath([string]$VsInstallationPath) {
    $candidates = @(
        "C:\Program Files\LLVM\bin",
        (Join-Path $VsInstallationPath "VC\Tools\Llvm\x64\bin")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "clang-cl.exe")) {
            if ($env:Path -notlike "*$candidate*") {
                $env:Path = "$candidate;$env:Path"
            }
            return (Join-Path $candidate "clang-cl.exe")
        }
    }
    throw "clang-cl.exe not found; BTX requires clang-cl on Windows"
}

function Invoke-VsCmake([hashtable]$Vs, [string[]]$CmakeArgs, [string]$Label) {
    Import-VsDevEnvironment -VsDevCmd $Vs.VsDevCmd
    Remove-Item Env:CMAKE_TOOLCHAIN_FILE -ErrorAction SilentlyContinue
    $env:VCPKG_ROOT = $VcpkgRoot
    if ($env:VCPKG_ROOT -ne $VcpkgRoot) {
        throw "Failed to pin VCPKG_ROOT to $VcpkgRoot (got $($env:VCPKG_ROOT))"
    }
    $clangCl = Ensure-ClangClOnPath -VsInstallationPath $Vs.InstallationPath
    Write-Step "Using clang-cl at $clangCl"
    Write-Step $Label
    & cmake @CmakeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
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
        if ($cache -match "BUILD_GUI:BOOL=ON") {
            throw "BUILD_GUI must remain OFF for headless node CI"
        }
        if ($cache -notmatch "BUILD_GUI:BOOL=OFF") {
            throw "CMake cache missing BUILD_GUI=OFF"
        }
        if ($cache -match "VCPKG_MANIFEST_FEATURES:STRING=.*qt5") {
            throw "CMake cache must not request qt5 vcpkg features"
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

$vs = Get-VsInstallInfo
$toolchain = Ensure-Vcpkg -Root $VcpkgRoot
Apply-WindowsSourcePatches -SourceDir $BtxSourceDir

Write-Step "Configuring headless wallet-enabled BTX build (Ninja + clang-cl, no Qt/GUI)"
Write-Step "Using Visual Studio toolchain at $($vs.InstallationPath) (version $($vs.InstallationVersion))"
$configureArgs = @(
    "-S", $BtxSourceDir,
    "-B", $BuildDir,
    "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=$Configuration",
    "-DCMAKE_C_COMPILER=clang-cl",
    "-DCMAKE_CXX_COMPILER=clang-cl",
    "-DCMAKE_TOOLCHAIN_FILE=$toolchain",
    "-DVCPKG_TARGET_TRIPLET=x64-windows-static",
    "-DVCPKG_INSTALLED_DIR=$VcpkgInstalledDir",
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
)

Invoke-VsCmake -Vs $vs -CmakeArgs $configureArgs -Label "CMake configure"
Assert-HeadlessVcpkgInstall -InstalledDir $VcpkgInstalledDir -BuildDir $BuildDir

Write-Step "Building btxd and btx-cli ($Configuration)"
$buildArgs = @(
    "--build", $BuildDir,
    "--parallel",
    "--target", "btxd", "btx-cli"
)
Invoke-VsCmake -Vs $vs -CmakeArgs $buildArgs -Label "CMake build"

$daemon = Find-Binary -Root $BuildDir -Name "btxd"
$cli = Find-Binary -Root $BuildDir -Name "btx-cli"

Write-Step "Built daemon: $daemon"
Write-Step "Built cli:    $cli"
"BTXD_PATH=$daemon" >> $env:GITHUB_ENV
"BTX_CLI_PATH=$cli" >> $env:GITHUB_ENV