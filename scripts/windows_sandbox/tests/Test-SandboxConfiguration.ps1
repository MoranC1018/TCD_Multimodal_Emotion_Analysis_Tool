[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$TestDirectory)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$scriptRoot = Split-Path -Parent $PSScriptRoot
$generator = Join-Path $scriptRoot 'New-InstallSandbox.ps1'
$common = Join-Path $scriptRoot 'Sandbox.Common.ps1'
if (-not (Test-Path -LiteralPath $generator)) { throw 'Missing Sandbox configuration generator.' }
if (-not (Test-Path -LiteralPath $common)) { throw 'Missing Sandbox validation helpers.' }
. $common
$testRoot = Join-Path $TestDirectory ('sandbox-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$sha = '9d8d9e04ca4c84aa4d0e0de1807aa8048629df57'
$passed = 0

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Assert-Rejected([scriptblock]$Action, [string]$Message) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-True $rejected $Message
}

# A missing XML escape or accidental whole-workspace mapping must fail here.
$runPath = Join-Path $testRoot "Run & O'Brien"
$result = & $generator -Commit $sha -RunDirectory $runPath -SkipRemoteValidation
$xml = [xml](Get-Content -LiteralPath $result.ConfigurationPath -Raw)
$maps = @($xml.Configuration.MappedFolders.MappedFolder)
Assert-True ($maps.Count -eq 2) 'Only the task bootstrap and task evidence may be mapped.'
Assert-True ($maps[0].HostFolder -ceq (Join-Path $runPath 'bootstrap')) 'Bootstrap path did not round-trip through XML.'
Assert-True ($maps[0].ReadOnly -ceq 'true') 'Bootstrap must be read-only.'
Assert-True ($maps[0].SandboxFolder -ceq 'C:\SandboxBootstrap') 'Wrong guest bootstrap path.'
Assert-True ($maps[1].HostFolder -ceq (Join-Path $runPath 'evidence')) 'Evidence mapping points outside the task.'
Assert-True ($maps[1].ReadOnly -ceq 'false') 'Evidence must survive Sandbox disposal.'
Assert-True ($maps[1].SandboxFolder -ceq 'C:\Evidence') 'Wrong guest evidence path.'
Assert-True ($xml.Configuration.ClipboardRedirection -ceq 'Disable') 'Host clipboard should not be exposed.'
Assert-True ($xml.Configuration.MemoryInMB -eq '6144') 'Guest memory budget changed.'
Assert-True ($xml.Configuration.Networking -ceq 'Enable') 'The fresh guest needs download access.'
$bootstrapFiles = @(Get-ChildItem -LiteralPath (Join-Path $runPath 'bootstrap') -File | Select-Object -ExpandProperty Name | Sort-Object)
Assert-True (($bootstrapFiles -join ',') -ceq 'bootstrap-artifacts.json,Guest-Bootstrap.ps1,install_winget.ps1,run.json,Sandbox.Common.ps1') 'Unapproved files leaked into the mapped bootstrap.'
$passed++

# Reusing a run must never overwrite collected evidence or bootstrap state.
$sentinel = Join-Path $runPath 'evidence\keep.txt'
Set-Content -LiteralPath $sentinel -Value 'existing evidence' -Encoding UTF8
$before = (Get-FileHash -LiteralPath $result.ConfigurationPath).Hash
Assert-Rejected { & $generator -Commit $sha -RunDirectory $runPath -SkipRemoteValidation } 'Existing run was overwritten.'
Assert-True ((Get-Content -LiteralPath $sentinel -Raw).Trim() -ceq 'existing evidence') 'Existing evidence was modified.'
Assert-True ((Get-FileHash -LiteralPath $result.ConfigurationPath).Hash -ceq $before) 'Existing configuration was modified.'
$passed++

# These values would be ambiguous or could inject an unwanted Git destination.
foreach ($badSha in @('main', 'HEAD', ('a' * 39), ('g' * 40), '--upload-pack=evil', ($sha + "`n"))) {
    $invalidPath = Join-Path $testRoot ([guid]::NewGuid().ToString('N'))
    Assert-Rejected { & $generator -Commit $badSha -RunDirectory $invalidPath -SkipRemoteValidation } 'A non-SHA revision was accepted.'
    Assert-True (-not (Test-Path -LiteralPath $invalidPath)) 'Invalid revision created a partial run.'
}
$passed++
foreach ($badUrl in @('https://github.com.evil.example/a/b', 'https://token@github.com/a/b', 'file:///C:/private', 'https://github.com/a/b?token=secret', "https://github.com/a/b`n")) {
    $invalidPath = Join-Path $testRoot ([guid]::NewGuid().ToString('N'))
    Assert-Rejected { & $generator -Commit $sha -RepositoryUrl $badUrl -RunDirectory $invalidPath -SkipRemoteValidation } 'A non-public GitHub URL was accepted.'
    Assert-True (-not (Test-Path -LiteralPath $invalidPath)) 'Invalid URL created a partial run.'
}
$passed++

# WSB expands percent environment variables even in XML-escaped paths.
Assert-Rejected { & $generator -Commit $sha -RunDirectory (Join-Path $testRoot '%USERPROFILE%') -SkipRemoteValidation } 'Expandable mapped path was accepted.'
$passed++

# A corrupted installer must be rejected before execution.
$artifact = Join-Path $testRoot 'artifact.bin'
[IO.File]::WriteAllText($artifact, 'abc', [Text.UTF8Encoding]::new($false))
Assert-SandboxArtifactHash -Path $artifact -ExpectedSha256 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
Assert-Rejected { Assert-SandboxArtifactHash -Path $artifact -ExpectedSha256 ('0' * 64) } 'Hash mismatch was accepted.'
$passed++

# Test the environment guard itself; this never calls an installer.
if ([Security.Principal.WindowsIdentity]::GetCurrent().Name -notmatch '\\WDAGUtilityAccount$') {
    $priorActions = $env:GITHUB_ACTIONS
    $priorRunner = $env:RUNNER_ENVIRONMENT
    try {
        $env:GITHUB_ACTIONS = 'false'
        Assert-Rejected { Assert-InstallationTestEnvironment } 'An ordinary host was accepted for installation.'
        $env:GITHUB_ACTIONS = 'true'
        $env:RUNNER_ENVIRONMENT = 'self-hosted'
        Assert-Rejected { Assert-InstallationTestEnvironment } 'A persistent self-hosted runner was accepted for installation.'
        $env:RUNNER_ENVIRONMENT = 'github-hosted'
        Assert-InstallationTestEnvironment
        Assert-Rejected { Assert-InstallationTestEnvironment -SandboxOnly } 'Hosted CI was accepted as a Sandbox guest.'
    }
    finally { $env:GITHUB_ACTIONS = $priorActions; $env:RUNNER_ENVIRONMENT = $priorRunner }
    $passed++
}

# Exercise Windows argument quoting with the real PowerShell executable.
$echoScript = Join-Path $testRoot 'echo argument.ps1'
Set-Content -LiteralPath $echoScript -Value 'param([string]$Value); [Console]::WriteLine($Value)' -Encoding UTF8
$argumentValue = 'C:\A folder & O''Brien\"quoted"\'
$echoResult = Invoke-SandboxProcess -Executable 'powershell.exe' -Arguments @('-NoProfile', '-File', $echoScript, '-Value', $argumentValue) -TimeoutSeconds 15 -LogDirectory (Join-Path $testRoot 'argument-logs')
Assert-True ($echoResult.ExitCode -eq 0 -and -not $echoResult.TimedOut) 'Quoted argument child failed.'
Assert-True ((Get-Content -LiteralPath $echoResult.StandardOutput -Raw).Trim() -ceq $argumentValue) 'Native argument quoting changed the payload.'
$passed++

# A timeout must terminate this test's own PowerShell child and grandchild.
$pidFile = Join-Path $testRoot 'grandchild.pid'
$heartbeat = Join-Path $testRoot 'grandchild-heartbeat.txt'
$heartbeatLiteral = $heartbeat.Replace("'", "''")
$grandchildCode = "`$deadline = [DateTime]::UtcNow.AddSeconds(30); while ([DateTime]::UtcNow -lt `$deadline) { Set-Content -LiteralPath '$heartbeatLiteral' -Value ([DateTime]::UtcNow.ToString('o')); Start-Sleep -Milliseconds 100 }"
$encodedGrandchild = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($grandchildCode))
$parentScript = Join-Path $testRoot 'timeout-parent.ps1'
$parentCode = @'
$child = Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-EncodedCommand', '__ENCODED__') -PassThru -WindowStyle Hidden
Set-Content -LiteralPath '__PIDFILE__' -Value $child.Id
$deadline = [DateTime]::UtcNow.AddSeconds(30)
while ([DateTime]::UtcNow -lt $deadline) { Start-Sleep -Seconds 1 }
'@
$parentCode = $parentCode.Replace('__ENCODED__', $encodedGrandchild).Replace('__PIDFILE__', $pidFile.Replace("'", "''"))
Set-Content -LiteralPath $parentScript -Value $parentCode -Encoding UTF8
$timeoutResult = Invoke-SandboxProcess -Executable powershell.exe -Arguments @('-NoProfile', '-File', $parentScript) -TimeoutSeconds 5 -LogDirectory (Join-Path $testRoot 'timeout-logs')
Assert-True $timeoutResult.TimedOut 'A hung child did not time out.'
Assert-True ($timeoutResult.TerminationExitCode -eq 0) 'Owned child-tree termination failed.'
Assert-True (Test-Path -LiteralPath $heartbeat) 'Timeout test did not start the grandchild workload.'
$grandchildId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
Assert-True ($null -eq (Get-Process -Id $grandchildId -ErrorAction SilentlyContinue)) 'Grandchild survived timeout.'
Assert-True ($null -eq (Get-Process -Id $timeoutResult.ProcessId -ErrorAction SilentlyContinue)) 'Parent survived timeout.'
Assert-True (Test-Path -LiteralPath (Join-Path $testRoot 'timeout-logs\process-status.json')) 'Timeout evidence was not preserved.'
$passed++

$scripts = @(Get-ChildItem -LiteralPath $scriptRoot -Filter '*.ps1' -Recurse)
foreach ($scriptFile in $scripts) {
    $tokens = $null
    $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($scriptFile.FullName, [ref]$tokens, [ref]$parseErrors)
    Assert-True ($parseErrors.Count -eq 0) ("PowerShell parse error in {0}: {1}" -f $scriptFile.Name, ($parseErrors -join '; '))
}
$passed++

[pscustomobject]@{ Passed = $passed; ScriptsParsed = $scripts.Count; TestRoot = $testRoot } | ConvertTo-Json
