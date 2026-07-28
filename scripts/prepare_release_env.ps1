[CmdletBinding()]
param(
    [string]$Name = "astroview-release",
    [string]$CondaLockPath = "environment-win-64.conda.lock",
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$verifyScript = Join-Path $PSScriptRoot "verify_conda_environment.ps1"

function Invoke-CondaChecked {
    param([string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& conda @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        $preview = ($output | Select-Object -First 20 | Out-String).Trim()
        throw "conda $($Arguments -join ' ') failed with exit code $exitCode.`n$preview"
    }
    return $output
}

function Get-NamedCondaEnvironment {
    param([string]$EnvironmentName)

    $json = (Invoke-CondaChecked -Arguments @("env", "list", "--json") | Out-String)
    $environmentList = $json | ConvertFrom-Json
    $matches = @(
        $environmentList.envs |
            Where-Object {
                (Split-Path -Leaf $_) -eq $EnvironmentName
            }
    )
    if ($matches.Count -gt 1) {
        throw "More than one Conda environment is named '$EnvironmentName': $($matches -join ', ')."
    }
    return ($matches | Select-Object -First 1)
}

function Get-EnvironmentPython {
    param([string]$Prefix)

    $candidate = Join-Path $Prefix "python.exe"
    if (-not (Test-Path -LiteralPath $candidate)) {
        $candidate = Join-Path $Prefix "bin\python"
    }
    if (-not (Test-Path -LiteralPath $candidate)) {
        throw "Conda environment '$Prefix' has no Python executable."
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Environment name '$Name' is invalid. Use letters, digits, dots, underscores, or hyphens."
}
if ($Name -eq "base") {
    throw "The base Conda environment cannot be used as the AstroView release environment."
}

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    throw "Could not locate conda. Activate a Conda shell before preparing the release environment."
}
if (-not (Test-Path -LiteralPath $verifyScript)) {
    throw "Release-environment verifier was not found at '$verifyScript'."
}

$resolvedLockPath = if ([System.IO.Path]::IsPathRooted($CondaLockPath)) {
    $CondaLockPath
} else {
    Join-Path $repoRoot $CondaLockPath
}
& $verifyScript -LockPath $resolvedLockPath -LockOnly

$existingPrefix = Get-NamedCondaEnvironment -EnvironmentName $Name
if ($existingPrefix) {
    $resolvedExistingPrefix = (Resolve-Path -LiteralPath $existingPrefix).Path
    $basePrefixText = (Invoke-CondaChecked -Arguments @("info", "--base") | Out-String).Trim()
    if (-not $basePrefixText -or -not (Test-Path -LiteralPath $basePrefixText)) {
        throw "Conda returned an invalid base prefix: '$basePrefixText'."
    }
    $resolvedBasePrefix = (Resolve-Path -LiteralPath $basePrefixText).Path
    if ($resolvedExistingPrefix -eq $resolvedBasePrefix) {
        throw "The Conda base environment cannot be used or recreated as the AstroView release environment."
    }

    try {
        $environmentPython = Get-EnvironmentPython -Prefix $resolvedExistingPrefix
        & $verifyScript `
            -LockPath $resolvedLockPath `
            -Prefix $resolvedExistingPrefix `
            -PythonPath $environmentPython
        Write-Host "Conda environment '$Name' is already ready for release builds."
        Write-Host "Activate it with: conda activate $Name"
        return
    }
    catch {
        if (-not $Recreate) {
            throw "Conda environment '$Name' exists but does not match the release lock. No changes were made. Review the mismatch above, then rerun with -Recreate to remove and rebuild only this environment.`n$($_.Exception.Message)"
        }

        if ($env:CONDA_PREFIX -and (Test-Path -LiteralPath $env:CONDA_PREFIX)) {
            $resolvedActivePrefix = (Resolve-Path -LiteralPath $env:CONDA_PREFIX).Path
            if ($resolvedExistingPrefix -eq $resolvedActivePrefix) {
                throw "Cannot recreate the active Conda environment '$Name'. Deactivate it and rerun this command from another environment."
            }
        }

        Write-Host "Removing mismatched release environment '$Name' because -Recreate was explicitly supplied."
        Invoke-CondaChecked -Arguments @(
            "env", "remove", "--prefix", $resolvedExistingPrefix, "--yes"
        ) | Out-Null
    }
}

Write-Host "Creating Conda environment '$Name' from the exact release lock."
Invoke-CondaChecked -Arguments @(
    "create",
    "--name", $Name,
    "--file", $resolvedLockPath,
    "--yes"
) | Out-Null

$createdPrefix = Get-NamedCondaEnvironment -EnvironmentName $Name
if (-not $createdPrefix) {
    throw "Conda reported success but environment '$Name' could not be located."
}
$createdPython = Get-EnvironmentPython -Prefix $createdPrefix
& $verifyScript `
    -LockPath $resolvedLockPath `
    -Prefix $createdPrefix `
    -PythonPath $createdPython

Write-Host "Conda environment '$Name' is ready."
Write-Host "Activate it with: conda activate $Name"
Write-Host "Then build with: .\scripts\build_windows.ps1 -CondaLockPath environment-win-64.conda.lock"
