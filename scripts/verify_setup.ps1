[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-SetupCondition {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Assert-SetupThrows {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [Parameter(Mandatory = $true)]
        [string]$MessagePattern,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $caught = $null
    try {
        & $Action
    }
    catch {
        $caught = $_
    }
    if ($null -eq $caught) {
        throw $FailureMessage
    }
    if ($caught.Exception.Message -notmatch $MessagePattern) {
        throw "$FailureMessage Unexpected error: $($caught.Exception.Message)"
    }
}

$setupPath = Join-Path $PSScriptRoot "setup.ps1"
$projectRoot = Split-Path -Parent $PSScriptRoot
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
    "isolated single-program Python probe" = '@("-I", "-c", $probeCode)'
    "Python manager discovery is non-installing" = '$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = "false"'
    "compatible Python details probe" = 'function Get-CompatiblePythonDetails'
    "compatible Python validator" = 'function Test-CompatiblePython'
    "registered Python discovery" = 'function Get-RegisteredPythonCandidates'
    "non-installing Python runtime listing" = 'Arguments @("-0p")'
    "compatible Python discovery" = 'function Find-CompatiblePython'
    "Python 3.12 selection preference" = 'if ($_.Version.Major -eq 3 -and $_.Version.Minor -eq 12)'
    "compatible virtual environment reuse" = 'Reusing the existing compatible Python environment'
    "Python 3.12 automatic fallback" = 'Python.Python.3.12'
    "automatic Python fallback install" = 'Invoke-WinGetInstall -PackageId $pythonPackageId'
    "post-install verification" = '[scriptblock]$VerifyInstalled'
    "WinGet non-zero reconciliation" = '-AllowNonZeroExit -PassThru'
    "WinGet noninteractive mode" = '--disable-interactivity'
    "process PATH precedence" = 'foreach ($scope in @("Process", "User", "Machine"))'
    "recover-before-move ordering" = '$basePython = Confirm-CompatiblePython'
    "repeat virtual-environment probe" = 'if (Test-VirtualEnvironment)'
    "matched Torch CPU/CUDA selector" = 'Resolve-TorchRuntime'
    "supported NVIDIA architecture gate" = '--query-gpu=driver_version,compute_cap'
    "CUDA device usability check" = 'torch.cuda.is_available()'
    "CUDA computation smoke" = "torch.ones(8, device='cuda')"
    "Torch-compatible setuptools" = 'setuptools<82'
    "Windows TorchCodec CPU wheel" = 'TorchCodec 0.13 does not publish a Windows cu128 wheel'
    "pip dependency validation" = '"pip", "check"'
    "explicit Face model preparation" = '"processing.face_analysis", "--prepare-models"'
    "offline Face readiness smoke" = '"processing.face_analysis", "--check"'
    "Text readiness check" = '"processing.text_analysis", "--check"'
    "licensed JAR gate" = 'rocksteady-desktop-application-0.4#2018-05-16.jar'
    "RockSteady exact byte size" = '$rockSteadyJarSizeBytes = [long]67417737'
    "RockSteady exact SHA-256" = '02ddb9b418952df4b109fa8ca1e6a59000115af2d4b81aca29d555e28a448534'
    "RockSteady state validation" = 'function Get-RockSteadyJarState'
    "RockSteady scoped LFS materialization" = 'function Invoke-RockSteadyLfsPull'
    "RockSteady LFS resolution" = 'function Resolve-RockSteadyJar'
    "RockSteady exact LFS include" = '"--include=$relativeJar"'
    "explicit Text policy" = 'ValidateSet("Auto", "Require", "Skip")'
    "independent Face handoff" = 'processing.face_analysis Videos'
    "independent Text handoff" = 'processing.text_analysis Videos'
    "side-effect-free verification boundary" = 'if ($FunctionsOnly)'
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
Assert-SetupCondition ($nonInstallingIndex -ge 0 -and $discoveryIndex -gt $nonInstallingIndex) `
    "setup.ps1 must disable Python Manager auto-install before interpreter discovery."
if ($source -match 'sys\.version_info(?:\[:2\])?\s*(?:<|<=)\s*\(') {
    throw "setup.ps1 must not impose an upper Python version gate."
}
$pythonFallbackCount = [regex]::Matches(
    $source,
    'Invoke-WinGetInstall\s+-PackageId\s+\$pythonPackageId'
).Count
Assert-SetupCondition ($pythonFallbackCount -eq 1) `
    "setup.ps1 must have exactly one explicit Python WinGet fallback."
$prepareModelsIndex = $source.IndexOf('"processing.face_analysis", "--prepare-models"')
$offlineCheckIndex = $source.IndexOf('"processing.face_analysis", "--check"')
Assert-SetupCondition `
    ($prepareModelsIndex -ge 0 -and $offlineCheckIndex -gt $prepareModelsIndex) `
    "setup.ps1 must prepare Face models before its offline readiness check."

if ($source -match '(?m)^\s*&\s+winget\b') {
    throw "setup.ps1 must invoke the resolved WinGet executable through checked error handling."
}
if (-not $source.Contains('@("--version", $Version, "--force")')) {
    throw "setup.ps1 must be able to replace a different FFmpeg version after exact detection fails."
}
$entryMarker = '# Module checks below must resolve this repository'
$entryIndex = $source.IndexOf($entryMarker)
Assert-SetupCondition ($entryIndex -ge 0) `
    "setup.ps1 is missing its guarded installation entrypoint."
$setupEntry = $source.Substring($entryIndex)
$resolveIndex = $setupEntry.IndexOf('$basePython = Confirm-CompatiblePython')
$moveIndex = $setupEntry.IndexOf('Move-IncompatibleEnvironmentAside')
Assert-SetupCondition ($resolveIndex -ge 0 -and $moveIndex -gt $resolveIndex) `
    "setup.ps1 must resolve a replacement Python before moving the project environment."
$rockSteadyResolveIndex = $setupEntry.IndexOf('$rockSteadyState = Resolve-RockSteadyJar')
$jdkIndex = $setupEntry.IndexOf('Confirm-Jdk')
Assert-SetupCondition `
    ($rockSteadyResolveIndex -ge 0 -and $jdkIndex -gt $rockSteadyResolveIndex) `
    "setup.ps1 must materialize and validate RockSteady before installing/checking the JDK."

$ignoreSource = Get-Content -LiteralPath (Join-Path $projectRoot ".gitignore") -Raw
Assert-SetupCondition ($ignoreSource.Contains('.venv.incompatible-*/')) `
    ".gitignore must ignore backups created by older setup versions."
Assert-SetupCondition ($ignoreSource.Contains('.venv-*/')) `
    ".gitignore must ignore backups created by the current setup version."

# Dot-source the installer in this verifier process. The internal FunctionsOnly
# switch must load functions without invoking pip, WinGet, downloads, or checks.
$oldPythonManagerSetting = $env:PYTHON_MANAGER_AUTOMATIC_INSTALL
try {
    . $setupPath -FunctionsOnly

    # Verify that Python receives exactly one complete program after -c. Mocking
    # the native probe makes this independent of any installed Python runtime.
    $originalNativeProbe = (Get-Command Invoke-NativeProbe -CommandType Function).ScriptBlock
    $script:capturedProbeArguments = @()
    function Invoke-NativeProbe {
        param(
            [Parameter(Mandatory = $true)]
            [string]$Executable,
            [string[]]$Arguments = @()
        )

        $script:capturedProbeArguments = @($Arguments)
        return [pscustomobject]@{
            ExitCode = 0
            Output = @("unexpected startup output", "3.12.10", "unexpected shutdown output")
        }
    }
    $pythonDetails = Get-CompatiblePythonDetails -Candidate $setupPath
    Assert-SetupCondition ($script:capturedProbeArguments.Count -eq 3) `
        "The Python compatibility probe must pass '-I', '-c', and one code argument."
    Assert-SetupCondition ($script:capturedProbeArguments[0] -eq "-I") `
        "The Python compatibility probe must use isolated mode."
    Assert-SetupCondition ($script:capturedProbeArguments[1] -eq "-c") `
        "The second Python compatibility-probe argument must be -c."
    Assert-SetupCondition ($script:capturedProbeArguments[2] -match 'print\(') `
        "The single Python compatibility-probe program must include its version output."
    Assert-SetupCondition ($pythonDetails.Version -eq [version]"3.12.10") `
        "The Python compatibility probe must parse a valid version."
    Set-Item -LiteralPath Function:\Invoke-NativeProbe -Value $originalNativeProbe

    # Exercise the WinGet reconciliation contract without launching WinGet.
    # A non-zero tool status is acceptable only when the required postcondition
    # is independently verified afterward.
    $originalGetWinGetPath = (Get-Command Get-WinGetPath -CommandType Function).ScriptBlock
    $originalNativeCommand = (Get-Command Invoke-NativeCommand -CommandType Function).ScriptBlock
    $originalRefreshPath = (Get-Command Refresh-ProcessPath -CommandType Function).ScriptBlock
    $script:mockWinGetExitCode = 42
    $script:mockNativeThrows = $false
    $script:mockRefreshCount = 0
    function Get-WinGetPath { return "mock-winget.exe" }
    function Invoke-NativeCommand {
        param(
            [string]$Executable,
            [string[]]$Arguments,
            [string]$FailureMessage,
            [switch]$AllowNonZeroExit,
            [switch]$PassThru
        )
        if ($script:mockNativeThrows) {
            throw "mock launch failure"
        }
        if ($PassThru) {
            return [int]$script:mockWinGetExitCode
        }
    }
    function Refresh-ProcessPath { $script:mockRefreshCount += 1 }

    Invoke-WinGetInstall -PackageId "Example.Tool" `
        -RequirementDescription "the mocked tool" -VerifyInstalled { $true }
    Assert-SetupCondition ($script:mockRefreshCount -eq 1) `
        "WinGet handling must refresh discovery after a non-zero exit."

    Assert-SetupThrows `
        -Action {
            Invoke-WinGetInstall -PackageId "Example.Tool" `
                -RequirementDescription "the mocked tool" -VerifyInstalled { $false }
        } `
        -MessagePattern 'remains unavailable' `
        -FailureMessage "WinGet failure must remain fatal when post-install verification fails."

    $script:mockNativeThrows = $true
    Invoke-WinGetInstall -PackageId "Example.Tool" `
        -RequirementDescription "the mocked tool" -VerifyInstalled { $true }
    $script:mockNativeThrows = $false

    $script:mockWinGetExitCode = 0
    Assert-SetupThrows `
        -Action {
            Invoke-WinGetInstall -PackageId "Example.Tool" `
                -RequirementDescription "the mocked tool" -VerifyInstalled { $false }
        } `
        -MessagePattern 'reported success.*could not be verified' `
        -FailureMessage "WinGet success must not bypass a failed post-install verification."

    Set-Item -LiteralPath Function:\Get-WinGetPath -Value $originalGetWinGetPath
    Set-Item -LiteralPath Function:\Invoke-NativeCommand -Value $originalNativeCommand
    Set-Item -LiteralPath Function:\Refresh-ProcessPath -Value $originalRefreshPath

    # Refreshing persistent PATH entries must not demote a caller's active
    # process prefix, such as .venv\Scripts.
    $originalProcessPath = $env:PATH
    try {
        $pathMarker = Join-Path $projectRoot "_setup_path_precedence_probe"
        $env:PATH = "$pathMarker$([IO.Path]::PathSeparator)$env:PATH"
        Refresh-ProcessPath
        $firstPathEntry = @($env:PATH -split [IO.Path]::PathSeparator)[0]
        Assert-SetupCondition `
            ($firstPathEntry.Equals($pathMarker, [StringComparison]::OrdinalIgnoreCase)) `
            "Refresh-ProcessPath must preserve the caller's first process PATH entry."
    }
    finally {
        $env:PATH = $originalProcessPath
    }

    # Exercise RockSteady state detection and the exact Git LFS pull contract
    # with a temporary mock artifact. No network, repository file, or real LFS
    # object is touched by this verification.
    $originalRockSteadyJar = $rockSteadyJar
    $originalRockSteadyJarSizeBytes = $rockSteadyJarSizeBytes
    $originalRockSteadyJarSha256 = $rockSteadyJarSha256
    $originalGetGitPath = (Get-Command Get-GitPath -CommandType Function).ScriptBlock
    $originalNativeProbe = (Get-Command Invoke-NativeProbe -CommandType Function).ScriptBlock
    $rockSteadyProbeDirectory = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("rocksteady-setup-verification-" + [Guid]::NewGuid().ToString("N"))
    $rockSteadyProbeFile = Join-Path $rockSteadyProbeDirectory $rockSteadyJarName
    [void](New-Item -ItemType Directory -Path $rockSteadyProbeDirectory)
    try {
        [byte[]]$validBytes = 0..63
        [IO.File]::WriteAllBytes($rockSteadyProbeFile, $validBytes)
        $rockSteadyJar = $rockSteadyProbeFile
        $rockSteadyJarSizeBytes = [long]$validBytes.LongLength
        $rockSteadyJarSha256 = (
            Get-FileHash -Algorithm SHA256 -LiteralPath $rockSteadyProbeFile
        ).Hash.ToLowerInvariant()

        $state = Get-RockSteadyJarState
        Assert-SetupCondition ($state.Ready -and $state.Status -eq "ready") `
            "An exact RockSteady artifact must pass size and SHA-256 validation."

        $pointer = (
            "version https://git-lfs.github.com/spec/v1`n" +
            "oid sha256:$rockSteadyJarSha256`n" +
            "size $rockSteadyJarSizeBytes`n"
        )
        [IO.File]::WriteAllText(
            $rockSteadyProbeFile,
            $pointer,
            [Text.UTF8Encoding]::new($false)
        )
        $state = Get-RockSteadyJarState
        Assert-SetupCondition ($state.Status -eq "lfs-pointer") `
            "A Git LFS pointer must never be accepted as the RockSteady JAR."

        Remove-Item -LiteralPath $rockSteadyProbeFile -Force
        $state = Get-RockSteadyJarState
        Assert-SetupCondition ($state.Status -eq "missing") `
            "A missing RockSteady artifact must be reported explicitly."

        $script:mockRockSteadyBytes = $validBytes
        $script:capturedRockSteadyLfsArguments = @()
        $script:mockGitLfsAvailable = $true
        $script:mockGitLfsPullExitCode = 0
        function Get-GitPath { return "mock-git.exe" }
        function Invoke-NativeProbe {
            param(
                [Parameter(Mandatory = $true)]
                [string]$Executable,
                [string[]]$Arguments = @()
            )

            if ($Arguments.Count -ge 2 -and $Arguments[0] -eq "lfs" -and $Arguments[1] -eq "version") {
                return [pscustomobject]@{
                    ExitCode = $(if ($script:mockGitLfsAvailable) { 0 } else { 1 })
                    Output = @()
                }
            }
            if ($Arguments -contains "pull") {
                $script:capturedRockSteadyLfsArguments = @($Arguments)
                if ($script:mockGitLfsPullExitCode -eq 0) {
                    [IO.File]::WriteAllBytes($rockSteadyJar, $script:mockRockSteadyBytes)
                }
                return [pscustomobject]@{
                    ExitCode = $script:mockGitLfsPullExitCode
                    Output = @("mock LFS pull diagnostic")
                }
            }
            return [pscustomobject]@{
                ExitCode = 0
                Output = @()
            }
        }

        $state = Resolve-RockSteadyJar
        Assert-SetupCondition ($state.Ready) `
            "A successful exact Git LFS pull must materialize and validate RockSteady."
        $relativeJar = "external/RockSteady/$rockSteadyJarName"
        Assert-SetupCondition `
            ($script:capturedRockSteadyLfsArguments -contains "--include=$relativeJar") `
            "RockSteady Git LFS pull must include only the exact tracked path."
        Assert-SetupCondition `
            ($script:capturedRockSteadyLfsArguments -contains "--exclude=") `
            "RockSteady Git LFS pull must explicitly clear broader include/exclude configuration."

        [byte[]]$invalidBytes = @($validBytes)
        $invalidBytes[0] = 255
        [IO.File]::WriteAllBytes($rockSteadyProbeFile, $invalidBytes)
        $state = Get-RockSteadyJarState
        Assert-SetupCondition ($state.Status -eq "hash-mismatch") `
            "A same-size RockSteady artifact with different bytes must fail closed."

        $script:capturedRockSteadyLfsArguments = @()
        $state = Resolve-RockSteadyJar
        Assert-SetupCondition `
            ($state.Status -eq "hash-mismatch" -and $script:capturedRockSteadyLfsArguments.Count -eq 0) `
            "Setup must not overwrite a present but unapproved RockSteady artifact."

        Remove-Item -LiteralPath $rockSteadyProbeFile -Force
        $script:mockGitLfsAvailable = $false
        $state = Resolve-RockSteadyJar
        Assert-SetupCondition ($state.Status -eq "lfs-pull-failed") `
            "Missing Git LFS must produce an explicit non-ready RockSteady state."

        $script:mockGitLfsAvailable = $true
        $script:mockGitLfsPullExitCode = 9
        $state = Resolve-RockSteadyJar
        Assert-SetupCondition `
            ($state.Status -eq "lfs-pull-failed" -and $state.Detail -match 'exit code 9') `
            "A failed Git LFS pull must preserve an actionable exit-code diagnostic."
    }
    finally {
        $rockSteadyJar = $originalRockSteadyJar
        $rockSteadyJarSizeBytes = $originalRockSteadyJarSizeBytes
        $rockSteadyJarSha256 = $originalRockSteadyJarSha256
        Set-Item -LiteralPath Function:\Get-GitPath -Value $originalGetGitPath
        Set-Item -LiteralPath Function:\Invoke-NativeProbe -Value $originalNativeProbe
        if (Test-Path -LiteralPath $rockSteadyProbeFile -PathType Leaf) {
            Remove-Item -LiteralPath $rockSteadyProbeFile -Force
        }
        if (Test-Path -LiteralPath $rockSteadyProbeDirectory -PathType Container) {
            Remove-Item -LiteralPath $rockSteadyProbeDirectory -Force
        }
    }
}
finally {
    $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = $oldPythonManagerSetting
}

Write-Host (
    "setup.ps1 verification passed: parse, static contracts, Python argument " +
    "shape, WinGet postconditions, recovery ordering, PATH precedence, and " +
    "RockSteady Git LFS integrity."
)
