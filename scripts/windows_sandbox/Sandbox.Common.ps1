Set-StrictMode -Version Latest

function Get-SandboxRepository {
    param([string]$RepositoryUrl, [string]$Commit)
    if ($Commit -cnotmatch '^[0-9a-fA-F]{40}\z') {
        throw 'Commit must be the full 40-character public Git commit SHA.'
    }
    if ($RepositoryUrl -cnotmatch '^https://github\.com/([A-Za-z0-9][A-Za-z0-9_.-]*)/([A-Za-z0-9][A-Za-z0-9_.-]*?)(?:\.git)?/?\z') {
        throw 'RepositoryUrl must be a public HTTPS github.com owner/repository URL without credentials, query, or fragment.'
    }
    return [pscustomobject]@{
        Slug = "$($Matches[1])/$($Matches[2])"
        Url = "https://github.com/$($Matches[1])/$($Matches[2]).git"
        Commit = $Commit.ToLowerInvariant()
    }
}

function Assert-SandboxArtifactHash {
    param([string]$Path, [string]$ExpectedSha256)
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}\z') { throw 'Invalid pinned SHA256.' }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ine $ExpectedSha256) { throw "SHA256 mismatch for $Path. Expected $ExpectedSha256; got $actual." }
}

function Save-SandboxJson {
    param([object]$Value, [string]$Path)
    # Rewrite the current stage status while preserving transcripts and prior run directories.
    $Value | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function New-SandboxEvidenceAttempt {
    param([string]$EvidenceDirectory, [string]$Prefix)
    $parent = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($EvidenceDirectory)
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $attempt = Join-Path $parent ($Prefix + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $attempt | Out-Null
    return $attempt
}

function Assert-InstallationTestEnvironment {
    param([switch]$SandboxOnly)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $isSandbox = $identity -match '\\WDAGUtilityAccount$'
    $isHosted = $env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_ENVIRONMENT -ceq 'github-hosted'
    if (-not $isSandbox -and ($SandboxOnly -or -not $isHosted)) {
        throw 'Installation bootstrap is restricted to Windows Sandbox WDAGUtilityAccount or a GitHub-hosted Actions runner. No host installation was performed.'
    }
    if ($env:PROCESSOR_ARCHITECTURE -cne 'AMD64') { throw 'This pinned bootstrap supports Windows x64 only.' }
}

function ConvertTo-SandboxProcessArgument {
    param([AllowEmptyString()][string]$Value)
    # Windows native argv: double backslashes before embedded quotes and the final quote.
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Invoke-SandboxProcess {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [ValidateRange(1, 7200)][int]$TimeoutSeconds = 120,
        [string]$LogDirectory
    )
    if (-not $LogDirectory) { $LogDirectory = Join-Path $env:TEMP ('sandbox-process-' + [guid]::NewGuid().ToString('N')) }
    if (Test-Path -LiteralPath $LogDirectory) { throw "Process log directory already exists: $LogDirectory" }
    New-Item -ItemType Directory -Path $LogDirectory | Out-Null
    $stdout = Join-Path $LogDirectory 'stdout.log'
    $stderr = Join-Path $LogDirectory 'stderr.log'
    $statusPath = Join-Path $LogDirectory 'process-status.json'
    $status = [ordered]@{ Executable = $Executable; Arguments = $Arguments; StartedUtc = [DateTime]::UtcNow.ToString('o'); TimeoutSeconds = $TimeoutSeconds; TimedOut = $false; ExitCode = $null; ProcessId = $null; TerminationExitCode = $null; StandardOutput = $stdout; StandardError = $stderr; Status = 'Starting' }
    Save-SandboxJson -Value $status -Path $statusPath
    try {
        $argumentLine = (@($Arguments | ForEach-Object { ConvertTo-SandboxProcessArgument -Value $_ }) -join ' ')
        $process = Start-Process -FilePath $Executable -ArgumentList $argumentLine -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        # Windows PowerShell 5.1 needs the handle retained to expose ExitCode reliably.
        $null = $process.Handle
        $status.ProcessId = $process.Id
        $status.Status = 'Running'
        Save-SandboxJson -Value $status -Path $statusPath
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $status.TimedOut = $true
            $status.Status = 'TimedOut'
            Save-SandboxJson -Value $status -Path $statusPath
            # Terminate only this function's still-running child and its descendants.
            if (-not $process.HasExited) {
                $killer = Start-Process -FilePath "$env:SystemRoot\System32\taskkill.exe" -ArgumentList @('/PID', $process.Id, '/T', '/F') -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogDirectory 'termination-stdout.log') -RedirectStandardError (Join-Path $LogDirectory 'termination-stderr.log')
                $null = $killer.Handle
                if (-not $killer.WaitForExit(15000)) { $killer.Kill(); throw 'Owned process-tree termination did not finish within 15 seconds.' }
                $status.TerminationExitCode = $killer.ExitCode
                $null = $process.WaitForExit(10000)
                if ($status.TerminationExitCode -ne 0 -or -not $process.HasExited) { throw 'Owned process-tree termination failed; inspect termination logs.' }
            }
        }
        else { $status.Status = 'Exited' }
        if ($process.HasExited) {
            $status.ExitCode = $process.ExitCode
        }
    }
    catch { $status.Error = $_.Exception.Message; $status.Status = 'Failed'; throw }
    finally {
        $status.FinishedUtc = [DateTime]::UtcNow.ToString('o')
        Save-SandboxJson -Value $status -Path $statusPath
    }
    return [pscustomobject]$status
}

function Invoke-SandboxNative {
    param([string]$Executable, [string[]]$Arguments, [int]$TimeoutSeconds = 120, [string]$LogDirectory)
    $result = Invoke-SandboxProcess -Executable $Executable -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds -LogDirectory $LogDirectory
    $output = @(Get-Content -LiteralPath $result.StandardOutput) + @(Get-Content -LiteralPath $result.StandardError)
    if ($result.TimedOut) { throw "Native command timed out after $TimeoutSeconds seconds: $Executable. Logs: $($result.StandardOutput)" }
    if ($result.ExitCode -ne 0) { throw "Native command failed ($($result.ExitCode)): $Executable $($Arguments -join ' ')`n$($output -join [Environment]::NewLine)" }
    return $output
}

function Get-WorkingWinGet {
    $candidates = @()
    $command = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) { $candidates += $command.Source }
    $package = Get-AppxPackage -Name Microsoft.DesktopAppInstaller -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $package) { $candidates += (Join-Path $package.InstallLocation 'winget.exe') }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $version = @(Invoke-SandboxNative -Executable $candidate -Arguments @('--version'))
            return [pscustomobject]@{ Path = $candidate; Version = ($version -join ' ').Trim() }
        }
        catch { Write-Host "WinGet probe failed: $($_.Exception.Message)" }
    }
    return $null
}

function Receive-SandboxArtifact {
    param([object]$Artifact, [string]$Directory)
    $path = Join-Path $Directory $Artifact.FileName
    Invoke-WebRequest -UseBasicParsing -Uri $Artifact.Url -OutFile $path -TimeoutSec 600
    Assert-SandboxArtifactHash -Path $path -ExpectedSha256 $Artifact.Sha256
    return $path
}
