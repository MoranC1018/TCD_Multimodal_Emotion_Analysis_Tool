<#
.SYNOPSIS
Runs the public installer and acceptance checks in a disposable Windows machine.
.DESCRIPTION
Requires a fresh checkout without .venv. Git and WinGet are prerequisites.
Hosted images provide Python/JDK; Sandbox exercises their installer fallbacks.
EvidenceDirectory must be new and outside the repository. This harness installs
software only in GitHub Actions or the default Windows Sandbox user session.
#>
[CmdletBinding()]
param(
    [string]$EvidenceDirectory,
    [ValidateSet('GitHubHosted', 'WindowsSandbox')]
    [string]$EnvironmentKind = 'GitHubHosted',
    [switch]$RunRegression,
    [switch]$RunBrowser,
    [switch]$InventoryOnly,
    [Parameter(DontShow = $true)]
    [switch]$FunctionsOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-InstallTestJson {
    param([string]$Path, [object]$Value)
    $json = ConvertTo-Json -InputObject $Value -Depth 15
    [IO.File]::WriteAllText($Path, $json, [Text.UTF8Encoding]::new($false))
}

function New-InstallTestEvidence {
    param([string]$Path, [string]$Repository)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not [IO.Path]::IsPathRooted($Path)) {
        throw 'EvidenceDirectory must be an absolute path to a new directory.'
    }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $repo = [IO.Path]::GetFullPath($Repository).TrimEnd('\', '/')
    if ($full.Equals($repo, [StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Installation evidence must be outside the repository.'
    }
    if (Test-Path -LiteralPath $full) { throw 'Evidence directory already exists; preserve it and use a new path.' }
    $ancestor = Split-Path -Parent $full
    while ($ancestor) {
        if (Test-Path -LiteralPath $ancestor) {
            $item = Get-Item -LiteralPath $ancestor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Evidence path must not pass through a reparse point.'
            }
        }
        $next = Split-Path -Parent $ancestor
        if ($next -eq $ancestor) { break }
        $ancestor = $next
    }
    [void](New-Item -ItemType Directory -Path $full -ErrorAction Stop)
    return $full
}

function Invoke-InstallTestCommand {
    param(
        [ValidatePattern('^[a-z0-9][a-z0-9-]{0,60}$')][string]$Name,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$ReportDirectory
    )
    $log = Join-Path $ReportDirectory "$Name.log"
    $record = Join-Path $ReportDirectory "$Name.command.json"
    if ((Test-Path -LiteralPath $log) -or (Test-Path -LiteralPath $record)) {
        throw "Evidence for $Name already exists."
    }
    $started = [DateTime]::UtcNow
    $result = [ordered]@{
        name = $Name; executable = $Executable; arguments = @($Arguments)
        started_utc = $started.ToString('o'); state = 'running'; exit_code = $null
        finished_utc = $null; seconds = $null; error = $null
    }
    Write-InstallTestJson -Path $record -Value $result
    $writer = [IO.StreamWriter]::new($log, $false, [Text.UTF8Encoding]::new($false))
    $previousPreference = $ErrorActionPreference
    try {
        Write-Host "Running installation check: $Name"
        # Native stderr is data in Windows PowerShell; command exit determines failure.
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = 0
        & $Executable @Arguments 2>&1 | ForEach-Object {
            $line = [string]$_
            $writer.WriteLine($line)
            $writer.Flush()
            Write-Host $line
        }
        $result.exit_code = $LASTEXITCODE
        if ($result.exit_code -ne 0) { throw "$Name failed with exit code $($result.exit_code)." }
        $result.state = 'passed'
    }
    catch {
        $result.state = 'failed'
        $result.error = $_.Exception.Message
        $writer.WriteLine($result.error)
        throw
    }
    finally {
        $ErrorActionPreference = $previousPreference
        $writer.Dispose()
        $finished = [DateTime]::UtcNow
        $result.finished_utc = $finished.ToString('o')
        $result.seconds = ($finished - $started).TotalSeconds
        Write-InstallTestJson -Path $record -Value $result
    }
}

function Get-InstallTestSource {
    param([string]$Repository)
    $head = & git -C $Repository rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the checked-out source commit.' }
    $files = @(& git -C $Repository -c core.quotePath=false ls-files)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate checked-out source files.' }
    $lfsFiles = @(& git -C $Repository lfs ls-files --name-only)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate Git LFS sources.' }
    $hashes = [ordered]@{}
    foreach ($file in ($files | Sort-Object)) {
        $path = Join-Path $Repository $file
        if ($file -cin $lfsFiles) {
            # The installer intentionally hydrates the tracked RockSteady pointer.
            # Its clean-filter Git identity stays equal only for the same LFS content.
            # Explicit per-command configuration also works when a clean guest
            # excludes global/system Git settings. It changes no saved config.
            $blob = & git -C $Repository -c 'filter.lfs.process=git-lfs filter-process' -c 'filter.lfs.required=true' hash-object "--path=$file" -- $path
            if ($LASTEXITCODE -ne 0) { throw "Cannot verify the LFS identity of $file." }
            $hashes[$file] = "git-clean-blob:$blob"
        }
        else {
            # .NET avoids dependence on PowerShell module autoload state when
            # this helper is called from a Python/PowerShell interoperability test.
            $stream = [IO.File]::OpenRead($path)
            $algorithm = [Security.Cryptography.SHA256]::Create()
            try {
                $hashes[$file] = 'sha256:' + ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
            }
            finally {
                $algorithm.Dispose()
                $stream.Dispose()
            }
        }
    }
    return [ordered]@{commit = [string]$head; hashes = $hashes}
}

function Assert-InstallTestEnvironment {
    param([ValidateSet('GitHubHosted', 'WindowsSandbox')][string]$Kind)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name.Split('\')[-1]
    $hosted = $env:GITHUB_ACTIONS -ceq 'true' -and $env:RUNNER_ENVIRONMENT -ceq 'github-hosted'
    if (($Kind -eq 'GitHubHosted' -and -not $hosted) -or
        ($Kind -eq 'WindowsSandbox' -and $identity -ne 'WDAGUtilityAccount')) {
        throw 'Installation testing requires the selected disposable environment; refusing a normal or self-hosted session.'
    }
}

function Get-InstallTestBaseline {
    param([string]$Repository, [string]$Kind)
    $commands = foreach ($name in @('python.exe', 'py.exe', 'java.exe', 'javac.exe', 'winget.exe', 'git.exe', 'ffmpeg.exe', 'ffprobe.exe', 'node.exe')) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            [ordered]@{name = $name; path = $command.Source}
        }
    }
    $os = Get-CimInstance Win32_OperatingSystem
    return [ordered]@{
        captured_utc = [DateTime]::UtcNow.ToString('o'); environment_kind = $Kind
        os = [ordered]@{caption = $os.Caption; version = $os.Version; architecture = $os.OSArchitecture
            total_memory_kib = $os.TotalVisibleMemorySize; available_memory_kib = $os.FreePhysicalMemory}
        identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        image_os = $env:ImageOS; image_version = $env:ImageVersion
        commands = @($commands); existing_venv = (Test-Path -LiteralPath (Join-Path $Repository '.venv'))
        source = Get-InstallTestSource -Repository $Repository
        interpretation = 'Disposable machine; prerequisites/bootstrap are recorded separately. This is not a population installation error rate.'
    }
}

if ($FunctionsOnly) { return }

$repository = Split-Path -Parent $PSScriptRoot
$evidence = New-InstallTestEvidence -Path $EvidenceDirectory -Repository $repository
$summary = [ordered]@{
    environment_kind = $EnvironmentKind; started_utc = [DateTime]::UtcNow.ToString('o')
    state = 'running'; completed_utc = $null; source_unchanged = $false; error = $null
    regression_requested = [bool]$RunRegression; browser_requested = [bool]$RunBrowser
    model_scope = 'Installer prepares/checks native Face; other component doctors check runtime readiness. CLI and browser acceptance here use no emotion/transcription model inference.'
}
$returnCode = 1
Push-Location -LiteralPath $repository
try {
    $baseline = Get-InstallTestBaseline -Repository $repository -Kind $EnvironmentKind
    Write-InstallTestJson -Path (Join-Path $evidence 'baseline.json') -Value $baseline
    if ($InventoryOnly) {
        $summary.state = 'inventory_only'
        $returnCode = 0
    }
    else {
        Assert-InstallTestEnvironment -Kind $EnvironmentKind
        if ($baseline.existing_venv) { throw 'A fresh checkout without .venv is required for an installation test.' }
        $env:PYTHONUTF8 = '1'
        $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'false'
        $env:OMP_NUM_THREADS = '4'
        $env:MKL_NUM_THREADS = '4'
        $env:OPENBLAS_NUM_THREADS = '4'
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $python = Join-Path $repository '.venv\Scripts\python.exe'
        $setupArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'setup.ps1'), '-TorchRuntime', 'cpu', '-TextMode', 'Require')
        Invoke-InstallTestCommand -Name 'setup-first' -Executable $powershell -Arguments $setupArguments -ReportDirectory $evidence
        Invoke-InstallTestCommand -Name 'setup-rerun' -Executable $powershell -Arguments $setupArguments -ReportDirectory $evidence
        # A child installer cannot update this process's PATH directly.
        $entries = foreach ($scope in @('Process', 'User', 'Machine')) {
            foreach ($entry in ([Environment]::GetEnvironmentVariable('PATH', $scope) -split ';')) {
                if ($entry) { $entry }
            }
        }
        $env:PATH = ($entries | Select-Object -Unique) -join ';'
        Invoke-InstallTestCommand -Name 'pip-check' -Executable $python -Arguments @('-m', 'pip', 'check') -ReportDirectory $evidence
        Invoke-InstallTestCommand -Name 'runtime-freeze' -Executable $python -Arguments @('-m', 'pip', 'freeze', '--all') -ReportDirectory $evidence
        $pinCheck = @'
import importlib.metadata as m, json, pathlib, sys
from packaging.requirements import Requirement
rows = []
for line in pathlib.Path('requirements.txt').read_text(encoding='utf-8').splitlines():
    if not line.strip() or line.lstrip().startswith('#'):
        continue
    requirement = Requirement(line)
    actual = m.version(requirement.name)
    rows.append({'name': requirement.name, 'required': str(requirement.specifier), 'actual': actual, 'matches': actual in requirement.specifier})
result = {'python': sys.version, 'requirements': rows, 'all_match': all(row['matches'] for row in rows)}
pathlib.Path(sys.argv[1]).write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['all_match'] and rows else 1)
'@
        Invoke-InstallTestCommand -Name 'direct-pins' -Executable $python -Arguments @('-c', $pinCheck, (Join-Path $evidence 'direct-pins.json')) -ReportDirectory $evidence
        Invoke-InstallTestCommand -Name 'installer-contracts' -Executable $powershell -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'verify_setup.ps1')) -ReportDirectory $evidence
        Invoke-InstallTestCommand -Name 'component-readiness' -Executable $python -Arguments @('-m', 'application.cli', 'doctor', '--component', 'all') -ReportDirectory $evidence
        Invoke-InstallTestCommand -Name 'cli-acceptance' -Executable $python -Arguments @('application/tests/real_cli_e2e.py', '--phase', 'nonmodel', '--output', (Join-Path $evidence 'cli-acceptance')) -ReportDirectory $evidence
        if ($RunRegression -or $RunBrowser) {
            if (-not $env:MEAP_TEST_NODE -or -not $env:MEAP_TEST_PLAYWRIGHT -or -not $env:MEAP_TEST_BROWSER_EXECUTABLE) {
                throw 'Strict hosted tests require explicit Node, Playwright and browser paths.'
            }
            $env:MEAP_STRICT_BROWSER_TESTS = '1'
        }
        if ($RunRegression) {
            Invoke-InstallTestCommand -Name 'test-dependencies' -Executable $python -Arguments @('-m', 'pip', 'install', 'pytest==9.1.1', 'jsonschema==4.26.0') -ReportDirectory $evidence
            Invoke-InstallTestCommand -Name 'full-regression' -Executable $python -Arguments @('-m', 'pytest', '-q', '-ra', '--junitxml', (Join-Path $evidence 'regression.xml'), '--basetemp', (Join-Path $evidence 'pytest-temp')) -ReportDirectory $evidence
            Invoke-InstallTestCommand -Name 'installation-harness-tests' -Executable $python -Arguments @('-m', 'pytest', '-q', 'scripts/tests', '--junitxml', (Join-Path $evidence 'installation-harness.xml')) -ReportDirectory $evidence
            Invoke-InstallTestCommand -Name 'sandbox-configuration-tests' -Executable $powershell -Arguments @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'windows_sandbox\tests\Test-SandboxConfiguration.ps1'), '-TestDirectory', (Join-Path $evidence 'sandbox-configuration-tests')) -ReportDirectory $evidence
        }
        if ($RunBrowser) {
            Invoke-InstallTestCommand -Name 'browser-acceptance' -Executable $python -Arguments @('application/tests/real_launcher_browser_e2e.py', '--output', (Join-Path $evidence 'browser-acceptance'), '--node', $env:MEAP_TEST_NODE, '--playwright', $env:MEAP_TEST_PLAYWRIGHT, '--browser', $env:MEAP_TEST_BROWSER_EXECUTABLE) -ReportDirectory $evidence
        }
        $finish = Get-InstallTestSource -Repository $repository
        Write-InstallTestJson -Path (Join-Path $evidence 'source-finish.json') -Value $finish
        $beforeJson = ConvertTo-Json -InputObject $baseline.source -Depth 5 -Compress
        $afterJson = ConvertTo-Json -InputObject $finish -Depth 5 -Compress
        if ($beforeJson -cne $afterJson) { throw 'Tracked executable sources changed during installation validation.' }
        $summary.source_unchanged = $true
        $summary.state = 'passed'
        $returnCode = 0
    }
}
catch {
    $summary.state = 'failed'
    $summary.error = $_.Exception.Message
    Write-Host "Installation validation failed: $($summary.error)"
}
finally {
    $summary.completed_utc = [DateTime]::UtcNow.ToString('o')
    Write-InstallTestJson -Path (Join-Path $evidence 'summary.json') -Value $summary
    Pop-Location
}
exit $returnCode
