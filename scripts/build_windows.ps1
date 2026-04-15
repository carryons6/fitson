[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-ConfiguredPythonPath {
    param([string]$RepoRoot)

    $configPath = Join-Path $RepoRoot ".python-env.local"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $null
    }

    $configuredPath = Get-Content -LiteralPath $configPath |
        Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") } |
        Select-Object -First 1

    if (-not $configuredPath) {
        return $null
    }

    if (Test-Path -LiteralPath $configuredPath) {
        return (Resolve-Path -LiteralPath $configuredPath).Path
    }

    return $configuredPath
}

function Resolve-BuildPython {
    param([string]$RepoRoot)

    $candidates = @()
    $configuredPython = Get-ConfiguredPythonPath -RepoRoot $RepoRoot
    if ($configuredPython) {
        $candidates += $configuredPython
    }

    if ($env:CONDA_PREFIX) {
        $activePython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path -LiteralPath $activePython) {
            $candidates += $activePython
        }
    }

    $pathPython = Get-Command python -ErrorAction SilentlyContinue
    if ($pathPython -and $pathPython.Source) {
        $candidates += $pathPython.Source
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Resolve-IsccPath {
    $candidates = @(
        "ISCC.exe",
        "D:\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )

    $command = Get-Command iscc -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        $candidates = @($command.Source) + $candidates
    }

    $registryPaths = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    )
    foreach ($registryPath in $registryPaths) {
        if (-not (Test-Path -LiteralPath $registryPath)) {
            continue
        }

        $item = Get-ItemProperty -LiteralPath $registryPath -ErrorAction SilentlyContinue
        if ($item -and $item.InstallLocation) {
            $candidates += (Join-Path $item.InstallLocation "ISCC.exe")
        }
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

function Assert-BundledVersion {
    param([string]$RepoRoot)

    $sourceVersionPath = Join-Path $RepoRoot "VERSION"
    $bundleVersionPath = Join-Path $RepoRoot "dist\AstroView\_internal\astroview\VERSION"

    if (-not (Test-Path -LiteralPath $bundleVersionPath)) {
        throw "Bundled VERSION file was not produced at '$bundleVersionPath'. The installer would package a stale or incomplete build."
    }

    $sourceVersion = (Get-Content -LiteralPath $sourceVersionPath | Select-Object -First 1).Trim()
    $bundleVersion = (Get-Content -LiteralPath $bundleVersionPath | Select-Object -First 1).Trim()

    if ($sourceVersion -ne $bundleVersion) {
        throw "Bundled app version '$bundleVersion' does not match source version '$sourceVersion'. Rebuild before creating the installer."
    }
}

function Assert-BundledExeVersionInfo {
    param([string]$RepoRoot)

    $sourceVersionPath = Join-Path $RepoRoot "VERSION"
    $bundledExePath = Join-Path $RepoRoot "dist\AstroView\AstroView.exe"

    if (-not (Test-Path -LiteralPath $bundledExePath)) {
        throw "Bundled executable was not produced at '$bundledExePath'."
    }

    $sourceVersion = (Get-Content -LiteralPath $sourceVersionPath | Select-Object -First 1).Trim()
    $exeVersionInfo = (Get-Item -LiteralPath $bundledExePath).VersionInfo
    $productVersion = ($exeVersionInfo.ProductVersion | Select-Object -First 1)
    $fileVersion = ($exeVersionInfo.FileVersion | Select-Object -First 1)

    if (-not $productVersion -or -not $fileVersion) {
        throw "Bundled executable is missing ProductVersion/FileVersion metadata."
    }

    if ($productVersion -ne $sourceVersion -or $fileVersion -ne $sourceVersion) {
        throw "Bundled executable version info ('$productVersion' / '$fileVersion') does not match source version '$sourceVersion'."
    }
}

$buildPython = Resolve-BuildPython -RepoRoot $repoRoot
if (-not $buildPython) {
    throw "Could not locate a usable python.exe for the build."
}

Push-Location $repoRoot
try {
    if (-not $SkipTests) {
        & $buildPython -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "Tests failed."
        }
    }

    & $buildPython -m PyInstaller astroview.spec --noconfirm
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    Assert-BundledVersion -RepoRoot $repoRoot
    Assert-BundledExeVersionInfo -RepoRoot $repoRoot

    if (-not $SkipInstaller) {
        $iscc = Resolve-IsccPath
        if (-not $iscc) {
            throw "Inno Setup compiler 'iscc' was not found on PATH."
        }

        & $iscc installer.iss
        if ($LASTEXITCODE -ne 0) {
            throw "Installer build failed."
        }
    }
}
finally {
    Pop-Location
}
