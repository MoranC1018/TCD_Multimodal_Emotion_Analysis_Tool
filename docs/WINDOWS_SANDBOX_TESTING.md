# Windows Sandbox installation test

This route tests a fresh public Git clone in a disposable Windows x64 desktop.
The generator prepares a configuration and evidence directories. It does not
enable Windows features, install host software, start Sandbox, or restart Windows.
Use a public commit containing `scripts/test_windows_install.ps1`. The guest checks
the full commit SHA before running that harness.

## Requirements and scope

Windows Sandbox requires a supported Windows edition, firmware virtualization,
and sufficient available memory and disk. Microsoft lists 4 GB of system RAM as
the minimum and recommends 8 GB. This configuration allocates 6,144 MB to the
guest. Python wheels, CPU Torch, FFmpeg, a JDK, and model downloads need additional
host disk beyond Sandbox's own minimum. The full installation can take substantial
time and download several GB. Close other heavy workloads before starting it.
See [Microsoft's installation requirements](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-install).

The configuration disables vGPU, clipboard, microphone, camera, and printer
sharing. Networking is enabled for public downloads. Exactly two folders are
mapped: a new task bootstrap folder at `C:\SandboxBootstrap` with read-only access,
and a new task evidence folder at `C:\Evidence` with write access. The host checkout,
credentials, private media, Python environment, and model caches are not mapped.
Writable mapped files persist after Sandbox closes. See
[Microsoft's configuration reference](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file).

Microsoft documents that Sandbox does not include WinGet or the Microsoft Store.
The guest first records its baseline, then bootstraps WinGet and Git separately.
This prerequisite preparation is included in the evidence and is not attributed
to the repository's setup script. The isolated guest uses its default administrator
account, `WDAGUtilityAccount`. See
[Microsoft's WinGet guidance for Sandbox](https://learn.microsoft.com/en-us/windows/package-manager/winget/#install-winget-on-windows-sandbox).

## Enable the host feature once, if needed

Run this optional command from the checkout in Windows PowerShell. `-Elevate`
requests normal Windows UAC when needed. Review the UAC prompt before accepting.
No alternate elevation mechanism or automatic restart is used.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\windows_sandbox\Enable-SandboxHost.ps1 -EvidenceDirectory "$env:LOCALAPPDATA\TCD-InstallTests\host-enablement" -Elevate
```

The elevated step runs:

```powershell
Enable-WindowsOptionalFeature -FeatureName Containers-DisposableClientVM -All -Online -NoRestart
```

Read `host-enablement\host-enable-*\status.json` and `transcript.txt`. A cancelled
UAC prompt is recorded separately from a failed feature installation. If status
is `EnabledRestartRequired`, save your work and restart Windows manually before
launching Sandbox. The script also recognizes an already enabled feature.

## Prepare an exact public revision

Choose the full 40-character commit SHA to test. It must be publicly fetchable
and contain the common harness. Running this generator requires no administrator
rights. By default it checks the repository, exact commit, and harness through
the public GitHub API without credentials. API rate limiting or an unpublished
commit causes preparation to fail before creating a run directory.

```powershell
$commit = Read-Host 'Full public commit SHA containing the installation harness'
$run = Join-Path $env:LOCALAPPDATA ('TCD-InstallTests\sandbox-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$prepared = .\scripts\windows_sandbox\New-InstallSandbox.ps1 -Commit $commit -RunDirectory $run
$prepared
```

The default repository is
`https://github.com/MoranC1018/TCD_Multimodal_Emotion_Analysis_Tool`.
`-RepositoryUrl` accepts a public `https://github.com/owner/repository` URL.
Credentials, query strings, fragments, non-GitHub URLs, branch names, and abbreviated
SHAs are rejected. Existing run directories are rejected to preserve earlier
evidence. Local filesystem paths with spaces, apostrophes, or ampersands are
supported; junctions, symlinks, and percent-expanded paths are rejected.

For offline configuration review, add `-SkipRemoteValidation`. The resulting
manifest records `RemoteValidated: false`; the guest still fetches and verifies
the SHA and requires the harness. Offline generation is not a successful install
test. Never put private files inside the generated bootstrap or evidence folders.

## Launch and inspect the result

After enabling Sandbox and performing any required manual restart, launch the
generated configuration explicitly:

```powershell
Start-Process -FilePath $prepared.ConfigurationPath
```

If PowerShell was closed during the restart, use the saved absolute path:

```powershell
$configuration = Read-Host 'Absolute path to the generated install-test.wsb'
Start-Process -FilePath $configuration
```

The guest downloads prerequisites, verifies their hashes, installs them, creates
`C:\InstallTest\source` with a fresh clone, fetches and checks out the requested
commit, and confirms the checkout is clean. Git LFS smudging is disabled for the
clone so the setup script's own RockSteady materialization is exercised. It then
runs from the clone:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test_windows_install.ps1 -EvidenceDirectory C:\Evidence\validation -EnvironmentKind WindowsSandbox
```

Inspect these files on the host before disposing of the guest:

| Evidence | Meaning |
| --- | --- |
| `run.json` and `bootstrap-hashes.json` | Requested public revision, generator settings, and copied bootstrap hashes |
| `evidence\bootstrap-evidence\guest-bootstrap-*\status.json` | Baseline, prerequisite stages, actual checkout SHA, and harness exit code |
| `evidence\bootstrap-evidence\guest-bootstrap-*\transcript.txt` | Guest bootstrap console output |
| `evidence\bootstrap-evidence\guest-bootstrap-*\git-install.log` | Git prerequisite installer details |
| `evidence\bootstrap-evidence\winget-bootstrap-*\status.json` | Existing WinGet, or pinned download and Appx installation result |
| `evidence\bootstrap-evidence\winget-bootstrap-*\transcript.txt` | WinGet prerequisite logs |
| `evidence\bootstrap-evidence\guest-bootstrap-*\*-process\` | Per-process stdout, stderr, exit/timeout status, and any termination logs |
| `evidence\guest-status.json` | Final guest result for convenient readback |
| `evidence\validation\` | Common harness installation and validation evidence |

Every prerequisite attempt has a unique directory. Incomplete attempts retain
their most recent stage status and transcript. A missing final guest status can
mean startup failed or the guest closed early. A nonzero harness exit is a failure;
read its evidence for the failing stage. Starting the same configuration again
does not erase prior attempts, but validation refuses to reuse existing validation
evidence. Generate a new run directory for each fresh installation test.

The guest gives the WinGet prerequisite process 30 minutes, the Git installer
10 minutes, Git clone and checkout 15 minutes each, Git fetch 10 minutes, and the
common installation harness 120 minutes. Individual artifact requests have a
600-second timeout. On a process timeout, the launcher targets only its own child
PID and descendants with `taskkill /T /F`, records a failed result, and preserves
logs. A termination failure is recorded as a failure and must be reviewed.
The guest is not automatically closed or restarted. These are stage limits, not
a 120-minute limit on the entire Sandbox session.

Closing Sandbox discards its installed applications and clone. Only mapped evidence
persists. A completed test covers the selected revision, CPU environment, and
harness checks. It does not establish CUDA support, every model or media workflow,
every Windows build, or an untouched consumer-desktop installation.

## Bootstrap provenance and hosted reuse

`scripts/windows_sandbox/bootstrap-artifacts.json` pins Git 2.55.0.5 and WinGet
1.29.290 by official release URL and SHA256. The hashes come from the official
[Git for Windows release](https://github.com/git-for-windows/git/releases/tag/v2.55.0.windows.5)
and [Microsoft WinGet release](https://github.com/microsoft/winget-cli/releases/tag/v1.29.290).
Downloads fail closed on a hash mismatch. The Git executable must also have a valid
Authenticode signature. Appx deployment performs Windows package signature
validation for WinGet and its x64 dependencies; the script does not bypass it.
Future pin updates require reviewing release metadata and package contents.

Hosted Windows x64 jobs can reuse the prerequisite entry point:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\windows_sandbox\install_winget.ps1 -EvidenceDirectory C:\InstallEvidence\bootstrap-evidence
```

This installer permits only the Sandbox default account or both
`GITHUB_ACTIONS=true` and `RUNNER_ENVIRONMENT=github-hosted`. Persistent self-hosted
Actions runners are rejected.
The check prevents ordinary accidental host execution; it is not a security
boundary against a caller who changes their environment. A working existing
WinGet is recorded and reused. Otherwise the pinned bundle is installed. The
separate process does not change its caller's PATH; callers should discover
`winget.exe` through App Installer registration or refresh PATH after bootstrap.

## Local verification without installation

The focused tests generate actual XML in unique directories, check mapped-folder
boundaries and path escaping, reject invalid inputs, preserve existing evidence,
test hash-mismatch rejection, and parse all scripts. They do not enable Sandbox
or execute installers. They also start harmless PowerShell child/grandchild
fixtures to verify argument quoting and timeout cleanup. Normal process-management
permissions are required; a restricted execution token can deny `taskkill /T`.
Test artifacts are retained for inspection.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\windows_sandbox\tests\Test-SandboxConfiguration.ps1 -TestDirectory "$env:TEMP\TCD-SandboxTests"
```

Passing these local checks proves configuration behavior and PowerShell parsing.
The WinGet Appx installation, feature enablement, Sandbox startup, full download
chain, and common harness still require execution in their intended environments.
