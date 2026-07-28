[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [string]$CondaLockPath
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
            $resolvedCandidate = (Resolve-Path -LiteralPath $candidate).Path
            try {
                & $resolvedCandidate -c "import sys; raise SystemExit(0)" *> $null
                if ($LASTEXITCODE -eq 0) {
                    return $resolvedCandidate
                }
            }
            catch {
                # Windows exposes an inaccessible Microsoft Store python.exe
                # shim on PATH on some machines. Skip unusable candidates and
                # continue to an activated/configured environment.
                continue
            }
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

function Assert-InnoSetupMajorVersion {
    param([string]$IsccPath)

    # ISCC /? intentionally exits with code 1 and its executable metadata is
    # 0.0.0.0. Capture the complete output (avoiding a broken pipeline), then
    # scan it for the reliable banner while deliberately ignoring that exit
    # code. stdout/stderr merging does not guarantee which line arrives first.
    # Windows PowerShell 5 promotes native stderr to NativeCommandError when
    # ErrorActionPreference is Stop. ISCC writes its /? banner to stderr and
    # exits with code 1 by design, so capture it under Continue and restore the
    # caller's fail-fast policy immediately afterwards.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $helpOutput = @(& $IsccPath /? 2>&1)
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $versionBanner = @(
        $helpOutput |
            ForEach-Object { $_.ToString() } |
            Where-Object { $_ -match '^Inno Setup \d+(?:\s|$)' }
    ) | Select-Object -First 1
    if ($versionBanner -notmatch '^Inno Setup 6(?:\s|$)') {
        $summary = ($helpOutput | Select-Object -First 3 | Out-String).Trim()
        throw "The installer compiler must be Inno Setup 6.x; no matching version banner was found in '$IsccPath'.`n$summary"
    }
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

function Invoke-BundledSmokeAttempt {
    param(
        [string]$BundledExePath,
        [string]$ReportPath,
        [string]$AttemptName,
        [int]$TimeoutMilliseconds
    )

    if (Test-Path -LiteralPath $ReportPath) {
        Remove-Item -LiteralPath $ReportPath -Force
    }

    $process = Start-Process `
        -FilePath $BundledExePath `
        -ArgumentList "--smoke-test" `
        -PassThru `
        -WindowStyle Hidden
    if (-not $process.WaitForExit($TimeoutMilliseconds)) {
        # A newly built, unsigned executable can spend several minutes in the
        # host's first-run endpoint scan. Terminate the exact smoke-test tree
        # if even the bounded cold-start allowance is exhausted.
        try {
            $process.Kill($true)
        }
        catch {
            # Windows PowerShell 5.1 runs on .NET Framework, whose Process
            # type lacks Kill(bool). Use taskkill there so descendants are
            # not left holding files in the frozen distribution.
            $taskkillPath = Join-Path $env:SystemRoot "System32\taskkill.exe"
            if (Test-Path -LiteralPath $taskkillPath) {
                & $taskkillPath /PID $process.Id /T /F 2>$null | Out-Null
            }
            if (-not $process.HasExited) {
                $process.Kill()
            }
        }
        $process.WaitForExit(5000) | Out-Null
        $report = if (Test-Path -LiteralPath $ReportPath) {
            (Get-Content -LiteralPath $ReportPath -Raw).Trim()
        } else {
            "<no smoke-test report was produced>"
        }
        $timeoutSeconds = [math]::Round($TimeoutMilliseconds / 1000)
        throw "Bundled executable $AttemptName smoke test timed out after $timeoutSeconds seconds.`n$report"
    }

    $report = if (Test-Path -LiteralPath $ReportPath) {
        (Get-Content -LiteralPath $ReportPath -Raw).Trim()
    } else {
        "<no smoke-test report was produced>"
    }
    if ($process.ExitCode -ne 0 -or -not $report.StartsWith("OK ")) {
        throw "Bundled executable $AttemptName smoke test failed with exit code $($process.ExitCode).`n$report"
    }
}

function Invoke-BundledSmokeTest {
    param([string]$RepoRoot)

    $bundledExePath = Join-Path $RepoRoot "dist\AstroView\AstroView.exe"
    if (-not (Test-Path -LiteralPath $bundledExePath)) {
        throw "Bundled executable was not produced at '$bundledExePath'."
    }

    $reportDir = Join-Path $RepoRoot "build\smoke-test"
    $reportPath = Join-Path $reportDir "result.txt"
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

    $previousReportPath = [Environment]::GetEnvironmentVariable("ASTROVIEW_SMOKE_REPORT", "Process")
    [Environment]::SetEnvironmentVariable("ASTROVIEW_SMOKE_REPORT", $reportPath, "Process")
    try {
        # The first launch covers cold endpoint scanning; the second proves
        # that normal warmed startup still stays within the strict budget.
        Invoke-BundledSmokeAttempt `
            -BundledExePath $bundledExePath `
            -ReportPath $reportPath `
            -AttemptName "cold-start" `
            -TimeoutMilliseconds 300000
        Invoke-BundledSmokeAttempt `
            -BundledExePath $bundledExePath `
            -ReportPath $reportPath `
            -AttemptName "warm-start" `
            -TimeoutMilliseconds 60000
    }
    finally {
        [Environment]::SetEnvironmentVariable("ASTROVIEW_SMOKE_REPORT", $previousReportPath, "Process")
    }
}

function Write-ReleaseChecksums {
    param([string]$RepoRoot)

    $sourceVersion = (Get-Content -LiteralPath (Join-Path $RepoRoot "VERSION") | Select-Object -First 1).Trim()
    $installerPath = Join-Path $RepoRoot "installer_output\AstroView_Setup_$sourceVersion.exe"
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Expected installer was not produced at '$installerPath'."
    }

    $checksumPath = Join-Path $RepoRoot "installer_output\SHA256SUMS.txt"
    $hash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $line = "$hash  $([System.IO.Path]::GetFileName($installerPath))"
    [System.IO.File]::WriteAllText(
        $checksumPath,
        # Release verification runs on Linux. Use a literal LF so GNU
        # sha256sum never interprets a trailing CR as part of the filename.
        $line + "`n",
        [System.Text.Encoding]::ASCII
    )
}

$buildPython = Resolve-BuildPython -RepoRoot $repoRoot
if (-not $buildPython) {
    throw "Could not locate a usable python.exe for the build."
}
if ($CondaLockPath) {
    if (-not $env:CONDA_PREFIX) {
        throw "-CondaLockPath requires an activated Conda environment."
    }
    $resolvedLockPath = if ([System.IO.Path]::IsPathRooted($CondaLockPath)) {
        $CondaLockPath
    } else {
        Join-Path $repoRoot $CondaLockPath
    }
    $verifyEnvironmentScript = Join-Path $PSScriptRoot "verify_conda_environment.ps1"
    & $verifyEnvironmentScript `
        -LockPath $resolvedLockPath `
        -Prefix $env:CONDA_PREFIX `
        -PythonPath $buildPython
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
    Invoke-BundledSmokeTest -RepoRoot $repoRoot

    if (-not $SkipInstaller) {
        $iscc = Resolve-IsccPath
        if (-not $iscc) {
            throw "Inno Setup compiler 'iscc' was not found on PATH."
        }

        Assert-InnoSetupMajorVersion -IsccPath $iscc
        & $iscc installer.iss
        if ($LASTEXITCODE -ne 0) {
            throw "Installer build failed."
        }
        Write-ReleaseChecksums -RepoRoot $repoRoot
    }
}
finally {
    Pop-Location
}
