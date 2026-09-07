<#
.SYNOPSIS
Optionally enables Windows Sandbox using normal administrator approval, never restarting.
.PARAMETER EvidenceDirectory
Parent directory for unique durable host-enable status and transcript folders.
.PARAMETER Elevate
Requests normal Windows UAC if the current PowerShell is not an administrator.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory,
    [switch]$Elevate,
    [Parameter(DontShow = $true)][string]$AttemptDirectory
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Sandbox.Common.ps1')
if (-not $AttemptDirectory) {
    $AttemptDirectory = New-SandboxEvidenceAttempt -EvidenceDirectory $EvidenceDirectory -Prefix 'host-enable'
}
$statusPath = Join-Path $AttemptDirectory 'status.json'
$status = [ordered]@{ SchemaVersion = 1; StartedUtc = [DateTime]::UtcNow.ToString('o'); Status = 'Running'; Feature = 'Containers-DisposableClientVM'; RestartPerformed = $false; EvidenceDirectory = $AttemptDirectory }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = [Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$status.IsAdministrator = $isAdmin
Save-SandboxJson -Value $status -Path $statusPath
if (-not $isAdmin) {
    if (-not $Elevate) {
        $status.Status = 'RequiresElevation'
        $status.FinishedUtc = [DateTime]::UtcNow.ToString('o')
        Save-SandboxJson -Value $status -Path $statusPath
        Write-Host "Administrator rights are required. Rerun with -Elevate for normal Windows UAC. Evidence: $AttemptDirectory"
        exit 1
    }
    try {
        $status.Status = 'AwaitingUac'
        Save-SandboxJson -Value $status -Path $statusPath
        # EncodedCommand avoids command-line quoting problems in spaces/apostrophes.
        $scriptLiteral = $PSCommandPath.Replace("'", "''")
        $evidenceLiteral = $EvidenceDirectory.Replace("'", "''")
        $attemptLiteral = $AttemptDirectory.Replace("'", "''")
        $command = "& '$scriptLiteral' -EvidenceDirectory '$evidenceLiteral' -AttemptDirectory '$attemptLiteral'"
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
        $child = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) -Wait -PassThru -WindowStyle Hidden
        Write-Host "Administrator step exited $($child.ExitCode). Review $statusPath. No restart was requested."
        exit $child.ExitCode
    }
    catch {
        $status.Status = 'ElevationFailedOrCancelled'
        $status.Error = $_.Exception.Message
        $status.FinishedUtc = [DateTime]::UtcNow.ToString('o')
        Save-SandboxJson -Value $status -Path $statusPath
        Write-Host $status.Error
        exit 1
    }
}
$exitCode = 1
$transcribing = $false
try {
    Start-Transcript -LiteralPath (Join-Path $AttemptDirectory 'transcript.txt') | Out-Null
    $transcribing = $true
    $before = Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM
    $status.Before = [string]$before.State
    Save-SandboxJson -Value $status -Path $statusPath
    if ($before.State -eq 'Enabled') {
        $status.Status = 'AlreadyEnabled'
        $status.After = 'Enabled'
        $status.RestartNeeded = $false
    }
    elseif ($before.State -eq 'EnablePending') {
        $status.Status = 'EnabledRestartRequired'
        $status.After = 'EnablePending'
        $status.RestartNeeded = $true
    }
    else {
        $result = Enable-WindowsOptionalFeature -FeatureName Containers-DisposableClientVM -All -Online -NoRestart
        $status.After = [string](Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM).State
        if ($status.After -notin @('Enabled', 'EnablePending')) { throw "Unexpected feature state after enabling: $($status.After)." }
        $status.RestartNeeded = ([bool]$result.RestartNeeded -or $status.After -eq 'EnablePending')
        if ($status.RestartNeeded) { $status.Status = 'EnabledRestartRequired' } else { $status.Status = 'Enabled' }
    }
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
Write-Host "Status: $($status.Status). Review $statusPath. Restart Windows manually if required."
exit $exitCode
