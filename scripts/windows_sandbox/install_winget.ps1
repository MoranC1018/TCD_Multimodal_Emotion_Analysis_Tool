<#
.SYNOPSIS
Bootstraps WinGet in a Windows x64 installation-test guest, with separate evidence.
.DESCRIPTION
Restricted to Windows Sandbox's WDAGUtilityAccount or a GitHub-hosted Actions runner.
Downloads pinned official release artifacts only when no working WinGet exists.
The script does not restart Windows. Run in Windows PowerShell 5.1.
#>
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$EvidenceDirectory)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Sandbox.Common.ps1')
Assert-InstallationTestEnvironment
$attempt = New-SandboxEvidenceAttempt -EvidenceDirectory $EvidenceDirectory -Prefix 'winget-bootstrap'
$statusPath = Join-Path $attempt 'status.json'
$status = [ordered]@{ SchemaVersion = 1; StartedUtc = [DateTime]::UtcNow.ToString('o'); Status = 'Running'; Stage = 'Baseline'; Bootstrapped = $false; EvidenceDirectory = $attempt }
$transcribing = $false
$exitCode = 1
try {
    Start-Transcript -LiteralPath (Join-Path $attempt 'transcript.txt') | Out-Null
    $transcribing = $true
    Save-SandboxJson -Value $status -Path $statusPath
    $existing = Get-WorkingWinGet
    $status.Baseline = $existing
    if ($null -eq $existing) {
        $status.Stage = 'PinnedArtifactDownload'
        Save-SandboxJson -Value $status -Path $statusPath
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'bootstrap-artifacts.json') -Raw | ConvertFrom-Json
        Save-SandboxJson -Value $manifest -Path (Join-Path $attempt 'artifact-pins.json')
        $downloadDirectory = Join-Path $env:TEMP ('winget-bootstrap-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
        $bundle = Receive-SandboxArtifact -Artifact $manifest.WinGet -Directory $downloadDirectory
        $dependencyZip = Receive-SandboxArtifact -Artifact $manifest.WinGetDependencies -Directory $downloadDirectory
        $status.VerifiedDownloads = @($manifest.WinGet, $manifest.WinGetDependencies)
        $status.Stage = 'AppxInstallation'
        Save-SandboxJson -Value $status -Path $statusPath
        $dependencies = Join-Path $downloadDirectory 'dependencies'
        Expand-Archive -LiteralPath $dependencyZip -DestinationPath $dependencies
        $dependencyPaths = @(Get-ChildItem -LiteralPath (Join-Path $dependencies 'x64') -Filter '*.appx' -File | Select-Object -ExpandProperty FullName)
        if ($dependencyPaths.Count -ne 3) { throw 'Pinned WinGet dependency archive has an unexpected x64 package count.' }
        # Appx deployment validates Microsoft package signatures; do not bypass it.
        Add-AppxPackage -Path $bundle -DependencyPath $dependencyPaths -ErrorAction Stop
        $status.Bootstrapped = $true
    }
    $status.Stage = 'VerifyWinGet'
    $working = Get-WorkingWinGet
    if ($null -eq $working) { throw 'WinGet is still unavailable after bootstrap.' }
    $env:PATH = (Split-Path -Parent $working.Path) + ';' + $env:PATH
    $status.Result = $working
    $status.AppInstaller = @(Get-AppxPackage -Name Microsoft.DesktopAppInstaller | Select-Object Name,Version,Publisher,SignatureKind,Status,InstallLocation)
    $status.Status = 'Passed'
    $exitCode = 0
}
catch {
    $status.Status = 'Failed'
    $status.Error = $_.Exception.Message
    Write-Host $status.Error
}
finally {
    $status.FinishedUtc = [DateTime]::UtcNow.ToString('o')
    $status.ExitCode = $exitCode
    Save-SandboxJson -Value $status -Path $statusPath
    if ($transcribing) { Stop-Transcript | Out-Null }
}
Write-Output ([pscustomobject]$status)
if ($exitCode -ne 0) { exit $exitCode }
