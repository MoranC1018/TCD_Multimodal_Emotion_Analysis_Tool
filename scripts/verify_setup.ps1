[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$setupPath = Join-Path $PSScriptRoot "setup.ps1"
$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $setupPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    $details = $parseErrors | ForEach-Object { $_.ToString() }
    throw "setup.ps1 has PowerShell parse errors:`n$($details -join "`n")"
}

$source = Get-Content -LiteralPath $setupPath -Raw
$requiredContracts = [ordered]@{
    "exact FFmpeg package" = 'Gyan.FFmpeg.Shared'
    "exact FFmpeg release" = '8.1.2'
    "JDK package with compiler" = 'EclipseAdoptium.Temurin.21.JDK'
    "Python 3.11-or-newer compatibility probe" = 'sys.version_info[:2] >= (3, 11)'
    "Python manager discovery is non-installing" = '$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = "false"'
    "compatible Python details probe" = 'function Get-CompatiblePythonDetails'
    "compatible Python validator" = 'function Test-CompatiblePython'
    "registered Python discovery" = 'function Get-RegisteredPythonCandidates'
    "non-installing Python runtime listing" = 'Arguments @("-0p")'
    "compatible Python discovery" = 'function Find-CompatiblePython'
    "Python 3.12 selection preference" = 'if ($_.Version.Major -eq 3 -and $_.Version.Minor -eq 12)'
    "compatible virtual environment reuse" = 'Reusing the existing compatible Python environment'
    "Python 3.12 automatic installation fallback" = 'Python.Python.3.12'
    "automatic Python fallback install" = 'Invoke-WinGetInstall -PackageId $pythonPackageId'
    "exact-version install guard" = 'This branch is reached only after the exact on-disk runtime'
    "WinGet noninteractive mode" = '--disable-interactivity'
    "matched Torch CPU/CUDA selector" = 'TorchRuntime'
    "automatic NVIDIA runtime selection" = 'Resolve-TorchRuntime'
    "supported NVIDIA architecture gate" = '--query-gpu=driver_version,compute_cap'
    "CUDA device usability check" = 'torch.cuda.is_available()'
    "Torch-compatible setuptools" = 'setuptools<82'
    "CPU/CUDA wheel replacement" = 'PEP 440 treats 2.11.0+cpu as satisfying torch==2.11.0'
    "Windows TorchCodec CPU wheel" = 'TorchCodec 0.13 does not publish a Windows cu128 wheel'
    "pip dependency validation" = '"pip", "check"'
    "explicit Face model preparation" = '"processing.face_analysis", "--prepare-models"'
    "offline Face readiness smoke" = '"processing.face_analysis", "--check"'
    "Text readiness check" = '"processing.text_analysis", "--check"'
    "licensed JAR gate" = 'rocksteady-desktop-application-0.4#2018-05-16.jar'
    "explicit Text policy" = 'ValidateSet("Auto", "Require", "Skip")'
    "Independent Face handoff" = 'processing.face_analysis Videos'
    "Independent Text handoff" = 'processing.text_analysis Videos'
}
foreach ($contract in $requiredContracts.GetEnumerator()) {
    if (-not $source.Contains([string]$contract.Value)) {
        throw "setup.ps1 is missing the $($contract.Key) contract: $($contract.Value)"
    }
}
$forbiddenPythonContracts = [ordered]@{
    "exact Python 3.12 version gate" = 'sys.version_info[:2] == (3, 12)'
    "exact Python 3.12 validator" = 'function Test-Python312'
    "exact Python 3.12 discovery" = 'function Find-Python312'
    "exact Python 3.12 confirmation" = 'function Confirm-Python312'
    "side-effectful Python 3.12 launcher probe" = '"-3.12", "-c"'
    "side-effectful generic Python launcher probe" = '"-3", "-c"'
}
foreach ($contract in $forbiddenPythonContracts.GetEnumerator()) {
    if ($source.Contains([string]$contract.Value)) {
        throw "setup.ps1 retains the $($contract.Key) contract: $($contract.Value)"
    }
}
$nonInstallingIndex = $source.IndexOf('$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = "false"')
$discoveryIndex = $source.IndexOf('function Find-CompatiblePython')
if ($nonInstallingIndex -lt 0 -or $discoveryIndex -le $nonInstallingIndex) {
    throw "setup.ps1 must disable Python Manager auto-install before interpreter discovery."
}
if ($source -match 'sys\.version_info(?:\[:2\])?\s*(?:<|<=)\s*\(') {
    throw "setup.ps1 must not impose an upper Python version gate."
}
$pythonFallbackCount = [regex]::Matches(
    $source,
    'Invoke-WinGetInstall\s+-PackageId\s+\$pythonPackageId'
).Count
if ($pythonFallbackCount -ne 1) {
    throw "setup.ps1 must have exactly one explicit Python WinGet fallback."
}
$prepareModelsIndex = $source.IndexOf('"processing.face_analysis", "--prepare-models"')
$offlineCheckIndex = $source.IndexOf('"processing.face_analysis", "--check"')
if ($prepareModelsIndex -lt 0 -or $offlineCheckIndex -le $prepareModelsIndex) {
    throw "setup.ps1 must explicitly prepare Face models before its offline readiness check."
}
if ($source -match '(?m)^\s*&\s+winget\b') {
    throw "setup.ps1 must invoke the resolved WinGet executable through checked error handling."
}
if (-not $source.Contains('@("--version", $Version, "--force")')) {
    throw "setup.ps1 must be able to replace a different FFmpeg version after exact detection fails."
}

Write-Host "setup.ps1 static verification passed: parse + installation/readiness contracts."
