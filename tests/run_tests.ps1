[CmdletBinding()]
param(
    [string]$Pattern = "test*.py",
    [switch]$FailFast
)

$ErrorActionPreference = "Stop"

function Wait-ForExit {
    Write-Host ""
    Write-Host "Press Enter to exit..." -ForegroundColor Yellow
    [void](Read-Host)
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
}

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

function Resolve-AstroPython {
    param([string]$RepoRoot)

    $candidates = @()
    $configuredPython = Get-ConfiguredPythonPath -RepoRoot $RepoRoot

    if ($configuredPython) {
        $candidates += $configuredPython
    }

    if ($env:CONDA_PREFIX) {
        $activePython = Join-Path $env:CONDA_PREFIX "python.exe"
        if ((Split-Path $env:CONDA_PREFIX -Leaf) -ieq "astro") {
            $candidates += $activePython
        }
    }

    $candidates += @(
        "D:\Miniforge\envs\astro\python.exe",
        "C:\Miniforge3\envs\astro\python.exe",
        "C:\Users\Public\miniforge3\envs\astro\python.exe"
    )

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $null
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$astroPython = Resolve-AstroPython -RepoRoot $repoRoot
$envCheckScript = @(
    "import importlib",
    "import platform",
    "import sys",
    "",
    "print('sys.executable   : {}'.format(sys.executable))",
    "print('python_version   : {}'.format(sys.version.split()[0]))",
    "print('platform         : {}'.format(platform.platform()))",
    "",
    "for name in ['astropy', 'numpy', 'sep', 'PySide6']:",
    "    try:",
    "        module = importlib.import_module(name)",
    "        version = getattr(module, '__version__', 'unknown')",
    "        print('{:16}: OK ({})'.format(name, version))",
    "    except Exception as exc:",
    "        print('{:16}: ERROR ({})'.format(name, exc))"
) -join [Environment]::NewLine

Write-Section "AstroView Test Runner"
Write-Host ("Start Time      : {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Host ("Script Path     : {0}" -f $MyInvocation.MyCommand.Path)
Write-Host ("Tests Directory : {0}" -f $scriptDir)
Write-Host ("Repository Root : {0}" -f $repoRoot)
Write-Host ("Pattern         : {0}" -f $Pattern)
Write-Host ("Fail Fast       : {0}" -f $FailFast.IsPresent)

if (-not $astroPython) {
    Write-Section "Environment Error"
    Write-Host "Could not locate python.exe for the conda astro environment." -ForegroundColor Red
    Write-Host "Checked .python-env.local, the active CONDA_PREFIX (if it is astro), and common Miniforge locations." -ForegroundColor Yellow
    Wait-ForExit
    exit 1
}

Write-Host ("Astro Python    : {0}" -f $astroPython)

Push-Location $repoRoot
try {
    Write-Section "Environment Check"
    & $astroPython -c $envCheckScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Environment check failed." -ForegroundColor Red
        Wait-ForExit
        exit $LASTEXITCODE
    }

    Write-Section "Discovered Tests"
    $matchedFiles = Get-ChildItem -Path (Join-Path $repoRoot "tests") -Filter $Pattern | Sort-Object Name
    foreach ($file in $matchedFiles) {
        Write-Host (" - {0}" -f $file.Name)
    }
    Write-Host ("Matched Files   : {0}" -f $matchedFiles.Count)
    if ($matchedFiles.Count -eq 0) {
        Write-Host "No test files matched the requested pattern." -ForegroundColor Yellow
        Wait-ForExit
        exit 1
    }

    $command = @("-m", "unittest", "discover", "-s", "tests", "-p", $Pattern, "-v")
    if ($FailFast.IsPresent) {
        $command += "-f"
    }

    Write-Section "Running Tests"
    Write-Host ("Command         : {0} {1}" -f $astroPython, ($command -join " "))
    & $astroPython @command
    $testExit = $LASTEXITCODE

    Write-Section "Result"
    if ($testExit -eq 0) {
        Write-Host "All discovered tests passed." -ForegroundColor Green
    } else {
        Write-Host ("Test run failed with exit code {0}." -f $testExit) -ForegroundColor Red
    }
    Write-Host ("Finish Time     : {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    Wait-ForExit
    exit $testExit
}
finally {
    Pop-Location
}
