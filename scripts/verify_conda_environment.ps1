[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LockPath,
    [string]$Prefix,
    [string]$PythonPath,
    [switch]$LockOnly
)

$ErrorActionPreference = "Stop"

function Resolve-ExistingPath {
    param(
        [string]$Path,
        [string]$Description
    )

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        throw "$Description was not found at '$Path'."
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-ExplicitCondaLock {
    param([string]$Path)

    $content = @(
        Get-Content -LiteralPath $Path |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and -not $_.StartsWith("#") }
    )
    if (-not $content -or $content[0] -ne "@EXPLICIT") {
        throw "Conda lock '$Path' must begin with @EXPLICIT."
    }

    $packageUrls = @($content | Select-Object -Skip 1)
    if (-not $packageUrls) {
        throw "Conda lock '$Path' contains no hash-locked package URLs."
    }

    $validUrlPattern = '^https://conda\.anaconda\.org/conda-forge/(win-64|noarch)/[^/]+#[0-9a-fA-F]{64}$'
    $invalidUrls = @($packageUrls | Where-Object { $_ -notmatch $validUrlPattern })
    if ($invalidUrls) {
        $preview = ($invalidUrls | Select-Object -First 5 | Out-String).Trim()
        throw "Conda lock '$Path' contains malformed or non-conda-forge package URLs.`n$preview"
    }

    $normalizedUrls = @($packageUrls | ForEach-Object { $_.ToLowerInvariant() })
    $duplicateUrls = @(
        $normalizedUrls |
            Group-Object |
            Where-Object { $_.Count -gt 1 } |
            ForEach-Object { $_.Name }
    )
    if ($duplicateUrls) {
        $preview = ($duplicateUrls | Select-Object -First 5 | Out-String).Trim()
        throw "Conda lock '$Path' contains duplicate package URLs.`n$preview"
    }

    return @($normalizedUrls | Sort-Object)
}

function Get-CondaPackageRecord {
    param([string]$Url)

    $artifactUrl = $Url.Split("#", 2)[0]
    $fileName = [System.IO.Path]::GetFileName(([System.Uri]$artifactUrl).AbsolutePath)
    if ($fileName.EndsWith(".tar.bz2", [System.StringComparison]::OrdinalIgnoreCase)) {
        $stem = $fileName.Substring(0, $fileName.Length - ".tar.bz2".Length)
    }
    elseif ($fileName.EndsWith(".conda", [System.StringComparison]::OrdinalIgnoreCase)) {
        $stem = $fileName.Substring(0, $fileName.Length - ".conda".Length)
    }
    else {
        $stem = $fileName
    }

    $parts = @($stem -split "-")
    if ($parts.Count -ge 3) {
        $name = ($parts[0..($parts.Count - 3)] -join "-")
    }
    else {
        $name = $stem
    }

    return [pscustomobject]@{
        Name = $name
        Artifact = $fileName
        Url = $Url
    }
}

function Format-CondaDifference {
    param(
        [string[]]$Expected,
        [string[]]$Actual
    )

    $missing = @($Expected | Where-Object { $_ -notin $Actual })
    $unexpected = @($Actual | Where-Object { $_ -notin $Expected })
    $expectedRecords = @($missing | ForEach-Object { Get-CondaPackageRecord -Url $_ })
    $actualRecords = @($unexpected | ForEach-Object { Get-CondaPackageRecord -Url $_ })
    $allNames = @(
        @($expectedRecords.Name) + @($actualRecords.Name) |
            Sort-Object -Unique
    )
    $criticalNames = @(
        "python",
        "pyside6",
        "astropy",
        "astropy-base",
        "numpy",
        "sep",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "pip",
        "setuptools",
        "wheel",
        "packaging",
        "libblas",
        "libopenblas"
    )
    $names = @(
        @($criticalNames | Where-Object { $_ -in $allNames }) +
        @($allNames | Where-Object { $_ -notin $criticalNames })
    )

    $lines = foreach ($name in $names | Select-Object -First 10) {
        $expectedArtifacts = @(
            $expectedRecords |
                Where-Object { $_.Name -eq $name } |
                ForEach-Object { $_.Artifact }
        )
        $actualArtifacts = @(
            $actualRecords |
                Where-Object { $_.Name -eq $name } |
                ForEach-Object { $_.Artifact }
        )
        if ($expectedArtifacts) {
            "  ${name}: expected $($expectedArtifacts -join ', ')"
        }
        if ($actualArtifacts) {
            "  ${name}: actual   $($actualArtifacts -join ', ')"
        }
    }
    return ($lines -join "`n")
}

$resolvedLockPath = Resolve-ExistingPath -Path $LockPath -Description "Conda lock"
$expected = @(Read-ExplicitCondaLock -Path $resolvedLockPath)
if ($LockOnly) {
    Write-Host "Validated $($expected.Count) hash-locked packages in '$resolvedLockPath'."
    return
}

if (-not $Prefix) {
    throw "-Prefix is required unless -LockOnly is used."
}
$resolvedPrefix = Resolve-ExistingPath -Path $Prefix -Description "Conda environment"
$activePython = Join-Path $resolvedPrefix "python.exe"
if (-not (Test-Path -LiteralPath $activePython)) {
    $activePython = Join-Path $resolvedPrefix "bin\python"
}
$activePython = Resolve-ExistingPath -Path $activePython -Description "Conda environment Python"

if ($PythonPath) {
    $resolvedPython = Resolve-ExistingPath -Path $PythonPath -Description "Build Python"
    if ($resolvedPython -ne $activePython) {
        throw "Build Python '$resolvedPython' is not the selected Conda-environment Python '$activePython'."
    }
}
else {
    $resolvedPython = $activePython
}

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    throw "Could not locate conda to verify the release environment."
}

$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $actualOutput = @(& conda list --prefix $resolvedPrefix --explicit --sha256 2>&1)
    $condaExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($condaExitCode -ne 0) {
    $preview = ($actualOutput | Select-Object -First 10 | Out-String).Trim()
    throw "conda list failed while verifying '$resolvedPrefix' (exit $condaExitCode).`n$preview"
}

$actualRecords = @(
    $actualOutput |
        ForEach-Object { $_.ToString().Trim() } |
        Where-Object { $_ -and -not $_.StartsWith("#") }
)
if (-not $actualRecords -or $actualRecords[0] -ne "@EXPLICIT") {
    $preview = ($actualRecords | Select-Object -First 5 | Out-String).Trim()
    throw "conda list did not return an @EXPLICIT package list.`n$preview"
}
$actualPackageUrls = @($actualRecords | Select-Object -Skip 1)
$validActualUrlPattern = '^https://conda\.anaconda\.org/conda-forge/(win-64|noarch)/[^/]+#[0-9a-fA-F]{64}$'
$malformedActualUrls = @(
    $actualPackageUrls |
        Where-Object { $_ -notmatch $validActualUrlPattern }
)
if ($malformedActualUrls) {
    $preview = ($malformedActualUrls | Select-Object -First 5 | Out-String).Trim()
    throw "conda list returned unsupported or malformed package records; exact releases require conda-forge HTTPS URLs with SHA-256 hashes.`n$preview"
}
$actual = @(
    $actualPackageUrls |
        ForEach-Object { $_.ToLowerInvariant() } |
        Sort-Object
)

$difference = @(Compare-Object -ReferenceObject $expected -DifferenceObject $actual)
if ($difference.Count -ne 0) {
    $summary = Format-CondaDifference -Expected $expected -Actual $actual
    throw "Conda environment '$resolvedPrefix' does not exactly match '$resolvedLockPath' (expected $($expected.Count) packages, found $($actual.Count)).`n$summary"
}

try {
    $ErrorActionPreference = "Continue"
    $inventoryOutput = @(& conda list --prefix $resolvedPrefix --json 2>&1)
    $inventoryExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($inventoryExitCode -ne 0) {
    $preview = ($inventoryOutput | Select-Object -First 10 | Out-String).Trim()
    throw "conda list --json failed while checking pip-managed packages in '$resolvedPrefix'.`n$preview"
}
try {
    $parsedInventory = (($inventoryOutput -join "`n") | ConvertFrom-Json)
}
catch {
    throw "conda list --json returned invalid JSON for '$resolvedPrefix': $($_.Exception.Message)"
}
$inventory = @()
foreach ($record in $parsedInventory) {
    $inventory += $record
}
$pipManagedRecords = @(
    $inventory |
        Where-Object {
            $_.channel -eq "pypi" -or
            $_.platform -eq "pypi" -or
            $_.build_string -eq "pypi_0"
        }
)
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $condaInventoryOutput = @(& conda list --prefix $resolvedPrefix --no-pip --json 2>&1)
    $condaInventoryExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($condaInventoryExitCode -ne 0) {
    $preview = ($condaInventoryOutput | Select-Object -First 10 | Out-String).Trim()
    throw "conda list --no-pip --json failed for '$resolvedPrefix'.`n$preview"
}
try {
    $parsedCondaInventory = (($condaInventoryOutput -join "`n") | ConvertFrom-Json)
}
catch {
    throw "conda list --no-pip --json returned invalid JSON for '$resolvedPrefix': $($_.Exception.Message)"
}
$condaInventory = @()
foreach ($record in $parsedCondaInventory) {
    $condaInventory += $record
}
$unlockedPipRecords = @(
    foreach ($pipRecord in $pipManagedRecords) {
        $matchedCondaRecord = $false
        foreach ($condaRecord in $condaInventory) {
            if (
                $condaRecord.name -eq $pipRecord.name -and
                $condaRecord.version -eq $pipRecord.version
            ) {
                $matchedCondaRecord = $true
                break
            }
        }
        if (-not $matchedCondaRecord) {
            $pipRecord
        }
    }
)
if ($unlockedPipRecords) {
    $preview = @(
        $unlockedPipRecords |
            Select-Object -First 10 |
            ForEach-Object { "  $($_.name) $($_.version) ($($_.build_string), $($_.channel))" }
    ) -join "`n"
    throw "Conda environment '$resolvedPrefix' contains unlocked pip-managed packages.`n$preview"
}

$pipAliasNames = @($pipManagedRecords | ForEach-Object { $_.name } | Sort-Object -Unique)
if ($pipAliasNames) {
    $installerProbe = @'
import importlib.metadata as metadata
import sys

for distribution_name in sys.argv[1:]:
    distribution = metadata.distribution(distribution_name)
    installer = (distribution.read_text('INSTALLER') or '').strip()
    print(f'{distribution_name}\t{installer}')
'@
    try {
        $ErrorActionPreference = "Continue"
        $installerOutput = @(& $resolvedPython -c $installerProbe @pipAliasNames 2>&1)
        $installerExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($installerExitCode -ne 0) {
        $preview = ($installerOutput | Select-Object -First 10 | Out-String).Trim()
        throw "Could not verify package ownership for Conda/pip inventory aliases in '$resolvedPrefix'.`n$preview"
    }
    $nonCondaInstallers = @(
        $installerOutput |
            ForEach-Object { $_.ToString().Trim() } |
            Where-Object { $_ -notmatch "`tconda$" }
    )
    if ($nonCondaInstallers) {
        $preview = ($nonCondaInstallers | Select-Object -First 10 | Out-String).Trim()
        throw "Conda environment '$resolvedPrefix' contains distributions installed by pip instead of the release lock.`n$preview"
    }
}

$previousPythonUtf8 = $env:PYTHONUTF8
try {
    $env:PYTHONUTF8 = "1"
    $ErrorActionPreference = "Continue"
    $doctorOutput = @(
        & conda doctor --prefix $resolvedPrefix altered-files missing-files 2>&1
    )
    $doctorExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
    if ($null -eq $previousPythonUtf8) {
        Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONUTF8 = $previousPythonUtf8
    }
}
$doctorText = ($doctorOutput | Out-String).Trim()
if (
    $doctorExitCode -ne 0 -or
    $doctorText -notmatch '(?i)no packages with altered files' -or
    $doctorText -notmatch '(?i)no packages with missing files'
) {
    $preview = ($doctorOutput | Select-Object -First 20 | Out-String).Trim()
    throw "Conda file-integrity checks failed for '$resolvedPrefix'.`n$preview"
}

try {
    $ErrorActionPreference = "Continue"
    $pipCheckOutput = @(& $resolvedPython -m pip check 2>&1)
    $pipCheckExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($pipCheckExitCode -ne 0) {
    $preview = ($pipCheckOutput | Select-Object -First 10 | Out-String).Trim()
    throw "pip check failed in the locked Conda environment '$resolvedPrefix'.`n$preview"
}

Write-Host "Release environment matches '$resolvedLockPath' exactly ($($expected.Count) packages; pip check passed)."
