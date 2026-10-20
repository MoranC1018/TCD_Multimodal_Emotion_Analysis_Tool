# Installation and validation

Use this guide from the repository root. All Python commands explicitly use
the project environment; running the installer does not activate the caller's
PowerShell session. The tested September path is Windows 11 x64, Python 3.12.1
and CPU processing. Windows 10 is a supported target, but was not independently
tested in that run. CUDA and other Python versions need their own acceptance.

See [release validation](RELEASE_VALIDATION_2026-09-04.md) for software results
and the separate research-paper gate. Successful installation does not establish
scientific validity or reproduce a historical study by itself.

## Obtain and identify the source

Install Git with Git LFS support, then obtain the intended published source
revision. For a new checkout:

```powershell
git clone https://github.com/MoranC1018/TCD_Multimodal_Emotion_Analysis_Tool.git
Set-Location TCD_Multimodal_Emotion_Analysis_Tool
git lfs install --local
git rev-parse HEAD
git status --short
```

Record the commit before installation. A clone of `main` obtains whatever is
currently published; compare it with the revision accompanying the release you
intend to validate. The initial September audit stage stopped at a local side
branch without publication; later review-branch or release publication is a
separate step. An existing working checkout should be preserved, not reset to
follow this example.

The Text runtime is a tracked Git LFS object. A small text file beginning with
`version https://git-lfs.github.com/spec/v1` is a pointer, not an executable JAR.
Setup attempts a pull scoped to the exact RockSteady path when it is absent or
a pointer. A ZIP/source archive without materialized LFS bytes and repository
metadata is not sufficient for that recovery. Use a Git checkout with object
access or a correctly materialized release artifact.

## Prerequisites and installation scope

| Component | Installer behavior and requirement |
| --- | --- |
| Python | Accepts Python 3.11 or newer during discovery, prefers 3.12, and can install the Python 3.12 fallback through WinGet. Use x64 Python. Discovery alone does not prove wheel compatibility for every accepted version. |
| Project environment | Creates or reuses `.venv`. An incompatible environment is moved aside only after a replacement interpreter is resolved. Keep any backup until the new environment is verified. |
| PyTorch family | Installs matched torch 2.11.0, torchvision 0.26.0 and torchaudio 2.11.0 from the selected CPU/cu128 index, plus the supported Windows CPU TorchCodec 0.13.0 wheel. |
| FFmpeg | Requires FFmpeg 8.1.2 full-shared, including `ffmpeg.exe`, `ffprobe.exe` and shared DLLs. Installs `Gyan.FFmpeg.Shared` through WinGet when the exact runtime is absent. An executable-only build is insufficient for native Face. |
| Text/JDK | Materializes and validates the tracked RockSteady 0.4 JAR and embedded default dictionary. Locates a working JDK containing both `java` and `javac`, or installs `EclipseAdoptium.Temurin.21.JDK`. An existing working JDK can be reused. |
| Native desktop | Requires Microsoft Edge WebView2 Runtime for the native window. Setup does not install or certify WebView2. A desktop-shell failure is logged and can fall back to browser app mode. |
| Acoustic processing | Uses the bundled OpenSMILE executable and eGeMAPS configuration, or a compatible distribution selected through `OPENSMILE_HOME`. Audio doctor resolves their actual paths. |
| Test automation | Node.js, npm, Playwright and a Chromium/Edge browser are separate testing prerequisites. They are not installed by the Python setup. |

Automatic prerequisite installation requires WinGet/App Installer and permission
to install the selected packages. On managed machines, have IT provision the
prerequisites first and use the corresponding skip-install switches below.

Installation needs network access to Python package indexes, the selected
PyTorch index, WinGet package sources when used, repository Git LFS when needed,
and the Face checkpoint host. Audio, Whisper and Clean Speaker may need further
model downloads on first use. Gated-model access depends on the selected backend
and account authorization. An installed Python package is not proof of model
access. Use a writable local NTFS location and allow space for the environment,
model caches, input/output media, temporary files and reports; no universal
minimum storage or RAM requirement has been established.

## Install the tested CPU configuration and retain a log

Use a fresh evidence directory outside the source tree. This example creates
one beneath the application's local data directory:

```powershell
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$evidence = Join-Path $env:LOCALAPPDATA "MultimodalEmotionAnalysisTool\validation\$runStamp"
New-Item -ItemType Directory -Path $evidence -ErrorAction Stop | Out-Null
git rev-parse HEAD | Set-Content (Join-Path $evidence 'source-commit.txt')

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -TorchRuntime cpu -TextMode Require 2>&1 |
    Tee-Object -FilePath (Join-Path $evidence 'setup.log')
$setupExit = $LASTEXITCODE
$setupExit | Set-Content (Join-Path $evidence 'setup-exit.txt')
if ($setupExit -ne 0) { throw 'Setup failed; inspect setup.log before continuing.' }

.\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'The project dependency check failed.' }
.\.venv\Scripts\python.exe -m pip freeze | Set-Content (Join-Path $evidence 'installed-packages.txt')
```

The required success message is `Setup complete: Face READY; Text/RockSteady
READY.` Read warnings as well as the exit code. Setup is rerunnable, but it can
repair or change the environment and can still require network access. Stop
active analysis jobs before changing dependencies. Do not upgrade individual
PyTorch family members or apply unpinned package-upgrade recipes afterward.

| Option | Meaning |
| --- | --- |
| `-TorchRuntime cpu` | Explicit CPU selection used by the September acceptance run. |
| `-TorchRuntime auto` | Default; selects CUDA 12.8 when its GPU/driver probe accepts a device, otherwise CPU. This can differ from the tested CPU configuration. |
| `-TorchRuntime cu128` | Requires the matched CUDA 12.8 family and a successful real CUDA computation during setup. It needs a separate workload acceptance run. |
| `-TextMode Require` | Fails unless Text runtime readiness succeeds. Use this for the full multimodal setup gate. |
| `-TextMode Auto` | Default; attempts Text setup, but can finish with Face ready and Text not ready when the JAR cannot be obtained. Inspect the final modality status. |
| `-TextMode Skip` | Explicitly skips JDK/Text setup; this is a partial installation. |
| `-SkipPythonInstall` | Prevents automatic Python installation; a compatible interpreter must already exist. |
| `-SkipJdkInstall` | Prevents automatic JDK installation; Text still requires a working JDK when enabled. |
| `-SkipSharedFfmpeg` | Prevents FFmpeg installation; exact shared-runtime validation still applies. |

The switches suppress installation, not prerequisite failures. Use
`Get-Help .\scripts\setup.ps1 -Full` to inspect the current script's parameters.

## Recheck each modality

These checks do not request model downloads:

```powershell
.\.venv\Scripts\python.exe -m processing.face_analysis --check
.\.venv\Scripts\python.exe -m processing.text_analysis --check
.\.venv\Scripts\python.exe processing/audio_analysis/run_audio_analysis.py doctor
```

Check each command's exit status and output before continuing. For Clean
Speaker, use **Check model readiness** in its application screen.

| Check | What it establishes | What still needs a real input run |
| --- | --- | --- |
| Face `--check` | Local pinned checkpoint integrity, offline Detectorv2 construction and native decoding readiness. | Input-specific decoding, detection quality, resource use and expected artifacts. |
| Text `--check` | Whisper/Torch/FFmpeg identity and expected checkpoint identity; RockSteady adapter compilation, dictionary and category checks for the requested configuration. | Whisper checkpoint availability/loading, transcription and the complete Text output chain. First transcription can still need a download. |
| Audio `doctor` | Required package imports, audio I/O and local FFmpeg/FFprobe/OpenSMILE resolution. Optional codec warnings are reported separately. | Actual emotion checkpoint loading/inference, selected model or fallback, and acoustic output contents. |
| Clean Speaker readiness | Required local tools plus available model files, packages and configured access indicators. | Successful backend inference, gated access, usable identity/voice intervals and final media. |

Face model preparation is an explicit network-enabled operation performed by
setup; normal Face checks and runs use validated local checkpoints. Audio's
preferred nine-class backend was unavailable in the September acceptance and
the manifest recorded SUPERB four-class fallback. Unsupported classes must
remain missing. Inspect each run's model names, versions, warnings and output
columns before interpreting results.

Record executable paths and versions from readiness/run manifests. The
installer and launcher configure the shared Face runtime, but an independently
started CLI can resolve another FFmpeg earlier on its PATH. Merely seeing
`ffmpeg -version` succeed does not prove every process used the same binary.

## Full software checks and browser prerequisites

Install Node.js with npm and ensure `node` and `npm` resolve in the shell. Use a
separate local Playwright installation; the September browser harness used
Playwright 1.62.1. This example uses an already installed Edge browser:

```powershell
$browserTools = Join-Path $env:LOCALAPPDATA 'MultimodalEmotionAnalysisTool\browser-tests'
npm install --prefix $browserTools --no-audit --no-fund playwright@1.62.1
if ($LASTEXITCODE -ne 0) { throw 'Playwright installation failed.' }
$env:MEAP_TEST_NODE = (Get-Command node -ErrorAction Stop).Source
$env:MEAP_TEST_PLAYWRIGHT = Join-Path $browserTools 'node_modules\playwright'
$edgeCandidates = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$env:MEAP_TEST_BROWSER_EXECUTABLE = $edgeCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $env:MEAP_TEST_BROWSER_EXECUTABLE) { throw 'Set MEAP_TEST_BROWSER_EXECUTABLE to an installed Chromium/Edge executable.' }
$env:MEAP_STRICT_BROWSER_TESTS = '1'

.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Test dependency installation failed.' }
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_setup.ps1
if ($LASTEXITCODE -ne 0) { throw 'Installer contract verification failed.' }
.\.venv\Scripts\python.exe -m pytest application procurement processing analysis tools -q -ra --junitxml="$evidence\regression.xml" --basetemp="$evidence\pytest-temp"
if ($LASTEXITCODE -ne 0) { throw 'Regression suite failed.' }
& $env:MEAP_TEST_NODE --check application/static/app.js
if ($LASTEXITCODE -ne 0) { throw 'JavaScript syntax validation failed.' }
```

Use the fresh `$evidence` directory created above; pytest's `--basetemp` is
test-owned scratch space and can be cleared by pytest on reuse. The default
`pytest -q` configuration omits the `tools` directory. Strict browser mode makes
missing browser automation a failure instead of a skip. Read all remaining
skip reasons; the September run lacked Windows symbolic-link privileges for
13 tests, while real junction-boundary tests executed.

The fast browser contract test uses mocked API responses. Also run
[real launcher E2E acceptance](../application/tests/REAL_BROWSER_ACCEPTANCE.md)
with the same resolved Node, Playwright and browser paths and a new output
directory. It exercises production handlers/subprocesses and checks media and
workbook artifacts. It does not certify the native desktop wrapper, Face/Text
model inference, scientific accuracy or Excel formula recalculation. Those
require their separately recorded checks. Retain logs, screenshots, dependency
inventory, selected model manifests and the source revision for the complete
acceptance record. Review logs for private paths or credentials before sharing.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| WinGet is missing or blocked | Have IT provide App Installer or the named prerequisites; rerun with the relevant skip-install switches only after they exist. |
| No compatible Python or no matching distribution | Use the tested x64 Python 3.12 path and verify which interpreter `.venv` contains. A newer version being discovered does not guarantee compiled wheels exist. Preserve an existing environment before replacing it. |
| RockSteady is missing or a pointer | Verify `git lfs version`, repository/object access and `git lfs install --local`; rerun setup with Text required. Do not rename a pointer to make it look like a JAR. |
| RockSteady integrity fails | Recover the exact tracked object from the intended source revision. Do not bypass the byte-size/hash check or substitute a different JAR. |
| Java exists but Text fails compilation | Check both `java -version` and `javac -version`; Text needs a complete JDK. Let setup resolve/install it or have IT provision one. |
| TorchCodec/Face reports missing DLLs | Use the exact full-shared FFmpeg runtime and matched package family; rerun Face readiness. A plain FFmpeg executable on PATH is insufficient. |
| Audio doctor passes but emotion columns are blank | Inspect the per-video model/fallback warning and selected backend; doctor does not validate checkpoint loading. Check model access/download completion and the emotion-model toggle. |
| Audio rejects an oversized window | Emotion-enabled windows must be at most 15 seconds. Keep the usual 10-second window/5-second stride, or explicitly use `--skip-emotion-models` for longer acoustic-only windows. |
| Text preflight passes but first transcription fails | Inspect checkpoint download/cache, media decode and memory errors; the preflight does not load Whisper weights. |
| Native window cannot open | Verify WebView2 is installed and inspect launcher logs. A working browser harness does not prove native WebView2 startup. |
| OneDrive placeholder or intermittent file access | Hydrate files fully and prefer local non-synced NTFS processing/evidence paths. Persistent sharing/access failures still propagate after bounded retries. |
| Model-cache symlink warning | Windows can use a larger copy-based Hugging Face cache without symlink privileges; distinguish that warning from an actual missing/corrupt model. Do not count a skipped boundary test as passed. |

## Observed installation reliability

The September audit created a new project virtual environment on one existing
Windows 11 host. Python 3.12.1, Git/LFS and a working JDK were already installed;
the successful setup selected Java/Javac 26.0.1. It did not exercise a pristine
Windows image or automatic missing-Python/JDK installation end to end.

The first controlled run installed the Python packages but stopped because
FFmpeg 8.1.2 full-shared was absent and its installation had deliberately been
disabled. The next supported run reused that environment, installed exact
shared FFmpeg, prepared/validated Face checkpoints and completed Face and
Text/RockSteady readiness. Subsequent package changes were followed by the
regression and real processing checks described in the release report. The
installer contract verifier also exercises failure/recovery cases with mocks;
those are not independent successful installations.

These observations establish the recorded scenarios on this host. They do
**not estimate an installation error rate across users or machines**. Repeated
runs share a host, caches, network and repairs; dividing them into a percentage
would create a misleading denominator. Clean-OS, CUDA, other Python versions,
proxy/offline access, and automatic Python/JDK provisioning remain separate
validation scenarios. The package inventory is a record of the tested
environment, not a portable lockfile with every wheel index and hash.

For future installation evidence, record each machine/configuration, fresh or
reused environment, command, starting prerequisites, source commit, elapsed
time, exit status and required intervention. Separate prerequisite/network,
installer, model-access, cancellation and retry outcomes. Report a population
rate only after defining and collecting independent installation attempts;
until then, report scenario outcomes and unresolved coverage.
