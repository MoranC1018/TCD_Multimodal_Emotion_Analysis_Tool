<#
.SYNOPSIS
Installs and validates the single supported Windows environment.

.DESCRIPTION
The default setup makes Face processing ready and also validates Text when the
licensed RockSteady JAR is present. The pinned stack requires Python 3.11 or
newer. Python 3.12 is tested and recommended, while other compatible versions
are accepted. The script is safe to rerun: it reuses a compatible environment
and installs FFmpeg only when the exact supported 8.1.2 full-shared runtime is
absent. If no compatible Python is installed, the automatic fallback installs
Python 3.12.

.PARAMETER TorchRuntime
Use auto (default), cpu, or the matched CUDA 12.8 PyTorch package family.
Auto selects CUDA when a compatible NVIDIA GPU/driver is available and CPU
otherwise.

.PARAMETER TextMode
Auto leaves an honest Face-only installation when the licensed JAR is absent;
Require treats that as an error; Skip explicitly omits JDK/Text setup.

.PARAMETER SkipSharedFfmpeg
Do not install FFmpeg. The exact-runtime validation and Face smoke still run.

.PARAMETER SkipPythonInstall
Do not install the Python 3.12 fallback when no compatible Python is present;
fail with an explicit prerequisite instead.

.PARAMETER SkipJdkInstall
Do not install a JDK when Text needs one; fail unless java and javac already work.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -TorchRuntime cu128 -TextMode Require
#>
[CmdletBinding()]
param(
    [ValidateSet("auto", "cpu", "cu128")]
    [string]$TorchRuntime = "auto",

    # Auto validates Text when the licensed JAR is present and otherwise leaves
    # an honest Face-only installation. Require makes a missing JAR fatal;
    # Skip explicitly opts out of the JDK and Text readiness checks.
    [ValidateSet("Auto", "Require", "Skip")]
    [string]$TextMode = "Auto",

    # This skips installation, not validation. Face readiness still fails if a
    # complete FFmpeg 8.1.2 shared runtime cannot be found.
    [switch]$SkipSharedFfmpeg,

    # Useful on managed machines where software installation is performed by
    # IT. The corresponding runtime checks are never silently skipped.
    [switch]$SkipPythonInstall,
    [switch]$SkipJdkInstall,

    # Internal verification hook: load function definitions without performing
    # installations. Hidden from normal help and used by verify_setup.ps1.
    [Parameter(DontShow = $true)]
    [switch]$FunctionsOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $environmentPath "Scripts\python.exe"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$rockSteadyJarName = "rocksteady-desktop-application-0.4#2018-05-16.jar"
$rockSteadyJar = Join-Path $projectRoot "external\RockSteady\$rockSteadyJarName"
$ffmpegVersion = "8.1.2"
$ffmpegPackageId = "Gyan.FFmpeg.Shared"
$jdkPackageId = "EclipseAdoptium.Temurin.21.JDK"
$pythonPackageId = "Python.Python.3.12"
$minimumCu128WindowsDriver = [version]"528.33"
$minimumCu128ComputeCapability = [version]"7.5"

# Discovery must never let the current Python Install Manager auto-install a
# runtime. Confirm-CompatiblePython owns the sole installation fallback below.
$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = "false"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage,
        [switch]$AllowNonZeroExit,
        [switch]$PassThru
    )

    try {
        # Out-Host prevents command output from accidentally becoming a
        # function return value when a caller is resolving a path.
        & $Executable @Arguments | Out-Host
        $exitCode = $LASTEXITCODE
    }
    catch {
        throw "$FailureMessage $($_.Exception.Message)"
    }
    if ($exitCode -ne 0 -and -not $AllowNonZeroExit) {
        throw "$FailureMessage (exit code $exitCode)."
    }
    if ($PassThru) {
        return [int]$exitCode
    }
}

function Invoke-NativeProbe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    # Windows PowerShell turns redirected native stderr into ErrorRecords. With
    # the script-wide Stop preference, ordinary probes such as `java -version`
    # would otherwise terminate setup even when the process exits successfully.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Executable @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = @($output | ForEach-Object { [string]$_ })
        }
    }
    catch {
        return [pscustomobject]@{
            ExitCode = -1
            Output = @([string]$_.Exception.Message)
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-WinGetPath {
    $command = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw (
            "WinGet is required for automatic prerequisite installation. " +
            "Install Microsoft's App Installer, or rerun with the relevant " +
            "-Skip*Install option after your administrator installs the prerequisite."
        )
    }
    return $command.Source
}

function Resolve-TorchRuntime {
    param([Parameter(Mandatory = $true)][string]$RequestedRuntime)

    if ($RequestedRuntime -ne "auto") {
        return $RequestedRuntime
    }

    $nvidiaSmi = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if ($null -eq $nvidiaSmi) {
        Write-Host "No NVIDIA GPU runtime was detected; selecting CPU PyTorch."
        return "cpu"
    }
    $probe = Invoke-NativeProbe -Executable $nvidiaSmi.Source -Arguments @(
        "--query-gpu=driver_version,compute_cap",
        "--format=csv,noheader"
    )
    if ($probe.ExitCode -ne 0) {
        Write-Warning "NVIDIA telemetry did not report a usable GPU/driver; selecting CPU PyTorch."
        return "cpu"
    }
    foreach ($line in $probe.Output) {
        $fields = @([string]$line -split ",")
        if ($fields.Count -lt 2) {
            continue
        }
        $driverMatch = [regex]::Match($fields[0], "\d+(?:\.\d+)+")
        $capabilityMatch = [regex]::Match($fields[1], "\d+(?:\.\d+)+")
        if (-not $driverMatch.Success -or -not $capabilityMatch.Success) {
            continue
        }
        $driverVersion = [version]$driverMatch.Value
        $computeCapability = [version]$capabilityMatch.Value
        if (
            $driverVersion -ge $minimumCu128WindowsDriver -and
            $computeCapability -ge $minimumCu128ComputeCapability
        ) {
            Write-Host (
                "Compatible NVIDIA GPU detected (driver $driverVersion, compute " +
                "$computeCapability); selecting CUDA 12.8 PyTorch."
            )
            return "cu128"
        }
    }
    Write-Warning (
        "No NVIDIA GPU met the CUDA 12.8 requirements (driver >= " +
        "$minimumCu128WindowsDriver, compute capability >= " +
        "$minimumCu128ComputeCapability); selecting CPU PyTorch."
    )
    return "cpu"
}

function Invoke-WinGetInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageId,
        [string]$Version = "",
        [Parameter(Mandatory = $true)]
        [scriptblock]$VerifyInstalled,
        [Parameter(Mandatory = $true)]
        [string]$RequirementDescription
    )

    $arguments = @(
        "install",
        "--id", $PackageId,
        "--exact",
        "--source", "winget",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity"
    )
    if ($Version) {
        # Version-pinned packages may need to replace a different installed
        # version. This branch is reached only after the exact on-disk runtime
        # check failed, so --force cannot make repeat runs reinstall it.
        $arguments += @("--version", $Version, "--force")
    }
    $installError = $null
    $exitCode = $null
    try {
        $exitCode = Invoke-NativeCommand -Executable (Get-WinGetPath) -Arguments $arguments `
            -FailureMessage "WinGet could not install $PackageId." `
            -AllowNonZeroExit -PassThru
    }
    catch {
        $installError = $_
    }

    # WinGet uses non-zero statuses for outcomes such as "already installed and
    # no upgrade is available".  The external command is not the source of
    # truth: refresh discovery and verify the required postcondition after every
    # attempt, including launch errors and non-zero exits.
    Refresh-ProcessPath
    $verificationError = $null
    $verified = $false
    try {
        $verificationResult = & $VerifyInstalled
        $verified = [bool]($verificationResult | Select-Object -Last 1)
    }
    catch {
        $verificationError = $_
    }
    if ($verified) {
        if ($null -ne $installError) {
            Write-Warning (
                "WinGet reported an error for $PackageId, but $RequirementDescription " +
                "was verified after the attempt. Continuing."
            )
        }
        elseif ($exitCode -ne 0) {
            Write-Warning (
                "WinGet exited with code $exitCode for $PackageId, but " +
                "$RequirementDescription was verified. Continuing."
            )
        }
        return
    }

    if ($null -ne $verificationError) {
        throw (
            "Could not verify $RequirementDescription after the WinGet attempt for " +
            "$PackageId. $($verificationError.Exception.Message)"
        )
    }
    if ($null -ne $installError) {
        throw (
            "WinGet could not install $PackageId, and $RequirementDescription remains " +
            "unavailable. $($installError.Exception.Message)"
        )
    }
    if ($exitCode -ne 0) {
        throw (
            "WinGet exited with code $exitCode for $PackageId, and " +
            "$RequirementDescription remains unavailable."
        )
    }
    throw (
        "WinGet reported success for $PackageId, but $RequirementDescription could " +
        "not be verified."
    )
}

function Refresh-ProcessPath {
    # Installers update the persistent environment, but an already-running
    # PowerShell process does not receive WM_SETTINGCHANGE. Merge all scopes so
    # newly installed tools are usable without asking the user to open a shell.
    $entries = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    # Preserve caller-specific prefixes such as an activated virtual
    # environment. Newly installed persistent entries are appended without
    # allowing Machine/User PATH values to displace current-process choices.
    foreach ($scope in @("Process", "User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable("Path", $scope)
        foreach ($entry in @($value -split [IO.Path]::PathSeparator)) {
            $trimmed = $entry.Trim()
            if ($trimmed -and $seen.Add($trimmed)) {
                $entries.Add($trimmed)
            }
        }
    }
    $env:PATH = $entries -join [IO.Path]::PathSeparator
}

function Add-ProcessPathPrefix {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $parts = @($env:PATH -split [IO.Path]::PathSeparator) | Where-Object {
        $_ -and -not $_.Equals($Directory, [StringComparison]::OrdinalIgnoreCase)
    }
    $env:PATH = (@($Directory) + $parts) -join [IO.Path]::PathSeparator
}

function Get-CompatiblePythonDetails {
    param([Parameter(Mandatory = $true)][string]$Candidate)

    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        return $null
    }
    # Build one Python program before constructing the argument array. Inside a
    # PowerShell @(...), newline-separated `+` expressions become separate
    # array items; Python would then execute only the first fragment after -c.
    $probeCode = (
        "import sys; ok = sys.version_info[:2] >= (3, 11); " +
        "print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}') if ok else None; " +
        "raise SystemExit(0 if ok else 1)"
    )
    $probe = Invoke-NativeProbe -Executable $Candidate -Arguments @("-I", "-c", $probeCode)
    if ($probe.ExitCode -ne 0 -or $probe.Output.Count -eq 0) {
        return $null
    }
    $versionLines = @($probe.Output | Where-Object { $_ -match '^\d+\.\d+\.\d+$' })
    if ($versionLines.Count -eq 0) {
        return $null
    }
    try {
        $versionText = ([string]($versionLines | Select-Object -Last 1)).Trim()
        $version = [version]$versionText
    }
    catch {
        return $null
    }
    if ($version -lt [version]"3.11") {
        return $null
    }
    return [pscustomobject]@{
        Path = (Resolve-Path -LiteralPath $Candidate).Path
        Version = $version
    }
}

function Test-CompatiblePython {
    param([Parameter(Mandatory = $true)][string]$Candidate)

    $details = Get-CompatiblePythonDetails -Candidate $Candidate
    return $null -ne $details
}

function Get-RegisteredPythonCandidates {
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -eq $launcher) {
        return @()
    }

    # -0p is the non-installing legacy-compatible listing interface supported
    # by both py.exe and the current Python Install Manager.
    $probe = Invoke-NativeProbe -Executable $launcher.Source -Arguments @("-0p")
    if ($probe.ExitCode -ne 0) {
        return @()
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $probe.Output) {
        $match = [regex]::Match(
            [string]$line,
            '(?<path>(?:[A-Za-z]:\\|\\\\).+?python(?:\d+(?:\.\d+)*)?\.exe)',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )
        if ($match.Success) {
            $candidates.Add($match.Groups["path"].Value.Trim())
        }
    }
    return @($candidates)
}

function Find-CompatiblePython {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"))
    }
    if ($env:ProgramFiles) {
        $candidates.Add((Join-Path $env:ProgramFiles "Python312\python.exe"))
    }
    foreach ($registered in Get-RegisteredPythonCandidates) {
        $candidates.Add($registered)
    }
    $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        $candidates.Add($pythonCommand.Source)
    }
    $installRoots = [System.Collections.Generic.List[string]]::new()
    if ($env:LOCALAPPDATA) {
        $installRoots.Add((Join-Path $env:LOCALAPPDATA "Programs\Python"))
    }
    if ($env:ProgramFiles) {
        $installRoots.Add($env:ProgramFiles)
    }
    foreach ($installRoot in $installRoots) {
        if (-not $installRoot -or -not (Test-Path -LiteralPath $installRoot -PathType Container)) {
            continue
        }
        foreach ($installation in Get-ChildItem -LiteralPath $installRoot -Directory `
            -Filter "Python3*" -ErrorAction SilentlyContinue | Sort-Object Name -Descending) {
            $candidates.Add((Join-Path $installation.FullName "python.exe"))
        }
    }

    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $compatible = [System.Collections.Generic.List[object]]::new()
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not $seen.Add($candidate)) {
            continue
        }
        $details = Get-CompatiblePythonDetails -Candidate $candidate
        if ($null -ne $details) {
            $compatible.Add($details)
        }
    }
    if ($compatible.Count -eq 0) {
        return $null
    }

    $selected = $compatible | Sort-Object `
        @{ Expression = {
            if ($_.Version.Major -eq 3 -and $_.Version.Minor -eq 12) { 0 } else { 1 }
        } }, `
        @{ Expression = { $_.Version }; Descending = $true }, `
        @{ Expression = { $_.Path } } | Select-Object -First 1
    return $selected.Path
}

function Confirm-CompatiblePython {
    $resolved = Find-CompatiblePython
    if ($null -ne $resolved) {
        return $resolved
    }
    if ($SkipPythonInstall) {
        throw "Python 3.11 or newer was not found and installation was explicitly skipped."
    }

    Write-Host (
        "Python 3.11 or newer was not found; installing the recommended " +
        "$pythonPackageId fallback with WinGet."
    )
    Invoke-WinGetInstall -PackageId $pythonPackageId `
        -RequirementDescription "a working Python 3.11-or-newer interpreter" `
        -VerifyInstalled { $null -ne (Find-CompatiblePython) }
    $resolved = Find-CompatiblePython
    if ($null -eq $resolved) {
        throw "WinGet completed, but a compatible Python could not be resolved in the current process."
    }
    return $resolved
}

function Test-VirtualEnvironment {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        return $false
    }
    return (Test-CompatiblePython $pythonPath)
}

function Move-IncompatibleEnvironmentAside {
    if (-not (Test-Path -LiteralPath $environmentPath)) {
        return
    }
    $suffix = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$environmentPath-incompatible-$suffix"
    if (Test-Path -LiteralPath $backup) {
        $backup = "$backup-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    }
    Move-Item -LiteralPath $environmentPath -Destination $backup
    Write-Warning "Moved the incompatible project environment to $backup"
    if ($env:VIRTUAL_ENV) {
        try {
            $activeEnvironment = [IO.Path]::GetFullPath([string]$env:VIRTUAL_ENV)
            $projectEnvironment = [IO.Path]::GetFullPath($environmentPath)
            if ($activeEnvironment.Equals($projectEnvironment, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Warning (
                    "The moved environment is still marked active in the calling shell. " +
                    "After setup finishes, open a new terminal or activate the new .venv."
                )
            }
        }
        catch {
            # A malformed inherited VIRTUAL_ENV value must not block recovery.
        }
    }
}

function Get-ExactSharedFfmpegDirectory {
    $requiredFiles = @(
        "avcodec-62.dll",
        "avdevice-62.dll",
        "avfilter-11.dll",
        "avformat-62.dll",
        "avutil-60.dll",
        "swresample-6.dll",
        "swscale-9.dll",
        "ffmpeg.exe",
        "ffprobe.exe"
    )
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($packageRoot in @(
        (Join-Path ([string]$env:LOCALAPPDATA) "Microsoft\WinGet\Packages"),
        (Join-Path ([string]$env:ProgramFiles) "WinGet\Packages")
    )) {
        if (-not $packageRoot -or -not (Test-Path -LiteralPath $packageRoot -PathType Container)) {
            continue
        }
        foreach ($package in Get-ChildItem -LiteralPath $packageRoot -Directory `
            -Filter "$ffmpegPackageId*" -ErrorAction SilentlyContinue) {
            $candidates.Add((Join-Path $package.FullName "ffmpeg-$ffmpegVersion-full_build-shared\bin"))
        }
    }
    foreach ($entry in @($env:PATH -split [IO.Path]::PathSeparator)) {
        if ($entry) {
            $candidates.Add($entry)
        }
    }

    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not $seen.Add($candidate)) {
            continue
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
            continue
        }
        $complete = $true
        foreach ($file in $requiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $candidate $file) -PathType Leaf)) {
                $complete = $false
                break
            }
        }
        if (-not $complete) {
            continue
        }

        $probe = Invoke-NativeProbe -Executable (Join-Path $candidate "ffmpeg.exe") `
            -Arguments @("-version")
        if ($probe.ExitCode -eq 0 -and ($probe.Output | Select-Object -First 1) -match `
            "^ffmpeg version $([regex]::Escape($ffmpegVersion))(?:[-\s])") {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Confirm-ExactSharedFfmpeg {
    $directory = Get-ExactSharedFfmpegDirectory
    if ($null -eq $directory) {
        if ($SkipSharedFfmpeg) {
            throw (
                "FFmpeg $ffmpegVersion full-shared was not found and installation was " +
                "explicitly skipped. Face readiness cannot be claimed."
            )
        }
        Write-Host "Installing exact FFmpeg $ffmpegVersion full-shared runtime."
        Invoke-WinGetInstall -PackageId $ffmpegPackageId -Version $ffmpegVersion `
            -RequirementDescription "the exact FFmpeg $ffmpegVersion full-shared runtime" `
            -VerifyInstalled { $null -ne (Get-ExactSharedFfmpegDirectory) }
        $directory = Get-ExactSharedFfmpegDirectory
        if ($null -eq $directory) {
            throw (
                "WinGet completed, but the exact FFmpeg $ffmpegVersion full-shared " +
                "runtime (including all DLLs, ffmpeg and ffprobe) could not be verified."
            )
        }
    }
    Add-ProcessPathPrefix $directory
    Write-Host "FFmpeg $ffmpegVersion full-shared: $directory"
    return $directory
}

function Test-JdkBin {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $javaPath = Join-Path $Directory "java.exe"
    $javacPath = Join-Path $Directory "javac.exe"
    if (
        -not (Test-Path -LiteralPath $javaPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $javacPath -PathType Leaf)
    ) {
        return $false
    }
    $javaProbe = Invoke-NativeProbe -Executable $javaPath -Arguments @("-version")
    if ($javaProbe.ExitCode -ne 0) {
        return $false
    }
    $javacProbe = Invoke-NativeProbe -Executable $javacPath -Arguments @("-version")
    return $javacProbe.ExitCode -eq 0
}

function Find-JdkBin {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:JAVA_HOME) {
        $candidates.Add((Join-Path $env:JAVA_HOME "bin"))
    }
    $java = Get-Command "java.exe" -ErrorAction SilentlyContinue
    $javac = Get-Command "javac.exe" -ErrorAction SilentlyContinue
    if ($null -ne $java -and $null -ne $javac) {
        $javaBin = Split-Path -Parent $java.Source
        $javacBin = Split-Path -Parent $javac.Source
        if ($javaBin.Equals($javacBin, [StringComparison]::OrdinalIgnoreCase)) {
            $candidates.Add($javaBin)
        }
    }
    foreach ($root in @(
        (Join-Path ([string]$env:ProgramFiles) "Eclipse Adoptium"),
        (Join-Path ([string]$env:ProgramFiles) "Java"),
        (Join-Path ([string]$env:LOCALAPPDATA) "Programs\Eclipse Adoptium")
    )) {
        if (-not $root -or -not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        foreach ($jdk in Get-ChildItem -LiteralPath $root -Directory -Filter "jdk*" `
            -ErrorAction SilentlyContinue | Sort-Object Name -Descending) {
            $candidates.Add((Join-Path $jdk.FullName "bin"))
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-JdkBin $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Confirm-Jdk {
    $directory = Find-JdkBin
    if ($null -eq $directory) {
        if ($SkipJdkInstall) {
            throw "A complete JDK (java.exe plus javac.exe) was not found and installation was explicitly skipped."
        }
        Write-Host "A complete JDK was not found; installing $jdkPackageId with WinGet."
        Invoke-WinGetInstall -PackageId $jdkPackageId `
            -RequirementDescription "a working JDK with java.exe and javac.exe" `
            -VerifyInstalled { $null -ne (Find-JdkBin) }
        $directory = Find-JdkBin
        if ($null -eq $directory) {
            throw "WinGet completed, but a matching java.exe and javac.exe could not be resolved."
        }
    }

    Add-ProcessPathPrefix $directory
    $env:JAVA_HOME = Split-Path -Parent $directory
    Invoke-NativeCommand -Executable (Join-Path $directory "java.exe") -Arguments @("-version") `
        -FailureMessage "The selected Java runtime did not start."
    Invoke-NativeCommand -Executable (Join-Path $directory "javac.exe") -Arguments @("-version") `
        -FailureMessage "The selected Java compiler did not start."
    Write-Host "JDK: $env:JAVA_HOME"
}

function Test-TorchFamily {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("cpu", "cu128")]
        [string]$Runtime
    )

    $validation = @'
import importlib.metadata as metadata
import sys

runtime = sys.argv[1]
expected = {
    'torch': '2.11.0',
    'torchvision': '0.26.0',
    'torchaudio': '2.11.0',
    'torchcodec': '0.13.0',
}
actual = {name: metadata.version(name).split('+')[0] for name in expected}
if actual != expected:
    raise SystemExit(f'PyTorch family mismatch: expected {expected}, got {actual}')

import torch

cuda = torch.version.cuda
if runtime == 'cpu' and cuda is not None:
    raise SystemExit(f'Expected a CPU PyTorch build, but torch reports CUDA {cuda}')
if runtime == 'cu128' and (cuda is None or not str(cuda).startswith('12.8')):
    raise SystemExit(f'Expected a CUDA 12.8 PyTorch build, but torch reports {cuda!r}')
if runtime == 'cu128' and not torch.cuda.is_available():
    raise SystemExit('CUDA 12.8 PyTorch is installed, but no usable CUDA device is available')
if runtime == 'cu128':
    # Availability alone only proves that the driver initialized. Exercise a
    # real kernel and synchronization so setup fails before long model runs do.
    value = (torch.ones(8, device='cuda') * 2).sum().item()
    torch.cuda.synchronize()
    if value != 16:
        raise SystemExit(f'CUDA computation smoke test returned {value!r}, expected 16')
print(f'Matched PyTorch family: {actual}; runtime={runtime}; torch CUDA={cuda!r}')
'@
    Invoke-NativeCommand -Executable $pythonPath -Arguments @("-c", $validation, $Runtime) `
        -FailureMessage "The installed PyTorch family is not the requested matched runtime."
}

function Get-InstalledTorchRuntime {
    $probe = @'
import torch

cuda = torch.version.cuda
if cuda is None:
    print('cpu')
elif str(cuda).startswith('12.8'):
    print('cu128')
else:
    print(f'other:{cuda}')
'@
    $result = Invoke-NativeProbe -Executable $pythonPath -Arguments @("-c", $probe)
    if ($result.ExitCode -ne 0) {
        return "missing"
    }
    return [string]($result.Output | Select-Object -Last 1)
}

if ($FunctionsOnly) {
    return
}

# Module checks below must resolve this repository even when the caller invokes
# the script from another working directory.
Push-Location -LiteralPath $projectRoot
try {
    if ($env:OS -ne "Windows_NT") {
        throw "This setup script supports Windows 10 and Windows 11 only."
    }
    Refresh-ProcessPath
    $selectedTorchRuntime = Resolve-TorchRuntime -RequestedRuntime $TorchRuntime

    if (-not (Test-VirtualEnvironment)) {
        # Resolve or install a usable base interpreter before touching the
        # existing project environment. A second probe protects against a
        # transient first failure and avoids moving a now-healthy .venv.
        $basePython = Confirm-CompatiblePython
        if (Test-VirtualEnvironment) {
            Write-Warning (
                "The project environment passed a repeat compatibility check; " +
                "reusing it without moving any files."
            )
        }
        else {
            Move-IncompatibleEnvironmentAside
            Write-Host "Creating the compatible Python project environment at $environmentPath"
            Invoke-NativeCommand -Executable $basePython -Arguments @("-m", "venv", $environmentPath) `
                -FailureMessage "Could not create the compatible Python project environment."
            if (-not (Test-VirtualEnvironment)) {
                throw "The new .venv did not contain a working Python 3.11-or-newer interpreter."
            }
        }
    }
    else {
        Write-Host "Reusing the existing compatible Python environment at $environmentPath"
    }

    Invoke-NativeCommand -Executable $pythonPath `
        -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools<82", "wheel") `
        -FailureMessage "Could not update the Python packaging tools."

    $torchIndex = "https://download.pytorch.org/whl/$selectedTorchRuntime"
    Write-Host "Installing the matched PyTorch 2.11 family ($selectedTorchRuntime)."
    $torchInstallArguments = @(
        "-m", "pip", "install",
        "torch==2.11.0", "torchvision==0.26.0", "torchaudio==2.11.0",
        "--index-url", $torchIndex
    )
    $installedTorchRuntime = Get-InstalledTorchRuntime
    if ($installedTorchRuntime -ne "missing" -and $installedTorchRuntime -ne $selectedTorchRuntime) {
        Write-Host (
            "Replacing the installed PyTorch runtime ($installedTorchRuntime) with $selectedTorchRuntime."
        )
        # PEP 440 treats 2.11.0+cpu as satisfying torch==2.11.0. Force the
        # exact-index wheels only when changing runtime families; requirements
        # installation below supplies and validates the shared dependencies.
        $torchInstallArguments += @("--force-reinstall", "--no-deps")
    }
    Invoke-NativeCommand -Executable $pythonPath -Arguments $torchInstallArguments `
        -FailureMessage "Could not install the matched PyTorch packages."

    # TorchCodec 0.13 does not publish a Windows cu128 wheel. Face uses its
    # supported Windows CPU wheel for decoding while Detectorv2 tensors and
    # models use the selected CUDA PyTorch runtime.
    Invoke-NativeCommand -Executable $pythonPath -Arguments @(
        "-m", "pip", "install", "torchcodec==0.13.0",
        "--index-url", "https://download.pytorch.org/whl/cpu"
    ) -FailureMessage "Could not install the supported Windows TorchCodec package."

    Write-Host "Installing all project features into the same environment."
    Invoke-NativeCommand -Executable $pythonPath `
        -Arguments @("-m", "pip", "install", "-r", $requirementsPath) `
        -FailureMessage "Could not install project requirements."

    Test-TorchFamily -Runtime $selectedTorchRuntime
    $ffmpegDirectory = Confirm-ExactSharedFfmpeg

    Invoke-NativeCommand -Executable $pythonPath -Arguments @("-m", "pip", "check") `
        -FailureMessage "The installed Python dependency set is inconsistent."

    Write-Host "Preparing Py-Feat Detectorv2 model weights (explicit network download when absent)."
    Invoke-NativeCommand -Executable $pythonPath `
        -Arguments @("-m", "processing.face_analysis", "--prepare-models") `
        -FailureMessage "Could not download/load and validate all Py-Feat Detectorv2 model weights."

    Write-Host "Running the offline Face native decode/import readiness smoke test."
    Invoke-NativeCommand -Executable $pythonPath `
        -Arguments @("-m", "processing.face_analysis", "--check") `
        -FailureMessage "Face-processing readiness smoke test failed."

    $faceCommand = ".\.venv\Scripts\python.exe -m processing.face_analysis Videos"
    $textCommand = ".\.venv\Scripts\python.exe -m processing.text_analysis Videos"
    $textReady = $false
    $textStatus = "not ready"

    if ($TextMode -eq "Skip") {
        $textStatus = "SKIPPED by explicit -TextMode Skip"
        Write-Warning "Text setup was explicitly skipped; full multimodal readiness is not claimed."
    }
    elseif (-not (Test-Path -LiteralPath $rockSteadyJar -PathType Leaf)) {
        $textStatus = "NOT READY: licensed RockSteady JAR is missing"
        $message = (
            "The Git LFS-managed RockSteady JAR is missing from this checkout. " +
            "Run 'git lfs pull' or restore the project-authorized copy at exactly:`n  $rockSteadyJar"
        )
        if ($TextMode -eq "Require") {
            throw "$message`nFace is ready now: $faceCommand"
        }
        Write-Warning $message
        Write-Host "After placing the JAR, rerun this setup script; it will install/check the JDK and validate Text."
    }
    else {
        Confirm-Jdk
        Write-Host "Running the Text/RockSteady compile, dictionary and category readiness check."
        Invoke-NativeCommand -Executable $pythonPath `
            -Arguments @("-m", "processing.text_analysis", "--check") `
            -FailureMessage "Text/RockSteady readiness check failed."
        $textReady = $true
        $textStatus = "READY"
    }

    Write-Host ""
    if ($textReady) {
        Write-Host "Setup complete: Face READY; Text/RockSteady READY."
        Write-Host "Run Facial: $faceCommand"
        Write-Host "Run Text:   $textCommand"
    }
    else {
        Write-Host "Setup complete: Face READY; Text/RockSteady $textStatus."
        Write-Host "Run Face now: $faceCommand"
    }
}
finally {
    Pop-Location
}
