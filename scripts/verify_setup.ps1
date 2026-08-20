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
    "Python 3.12 package" = 'Python.Python.3.12'
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
