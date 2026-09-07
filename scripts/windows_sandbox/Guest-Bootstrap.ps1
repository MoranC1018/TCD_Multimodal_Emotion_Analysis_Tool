<#
.SYNOPSIS
Runs the fresh public-clone installation test inside Windows Sandbox only.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Sandbox.Common.ps1')
# Check before creating files or downloading/installing anything.
Assert-InstallationTestEnvironment -SandboxOnly
$evidence = 'C:\Evidence'
if (-not (Test-Path -LiteralPath $evidence -PathType Container)) { throw 'Dedicated evidence mapping is missing.' }
$attempt = New-SandboxEvidenceAttempt -EvidenceDirectory (Join-Path $evidence 'bootstrap-evidence') -Prefix 'guest-bootstrap'
$statusPath = Join-Path $attempt 'status.json'
$status = [ordered]@{ SchemaVersion = 1; StartedUtc = [DateTime]::UtcNow.ToString('o'); Status = 'Running'; Stage = 'Baseline'; EnvironmentKind = 'WindowsSandbox'; EvidenceDirectory = $attempt }
$exitCode = 1
$transcribing = $false
try {
    Start-Transcript -LiteralPath (Join-Path $attempt 'transcript.txt') | Out-Null
    $transcribing = $true
    Save-SandboxJson -Value $status -Path $statusPath
    $run = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'run.json') -Raw | ConvertFrom-Json
    $repository = Get-SandboxRepository -RepositoryUrl $run.RepositoryUrl -Commit $run.Commit
    $status.Repository = $repository
    $status.Baseline = [ordered]@{
        Windows = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture,FreePhysicalMemory
        Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        Commands = @(Get-Command git.exe,winget.exe,python.exe,java.exe,ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object Name,Source)
        AppInstaller = @(Get-AppxPackage -Name Microsoft.DesktopAppInstaller | Select-Object Name,Version)
        MicrosoftStore = @(Get-AppxPackage -Name Microsoft.WindowsStore | Select-Object Name,Version)
    }
    Save-SandboxJson -Value $status -Path $statusPath
    if (Test-Path -LiteralPath (Join-Path $evidence 'validation')) { throw 'Validation evidence already exists. Generate a new run directory and fresh Sandbox.' }
    if (Test-Path -LiteralPath 'C:\InstallTest') { throw 'Guest work directory already exists. Start a fresh Sandbox.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    $status.Stage = 'WinGetPrerequisite'
    Save-SandboxJson -Value $status -Path $statusPath
    Invoke-SandboxNative -Executable powershell.exe -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'install_winget.ps1'), '-EvidenceDirectory', (Join-Path $evidence 'bootstrap-evidence')) -TimeoutSeconds 1800 -LogDirectory (Join-Path $attempt 'winget-process') | Out-Host
    $winget = Get-WorkingWinGet
    if ($null -eq $winget) { throw 'WinGet prerequisite failed.' }
    $env:PATH = (Split-Path -Parent $winget.Path) + ';' + $env:PATH

    $status.Stage = 'GitPrerequisite'
    Save-SandboxJson -Value $status -Path $statusPath
    $pins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'bootstrap-artifacts.json') -Raw | ConvertFrom-Json
    $downloadDirectory = Join-Path $env:TEMP ('git-bootstrap-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $downloadDirectory | Out-Null
    $gitInstaller = Receive-SandboxArtifact -Artifact $pins.Git -Directory $downloadDirectory
    $signature = Get-AuthenticodeSignature -LiteralPath $gitInstaller
    $status.GitArtifact = [ordered]@{ Pin = $pins.Git; SignatureStatus = [string]$signature.Status; Signer = $null }
    if ($null -ne $signature.SignerCertificate) { $status.GitArtifact.Signer = $signature.SignerCertificate.Subject }
    Save-SandboxJson -Value $status -Path $statusPath
    if ($signature.Status -ne 'Valid') { throw "Git installer Authenticode signature is not valid: $($signature.Status)" }
    $gitLog = Join-Path $attempt 'git-install.log'
    $process = Invoke-SandboxProcess -Executable $gitInstaller -Arguments @('/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', ('/LOG=' + $gitLog)) -TimeoutSeconds 600 -LogDirectory (Join-Path $attempt 'git-installer-process')
    $status.GitInstallerExitCode = $process.ExitCode
    if ($process.TimedOut) { throw 'Git prerequisite installation exceeded 10 minutes. Inspect preserved process and termination logs.' }
    if ($process.ExitCode -ne 0) { throw "Git prerequisite installer failed with exit $($process.ExitCode)." }
    $git = 'C:\Program Files\Git\cmd\git.exe'
    if (-not (Test-Path -LiteralPath $git)) { throw 'Git prerequisite executable is missing.' }
    $env:PATH = (Split-Path -Parent $git) + ';' + $env:PATH
    $status.GitVersion = @(Invoke-SandboxNative -Executable $git -Arguments @('--version'))
    $status.GitLfsVersion = @(Invoke-SandboxNative -Executable $git -Arguments @('lfs', 'version'))

    $status.Stage = 'PublicClone'
    Save-SandboxJson -Value $status -Path $statusPath
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'Never'
    $env:GIT_CONFIG_NOSYSTEM = '1'
    $env:GIT_CONFIG_GLOBAL = 'NUL'
    $env:GIT_LFS_SKIP_SMUDGE = '1'
    New-Item -ItemType Directory -Path 'C:\InstallTest' | Out-Null
    $clone = 'C:\InstallTest\source'
    Invoke-SandboxNative -Executable $git -Arguments @('clone', '--filter=blob:none', '--no-checkout', $repository.Url, $clone) -TimeoutSeconds 900 -LogDirectory (Join-Path $attempt 'git-clone-process') | Out-Host
    Invoke-SandboxNative -Executable $git -Arguments @('-C', $clone, 'fetch', '--depth=1', 'origin', $repository.Commit) -TimeoutSeconds 600 -LogDirectory (Join-Path $attempt 'git-fetch-process') | Out-Host
    Invoke-SandboxNative -Executable $git -Arguments @('-C', $clone, 'checkout', '--detach', $repository.Commit) -TimeoutSeconds 900 -LogDirectory (Join-Path $attempt 'git-checkout-process') | Out-Host
    $actualCommit = (@(Invoke-SandboxNative -Executable $git -Arguments @('-C', $clone, 'rev-parse', 'HEAD')) -join '').Trim()
    if ($actualCommit -ine $repository.Commit) { throw "Checkout mismatch: expected $($repository.Commit), got $actualCommit." }
    $dirty = @(Invoke-SandboxNative -Executable $git -Arguments @('-C', $clone, 'status', '--porcelain'))
    if ($dirty.Count -ne 0) { throw 'Fresh public clone is unexpectedly dirty.' }
    $status.ActualCommit = $actualCommit
    $status.LfsSmudgeSkipped = $true
    $harness = Join-Path $clone 'scripts\test_windows_install.ps1'
    if (-not (Test-Path -LiteralPath $harness -PathType Leaf)) { throw 'Target public commit lacks scripts/test_windows_install.ps1.' }
    $status.Stage = 'RepositoryInstallationValidation'
    Save-SandboxJson -Value $status -Path $statusPath
    Push-Location $clone
    try {
        $harnessProcess = Invoke-SandboxProcess -Executable powershell.exe -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $harness, '-EvidenceDirectory', 'C:\Evidence\validation', '-EnvironmentKind', 'WindowsSandbox') -TimeoutSeconds 7200 -LogDirectory (Join-Path $attempt 'validation-process')
    }
    finally { Pop-Location }
    $status.HarnessProcess = $harnessProcess
    if ($harnessProcess.TimedOut) { throw 'Repository installation validation exceeded 120 minutes. Inspect validation-process and termination logs.' }
    $exitCode = $harnessProcess.ExitCode
    $status.HarnessExitCode = $exitCode
    if ($exitCode -ne 0) { throw "Repository installation validation failed with exit $exitCode. Inspect C:\Evidence\validation." }
    $status.Status = 'Passed'
}
catch {
    $status.Status = 'Failed'
    $status.Error = $_.Exception.Message
    if ($exitCode -eq 0) { $exitCode = 1 }
    Write-Host $status.Error
}
finally {
    $status.FinishedUtc = [DateTime]::UtcNow.ToString('o')
    $status.ExitCode = $exitCode
    Save-SandboxJson -Value $status -Path $statusPath
    Save-SandboxJson -Value $status -Path (Join-Path $evidence 'guest-status.json')
    if ($transcribing) { Stop-Transcript | Out-Null }
}
Write-Host "Guest finished with $($status.Status). Evidence: $attempt. Close Sandbox after reviewing the host evidence folder."
exit $exitCode
