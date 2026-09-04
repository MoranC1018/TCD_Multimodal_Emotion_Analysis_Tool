# Multimodal Emotion Analysis Tool

Windows research software for collecting video, extracting multimodal signals,
and producing reproducible statistical reports. The application connects three
stages:

```text
Procurement -> Processing -> Analysis
```

- **Procurement** reviews video sources and creates full, sampled, focused, or
  clean-speaker media.
- **Processing** runs or imports face, audio, and text outputs.
- **Analysis** creates per-video and per-speaker statistics, histograms,
  comparisons, and audit manifests.

This is research software, not a diagnostic system. Researchers remain
responsible for copyright, model licences, consent, privacy, data protection,
interpretation of generated results, and any action taken from them.

## Academic Provenance And Release Boundary

The **Multimodal Emotion Analysis Tool** was developed by Conor Moran and
Jiaming Liu, with academic direction from Professor Khurshid Ahmad and Dr
Tracey Hilton at the School of Computer Science, Trinity College Dublin, the University of Dublin. Institutional affiliation does not imply endorsement
of particular findings.

The native Face/Text engines and their initial research contracts were adapted
from PR 3 (`e6e886255b55b76137fdc40ca8734e971cd420b8`), authored by Jiaming Liu.
This integration preserves that provenance while binding the engines to the
current source-manifest, Analysis, security, and desktop-application contracts.

Project-authored code and documentation are released under the root
[MIT License](LICENSE). Bundled third-party components retain their own terms:
in particular, OpenSMILE 3.0.0 is excluded from the MIT License and remains
under the audEERING Research License, including its non-commercial boundary.
Read [Third-Party Notices](THIRD_PARTY_NOTICES.md) before reuse or
redistribution. Attribution and contribution guidance are in
[AUTHORS.md](AUTHORS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Contents

1. [Current capabilities](#current-capabilities)
2. [Installation](#installation)
3. [Initial credential setup](#initial-credential-setup)
4. [Recommended workflow](#recommended-workflow)
5. [Inputs and outputs](#inputs-and-outputs)
6. [Resource controls and benchmark](#resource-controls-and-benchmark)
7. [Command-line use](#command-line-use)
8. [Verification and troubleshooting](#verification-and-troubleshooting)
9. [User manual](#user-manual)

## Current Capabilities

| Stage | Available in the application | Current boundary |
| --- | --- | --- |
| Procurement | YouTube URL, CSV/DOCX catalog, local video, or recursive folder input | Online metadata depends on YouTube availability and API quota |
| Standard sampling | Configurable random percentage and maximum clip length | Sampling is random and non-overlapping |
| Full video | Keeps or downloads the complete source | Requires enough output storage |
| Focus | Interactive timeline and exact segment selection | MP4 and WebM are the most reliable local preview formats |
| Clean speaker segments | Face visibility, voice activity, overlap selection, and stitching | Model-backed runs require the dependencies described below |
| Face processing | Native Py-Feat processing or import | Cached Detectorv2 models and the native Python stack must pass readiness |
| Audio processing | OpenSMILE and optional audio-emotion models | OpenSMILE 3.0.0 uses the audEERING Research License; review its non-commercial/product boundary |
| Text processing | Native Whisper/RockSteady processing or import | The authorized RockSteady 0.4 JAR is versioned with Git LFS; a JDK remains an external requirement |
| iMotions analysis | Emotions, action units, movement, geometry, and comparisons | Expects valid iMotions CSV exports |
| Native Face analysis | Primary-face Py-Feat emotion, valence, and arousal reports | Kept distinct from iMotions/AFFDEX because the providers are not interchangeable |
| Audio analysis | Emotion-model and OpenSMILE report generation | Expects outputs from this tool's audio processor |

Generated videos, audio, iMotions exports, API credentials, model weights,
caches, logs, and reports are intentionally excluded from git.

## Installation

### 1. System Requirements

The supported desktop path is Windows 10 or Windows 11 on x64 hardware.
The September validation used Windows 11, Python 3.12.1 and CPU processing on
one existing research machine. Other configurations need their own acceptance
checks; this is not a measured installation success rate.

Required components:

- Python 3.11 or newer. The automatic setup can install the recommended Python
  3.12 fallback when no compatible interpreter is present. Use x64 Python;
  accepting a version during discovery does not prove that every dependency
  provides a compatible wheel for it.
- [FFmpeg](https://ffmpeg.org/download.html), including `ffmpeg` and
  `ffprobe`. The automatic setup installs and selects the exact supported
  FFmpeg 8.1.2 full-shared runtime. Both executables and its shared DLLs are
  required for native Face; executable-only builds are insufficient.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), installed by
  `requirements.txt` or available on `PATH`.
- Microsoft Edge WebView2 Runtime for the native desktop window. Verify its
  availability on managed or minimal Windows installations.
- The bundled OpenSMILE 3.0.0 Windows distribution for audio acoustic
  features. Keep its complete `LICENSE` and `licenses/` tree. `OPENSMILE_HOME`
  can select a separately installed compatible distribution when required.
- Git and Git LFS when obtaining the source or materializing the tracked
  RockSteady JAR. A source archive containing only its LFS pointer is incomplete.
- WinGet/App Installer when setup must install Python, FFmpeg or a JDK;
  alternatively, have those prerequisites provisioned before running setup.
- Network access for package installation and missing model downloads, and
  writable space for `.venv`, model caches, media, temporary files and reports.

.\.venv\Scripts\python.exe 3.11 or newer is required by the pinned dependency stack. Python 3.12 is
tested and recommended, while other compatible versions are accepted. If
`scripts\setup.ps1` cannot find a compatible interpreter and installation is
allowed, its automatic fallback installs Python 3.12.

See [Installation and validation](docs/INSTALLATION_VALIDATION.md) for source
acquisition, exact prerequisite checks, managed-machine options and recovery.

### 2. Create The Python Environment

The supported automatic Windows setup creates or reuses `.venv`, installs the
matched CPU/CUDA PyTorch family and project requirements, verifies the exact
shared FFmpeg runtime, prepares Face model weights, and checks readiness. From
the repository root, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -TorchRuntime cpu -TextMode Require
if ($LASTEXITCODE -ne 0) { throw 'Setup failed; inspect its log before continuing.' }
```

The setup may use WinGet for a missing Python 3.12 fallback, the exact supported
FFmpeg runtime, or a JDK when Text is enabled. After every WinGet attempt it
verifies the actual required files and commands; an already-installed package
is accepted when that post-install verification succeeds.

The command above selects the tested CPU path and requires Text readiness.
The default `-TorchRuntime auto` can select CUDA; default `-TextMode Auto` can
finish with Face ready and Text not ready. Read the final status for both
modalities. Setup prepares Face checkpoints and checks the Text runtime, but
first-use Audio, Whisper and Clean Speaker model downloads may still be needed.
Run a short representative input and inspect its manifests before a study batch.

If Python, PyTorch, FFmpeg, and model preparation are managed separately, the
manual Python-only path is:

```powershell
.\.venv\Scripts\python.exe -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The manual path does not select a CPU/CUDA wheel family, install the required
shared FFmpeg DLLs, prepare Face weights, or perform the setup readiness checks.

For automated tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

The launcher prefers `.venv\Scripts\python.exe`, then prefers Python 3.12 while
discovering other Python 3.11-or-newer installations with `pywebview`. Keeping
a repository-local environment makes package versions predictable.

### 3. Optional CUDA Setup

Use the installer to keep torch, torchvision, torchaudio and TorchCodec on the
project's matched versions:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -TorchRuntime cu128 -TextMode Require
if ($LASTEXITCODE -ne 0) { throw 'CUDA setup failed; inspect its log before continuing.' }
```

The CUDA option checks the selected runtime with a real device computation.
CUDA was not certified by the September CPU acceptance run. Avoid independently
upgrading individual members of the PyTorch family.

Check the active environment:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

Selecting **CUDA** in the application does not install CUDA. It requires the
command above to report `True`.

### 4. Launch

Double-click:

```text
Launch_Video_Processing_Stack.bat
```

The application opens in a native WebView2 desktop window without browser
navigation controls. The first launch presents the EULA as a native dialog.
Acceptance is recorded in ignored local file `_local/eula.txt`, for example:

```text
# data: accepted_at=2026-07-27T14:33:33Z
terms_accepted=true
```

Every screen rechecks this local value. Revoking access changes it to `false`
and closes the application.

## Initial Credential Setup

Open **Settings** from the top-left of the home screen.

### YouTube Data API

**Required credential type:** a Google Cloud **API key** for
**YouTube Data API v3**. OAuth client credentials, service-account JSON, and a
YouTube account password are not required for the public metadata used here.

1. Sign in to Google Cloud and create or choose a project.
2. Enable **YouTube Data API v3**.
3. Create an API key under the project's credentials.
4. Restrict the key to **YouTube Data API v3** where practical.
5. Paste it into **Settings > YouTube Data API key** and select **Save
   settings**.

Google's current setup reference is
[YouTube Data API Overview](https://developers.google.com/youtube/v3/getting-started).

The key improves title, duration, upload-date, thumbnail, and licence metadata.
Direct URLs and `yt-dlp` provide fallbacks, but some fields may remain
`Unknown` when the API is unavailable or its quota is exhausted.

### Hugging Face

**Required credential type:** a Hugging Face **User Access Token**. A
**fine-grained token with read access** is recommended. A general `read` token
also works, but the application does not need write, billing, organization
administration, or Inference Provider permissions.

Create the token at the
[Hugging Face token settings](https://huggingface.co/settings/tokens), following
the [User Access Token guide](https://huggingface.co/docs/hub/en/security-tokens).
For pyannote diarization, the same Hugging Face account must first accept the
conditions on both gated repositories:

- [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)

For a fine-grained token, grant read access to those repositories. Paste the
token into **Settings > Hugging Face token** and save it. A token alone cannot
bypass model conditions that the account has not accepted.

### Credential Storage

Credentials are stored locally outside tracked source files. The UI returns
only `Configured` and a masked suffix after saving. Never put keys or tokens in
the README, `.env` files committed to git, screenshots, issue reports, or
shared logs.

**YouTube download fallback** can allow `yt-dlp` to use Edge, Chrome, or Firefox
cookies when YouTube requests sign-in or bot confirmation. Use it only when
needed and only with a browser profile that the researcher is permitted to
use.

## Recommended Workflow

1. Open **Settings**, configure credentials, and keep resource limits enabled.
2. Open **Procurement**.
3. Select a YouTube URL, one local video, a recursive folder, or a CSV/DOCX catalog.
4. Review speaker grouping, title, duration, upload date, thumbnail, and
   licence.
5. Untick speaker groups that are outside the study.
6. Select Standard, Full, Focus, or Clean Speaker mode.
7. Run Procurement and inspect its completion manifest.
8. Open **Processing**. Run native Face, Audio, and Text in-app, or import a
   verified existing result where the workflow permits it.
9. Open **Analysis**. Run iMotions, native Py-Feat Face, Audio, and Text reports
   without blending provider semantics.
10. Preserve the source list, processing manifests, settings, model versions,
    and generated reports with the research archive.

The **Guided workflow** switch on the home screen can move through selected
stages in order. Each processing stream can independently be run in-app where
supported or marked as an imported folder.

## Inputs And Outputs

### Procurement Inputs

| Input | Accepted form | Grouping behaviour |
| --- | --- | --- |
| YouTube | Watch, share, Shorts, or embed URL | One scanned video |
| Folder tree | Recursive MP4, MOV, MKV, WebM, or AVI files | Subfolder structure is retained and used for speaker groups |
| CSV/DOCX catalog | A required `Link` column, optional `Speaker`, and arbitrary study metadata | Rows retain catalog order and stable `source-0001` identifiers |
| Local video | One MP4, MOV, MKV, WebM, or AVI | Parent folder supplies the initial group |

Leaving the source field blank and selecting **Search** opens an in-app choice
between a modern folder picker and a modern DOCX/video file picker.

There is no application-level maximum local video byte size. The original local
media stays in place; a selected catalog row is processed from a temporary
byte-for-byte snapshot whose SHA-256 is sealed into the run manifest and
revalidated immediately before clean-speaker processing. Successful catalog
clean-speaker media is atomically published beside its source context for audio
discovery, while the reusable processing cache remains private. Practical
limits are free output storage, filesystem format, codec support, duration,
resolution, model memory, and network availability. FAT32 has a 4 GiB
single-file limit; NTFS is recommended.

Catalog headers are matched after Unicode normalization, trimming,
case-folding, and removal of spaces, underscores, and hyphens. `Upload Date`,
`Engagement`, `Date Accessed`, and `Length` columns are ignored; every other
nonblank metadata value is retained. Relative local links resolve from the
catalog directory, YouTube and local rows may be mixed, and repeated links
remain distinct SourceIDs. Filtering and sorting the review table do not alter
selection: only the row/speaker checkboxes and **Select visible** or **Clear
visible** do so. Each Face, Audio, and Text Processing screen reopens the sealed manifest from
the chosen batch folder, then offers its own metadata filter, sort, and explicit
visible-selection controls. The selected SourceIDs and catalog digest are bound
back to that same folder when the processing command starts.

Every catalog run creates a fresh child run directory. Before media processing
it seals `source_manifest.json` and spreadsheet-safe `source_metadata.csv` at
that run root. These record the catalog digest, row identity, explicit
selection, procurement options, user metadata, YouTube-reported language, and
source-to-output mapping. For a local row, the same sealed file identity is
carried into `source_context.json` and verified by audio processing. A named `Speaker` creates a speaker folder; a blank
speaker is shown as **Pooled (no speaker)** and stays directly under the run
root. Metadata fields never create directories.

### Procurement Modes

**Standard sampling**

- Defaults to 10 percent.
- Selects random, non-overlapping source intervals.
- Splits selections at the configured maximum segment length, default 30
  seconds.
- Records selected timestamps so the sample can be audited.

**Full video**

- Keeps a local source or downloads the complete online source.
- Does not apply the Standard percentage or maximum segment settings.

**Focus**

- Uses an embedded YouTube player or a local media preview.
- Accepts seconds, `MM:SS`, or `HH:MM:SS`.
- Snaps near the playhead and supports click-to-select, edge dragging, and
  deletion of selected intervals.
- Inserts the configured black/silent gap between clips. `0` joins them
  directly.

**Clean speaker segments**

- Samples the video and identifies the recurring target face.
- creates up to 20 diverse identity stills.
- Finds face-visible intervals and dominant-speaker voice intervals.
- Intersects the two timelines.
- Keeps overlaps at or above the minimum clean duration.
- **Clean compilation** retains every accepted overlap.
- **Percentage sample** fills a target percentage from the strongest and
  longest clean sections, with a configurable clip cap.

Each clean-speaker result includes selected and rejected interval metadata,
identity stills, face/voice timelines, and a stitched MP4. The strict path
fails closed when model-backed identity or voice evidence is unavailable.
Technical details and model licences are in
[Clean Speaker Setup](procurement/procurement_beta/SETUP.md) and
[Third-Party Notices](procurement/procurement_beta/THIRD_PARTY_NOTICES.md).

### Processing Outputs

Audio Processing mirrors the input speaker/video folder structure:

```text
audio_output/
  audio_analysis_manifest.csv
  run_log.txt
  Speaker_Name/
    Video_Name/
      audio_analysis.csv
      opensmile_features.csv
      audio_analysis_manifest.json
```

- `audio_analysis.csv` contains one row per time window and optional emotion
  probabilities.
- `opensmile_features.csv` contains the selected acoustic feature set.
- Manifests record source paths, models, settings, availability, and errors.

### Analysis Outputs

Reports are divided by data meaning:

```text
output/
  emotion/
    <speaker-or-run>/
      <video>/
      combined/
  raw/
    <speaker-or-run>/
      <video>/
      combined/
```

Outputs can include CSV and XLSX histograms, SVG graphs, log-scale histograms,
descriptive statistics, chi-squared comparisons, pairwise matrices, Spearman
comparisons, region correlations, and column manifests. Each speaker receives
individual video reports and one `combined` report across that speaker's input
files.

Log-scale histograms use:

```text
log10(count + 1)
```

They supplement, rather than replace, the linear counts. Full formulas and
column contracts are documented in
[Analysis Calculations](analysis/CALCULATIONS.md).

## Resource Controls And Benchmark

### What The Controls Mean

- **Maximum CPU load** is both a process-tree pause threshold and the basis for
  logical-processor affinity.
- **Maximum CPU cores** applies an additional affinity cap. `0` means the CPU
  percentage chooses the count automatically.
- **Maximum GPU load** monitors system-wide NVIDIA utilization with
  `nvidia-smi`; it cannot attribute shared GPU load to one process.
- **System RAM percentage** protects whole-machine headroom.
- **Tool process RAM in GB** monitors resident memory in the launched process
  tree instead.
- **Native library threads** limits OpenMP, MKL, OpenBLAS, NumExpr, ONNX, and
  related native worker pools per process.
- **Monitor interval** controls how often the launcher samples resources.

The launcher pauses and resumes with hysteresis. Sustained RAM pressure can
terminate the process tree after 30 seconds. These controls reduce crash risk
but cannot prevent driver resets, hardware faults, or unreported native
allocations.

### Reference Computer

Benchmarks in this repository were measured on:

| Component | Reference hardware |
| --- | --- |
| CPU | AMD Ryzen 9 5900X, 12 cores / 24 logical processors, up to 4.2 GHz |
| RAM | 23.9 GiB |
| GPU | NVIDIA GeForce RTX 3070, 8 GiB VRAM |
| Current model runtime | PyTorch 2.10 CPU build; CUDA unavailable in that environment |

Metadata-only bounded stress tests:

| Operation | Scale | Wall time | Peak traced Python memory |
| --- | ---: | ---: | ---: |
| Recursive folder scan | 100 videos | 0.0819 s | 0.115 MB |
| Recursive folder scan | 1,000 videos | 0.7389 s | 1.006 MB |
| Recursive folder scan | 5,000 videos | 3.6698 s | 4.998 MB |
| DOCX table scan | 100 rows | 0.4909 s | 2.225 MB |
| DOCX table scan | 1,000 rows | 4.7481 s | 2.623 MB |
| DOCX table scan | 5,000 rows | 24.0104 s | 7.655 MB |

Real Clean Speaker runs measured on 2026-07-28 used a curated 20-image face
bank, 1 FPS scanning, 1 FPS candidate validation, one CPU-backed video at a
time, a 10-second minimum overlap, 0.5-second gaps, and no final pruning pass:

| Video | Source duration | Clean output | Accepted overlaps | Face | Voice | Candidate validation | Stitch | End to end |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Reference video A | 15:26.0 | 11:10.6 | 19 | 217.6 s | 40.7 s | 210.4 s | 128.8 s | about 9:59 |
| Reference video B | 31:43.5 | 12:24.0 | 40 | 106.0 s | 72.9 s | 86.8 s | 89.9 s | about 6:29 |

Both runs completed with zero failed and zero unusable videos. The longer
reference source finished faster because runtime follows accepted candidate
density, decoding, validation, and stitch work rather than duration alone.

Times are reference observations, not guarantees. Video duration, resolution,
codec, face density, number of candidates, model cache state, storage speed,
and network access can dominate runtime.

### Recommended Settings For Similar Hardware

For a 12-core Ryzen, 24 GiB RAM, and 8 GiB NVIDIA GPU:

| Setting | Recommended starting value | Reason |
| --- | ---: | --- |
| Enforce limits | On | Keeps every launched mode under one policy |
| Maximum CPU load | 85% | Leaves capacity for Windows, decoding, and the UI |
| Maximum CPU cores | 20 | Leaves four logical processors outside affinity |
| Maximum GPU load | 90% | Leaves display and driver headroom |
| RAM limit type | System RAM percentage | Includes the pipeline and unrelated applications |
| Maximum system RAM | 85% | Leaves roughly 3.6 GiB on a 23.9 GiB system |
| Native library threads | 4 | Avoids multiplication of large native pools |
| Monitor interval | 2 seconds | Responsive without excessive polling |

Clean Speaker starting values:

| Setting | Recommended value |
| --- | ---: |
| Concurrent videos | 1 |
| Run one video per process | On |
| Skip completed outputs | On |
| Cooldown between videos | 30-60 seconds |
| Parallel face/audio analysis | Off |
| Scan FPS | 1 |
| Candidate validation FPS | 1-2 for throughput; 4 for stricter cutaway checking |
| Max YouTube height | 720 |
| Identity stills | 20 |
| Face confidence | 0.65 |
| Speaker confidence | 0.65 |
| Keep debug artifacts | Off except during diagnosis |

Store large runs on a local, non-synced NTFS drive. Copy results into OneDrive
or another sync service only after the run. On this reference environment,
model execution is CPU-backed until a CUDA PyTorch build is installed.

## Command-Line Use

The unified CLI runs the existing Procurement, Face, Audio, Text, and Analysis
engines without opening the desktop application. Jobs can contain one stage or
a sequential workflow with explicit output handoffs, metadata profiles,
resource limits, logs, cancellation and deadlines.

See the [complete CLI and automation guide](docs/CLI.md) for all commands,
exact parameter defaults, stage/resume controls, scheduling instructions and
[ready-to-edit JSON examples](docs/CLI.md#example-jobs). The desktop interface
and existing module commands remain available.

From the repository root after setup:

```powershell
$python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $python -m application.cli --help
& $python -m application.cli doctor --component procurement
& $python -m application.cli inspect source 'C:\Research\TrinityStudy\media' --no-enrich

# Replace these study paths with your own and edit the job before running.
$job = 'C:\Research\TrinityStudy\jobs\study.json'
$run = 'C:\Research\TrinityStudy\runs\study-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& $python -m application.cli validate --job $job --run-dir $run
if ($LASTEXITCODE -ne 0) { throw 'Job validation failed.' }
& $python -m application.cli run --job $job --run-dir $run --timeout 43200
if ($LASTEXITCODE -ne 0) { throw "Workflow failed. Inspect $run" }
```

The evidence directory must be new. Relative paths inside a job resolve from
the job file's directory. Commands return JSON on stdout and diagnostics on
stderr; processing stages retain their own manifests and provenance. A plan
can defer checks that require an earlier stage's outputs. Readiness checks do
not install dependencies, download weights, or establish model accuracy.

Existing low-level commands still work, for example:

```powershell
& $python -m processing.face_analysis --help
& $python -m processing.text_analysis --help
& $python processing\audio_analysis\run_audio_analysis.py doctor
& $python -m analysis.workflow --help
```

See the [CLI acceptance record](application/tests/REAL_CLI_ACCEPTANCE.md) for
the actual tested workflows and remaining validation limits.

## Verification And Troubleshooting

Run the installer contract checks and complete Python collection from the
repository root using its environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_setup.ps1
.\.venv\Scripts\python.exe -m pytest application procurement processing analysis tools -q -ra
node --check application\static\app.js
```

The fast Analysis browser test runs in a real browser with mocked API responses.
It is optional during normal development. Its portable resolver accepts these
environment variables:

| Variable | Purpose |
| --- | --- |
| `MEAP_TEST_NODE` | Full path to the Node.js executable |
| `MEAP_TEST_PLAYWRIGHT` | Folder containing the installed Playwright package |
| `MEAP_TEST_BROWSER_EXECUTABLE` | Full path to Microsoft Edge or another Chromium executable |
| `MEAP_STRICT_BROWSER_TESTS=1` | Fail instead of skip when browser automation is unavailable; use this in release CI |

Example strict Edge check:

```powershell
$env:MEAP_TEST_NODE = "C:\Program Files\nodejs\node.exe"
$env:MEAP_TEST_PLAYWRIGHT = "C:\path\to\node_modules\playwright"
$env:MEAP_TEST_BROWSER_EXECUTABLE = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$env:MEAP_STRICT_BROWSER_TESTS = "1"
.\.venv\Scripts\python.exe -m unittest application.tests.test_release_ui_contract.ReleaseUiContractTests.test_analysis_browser_interactions_and_responsive_rendering -v
```

Unset the variables after a local check if they should not affect later test
runs. Without overrides, the test searches common Node, Playwright, and Edge
locations and skips with setup guidance when optional browser automation is
not installed.

Release acceptance also requires the separate
[real launcher E2E suite](application/tests/REAL_BROWSER_ACCEPTANCE.md), which
uses production HTTP handlers and actual subprocesses. Node/Playwright setup,
evidence capture and readiness boundaries are documented in
[Installation and validation](docs/INSTALLATION_VALIDATION.md).

Before Clean Speaker or native Face, select the corresponding **Check model
readiness** action. Face preparation is an explicit network-enabled action;
normal Face runs are offline and receive no credentials. Before Audio, run the
`doctor` command above. Native Text readiness checks Whisper, FFmpeg, the JDK,
and the Git LFS-managed RockSteady 0.4 JAR/dictionaries before processing.
Text preflight does not load a Whisper checkpoint, and Audio doctor does not
run emotion-model inference. A successful check does not guarantee model-host
access, the preferred Audio backend, or successful processing of every input.

Common causes:

| Symptom | Check |
| --- | --- |
| Duration, thumbnail, or licence is unknown | YouTube API key, quota, private/deleted video, then `yt-dlp` availability |
| YouTube download requests sign-in | Update `yt-dlp`; configure the browser-cookie fallback only when permitted |
| Clean Speaker produces no output | Readiness report, Hugging Face token, accepted pyannote conditions, identity reference quality, and confidence thresholds |
| CUDA option fails | `torch.cuda.is_available()` must be `True` in the exact launcher environment |
| Audio emotion columns are blank | Emotion models toggle, audio `doctor`, model downloads, and manifest warnings |
| OpenSMILE output is missing | `OPENSMILE_HOME`, executable/config path, and audio `doctor` |
| Native Face is not ready | Run its structured readiness check; install the pinned native stack and explicitly prepare cached Detectorv2 weights |
| Native Text is not ready | Install the pinned Whisper stack and a supported JDK; rerun setup so it can materialize and validate the exact Git LFS-managed RockSteady 0.4 runtime |
| Focus video does not preview | Try MP4/WebM, but processing may still work through FFmpeg |
| Long run pauses | Resource monitor has reached CPU, GPU, or RAM limit; inspect the visible launcher/PowerShell log |
| OneDrive file is unavailable | Hydrate the file locally or move the run to a non-synced NTFS folder |

Further technical documents:

- [Research Methods and Reproducibility](docs/RESEARCH_METHODS.md)
- [Installation and validation](docs/INSTALLATION_VALIDATION.md)
- [Current software release review and defect register](docs/RELEASE_REVIEW_2026-09-04.md)
- [September release validation and remaining gates](docs/RELEASE_VALIDATION_2026-09-04.md)
- [Historical August readiness report](docs/RELEASE_READINESS.md)
- [Analysis Calculations](analysis/CALCULATIONS.md)
- [Native Face Processing Contract](processing/face_analysis/README.md)
- [Native Text Processing Contract](processing/text_analysis/README.md)
- [Audio Processing Contract](processing/audio_analysis/README.md)
- [Clean Speaker Setup](procurement/procurement_beta/SETUP.md)
- [Third-Party Notices](procurement/procurement_beta/THIRD_PARTY_NOTICES.md)

# User Manual

## Home Screen

| Control | What it does |
| --- | --- |
| Settings icon | Opens credentials, download fallback, resource controls, and EULA access controls |
| Procurement tile | Opens video source selection and Procurement modes |
| Processing tile | Opens Face, Audio, and Text processing choices |
| Analysis tile | Opens iMotions, native Py-Feat Face, Audio, or Text statistical report generation |
| Guided workflow switch | Shows or hides the multi-stage workflow planner |
| Procurement / Processing / Analysis checkboxes | Include or exclude each stage from the guided sequence |
| Face / Audio / Text checkboxes | Include or exclude each processing stream |
| Run in app / Import folder menu | Chooses whether that stream is executed or supplied from an existing folder |
| Browse | Selects the import folder for that stream |
| Start workflow | Begins at the first selected stage and carries paths forward |

Face, Audio, and Text can run in-app. Existing verified result folders can also
be imported where the selected workflow permits it.

## Settings

| Control | What it does |
| --- | --- |
| YouTube Data API key | Stores a new Google Cloud API key for public YouTube metadata |
| Remove stored YouTube API key | Deletes the saved YouTube key on the next save |
| How to get a YouTube API key | Opens Google's official setup guide |
| Hugging Face token | Stores a new Hugging Face User Access Token |
| Remove stored Hugging Face token | Deletes the saved token on the next save |
| How to create a Hugging Face access token | Opens the official token guide |
| YouTube download fallback | Optionally lets `yt-dlp` read cookies from Edge, Chrome, or Firefox |
| Enforce limits for all tool processes | Enables or disables the launcher resource policy |
| Maximum CPU load | Pauses above this load and limits automatic CPU affinity |
| Maximum CPU cores | Caps logical processors; `0` uses the CPU percentage automatically |
| Maximum GPU load | Pauses above this NVIDIA utilization when `nvidia-smi` is available |
| RAM limit type | Switches between whole-system percentage and process-tree gigabytes |
| Maximum system RAM | Pauses when overall used RAM reaches this percentage |
| Maximum tool process RAM | Pauses when the launched process tree reaches this resident-memory amount |
| Native library threads | Caps native math/ONNX thread pools per process |
| Monitor interval | Sets telemetry polling frequency |
| EULA file | Shows the local acceptance record used by every screen |
| Revoke access | Requires confirmation, sets acceptance to false, and closes the application |
| Save settings | Validates and stores changes locally |
| Close icon | Closes the dialog without saving unsaved changes |

## Procurement: Choose Input

| Control | What it does |
| --- | --- |
| Back shield | Returns to the three home tiles |
| Source field | Accepts a YouTube URL, folder path, DOCX path, or local video path |
| Search | Scans the entered source; if blank or spaces only, opens the source-choice dialog |
| Folder | Opens the modern recursive folder picker |
| DOCX or video | Opens the modern file picker for `.docx`, `.mp4`, `.mov`, `.mkv`, `.webm`, or `.avi` |
| Output directory | Shows where the Procurement run will be written |
| Change output folder | Opens the folder picker for a different output root |
| Input / Review / Run steps | Show progress through Procurement; unavailable future steps remain disabled |

## Procurement: Review And Mode

| Control | What it does |
| --- | --- |
| Search again | Returns to source selection and rescans a different input |
| Continue | Runs the selected mode, or opens the Focus video list |
| Clear / All | Unticks or reticks all speaker groups |
| Speaker checkbox/tab | Includes or excludes the entire speaker group and opens its video list |
| Sort menu | Orders the active speaker's videos by speaker order, upload date, or duration |
| Thumbnail | Opens the original YouTube page when a YouTube link exists |
| Video title | Opens the original YouTube page during Review |
| Standard sampling | Shows percentage and maximum segment length controls |
| Full video | Selects complete-video processing |
| Focus | Shows the inter-segment black/silent gap setting |
| Clean speaker segments | Shows clean compilation and percentage-sample settings |
| Run button | Remains disabled until a mode and at least one speaker are selected |

The video metadata row shows speaker, duration, upload date, and licence. Unknown
values are displayed as unknown rather than guessed.

## Clean Speaker Controls

| Control | What it does |
| --- | --- |
| Clean compilation | Keeps every accepted face-and-voice overlap |
| Percentage sample | Fills the target share from accepted clean overlaps |
| Minimum clean overlap | Rejects overlaps shorter than this duration |
| Black/silent gap | Inserts this gap between stitched clips |
| Target percentage | Appears only for Percentage sample |
| Max clip length | Appears only for Percentage sample |
| Only YouTube video IDs | Restricts a scanned DOCX/folder run to comma-separated IDs |
| Run one random scanned video | Performs a quick validation on one item |
| Random seed | Makes the random validation choice repeatable |
| Run one video per process | Releases model memory after each video and improves recovery |
| Skip completed outputs | Uses manifests to resume without repeating finished videos |
| Skip first videos | Starts after a known number of scanned items |
| Cooldown between videos | Waits between isolated video jobs |
| Reference voice audio | Supplies an optional known-speaker voice recording |
| Identity stills | Sets the number of diverse main-person reference images to retain |
| Scan FPS | Controls baseline face sampling density |
| Candidate validation FPS | Controls stricter checking inside proposed face intervals |
| Max YouTube download height | Caps online source resolution; `0` allows the downloader default |
| Face confidence | Sets the identity acceptance threshold |
| Speaker confidence | Sets the voice-cluster acceptance threshold |
| Concurrent videos | Runs this many videos simultaneously |
| Model device | Uses Auto, CPU, or requires CUDA |
| Parallel face/audio analysis | Runs both detector streams together at higher resource cost |
| Keep debug artifacts | Preserves intermediate frames, audio, and detector logs |
| Check model readiness | Reports required commands, packages, models, and token state before running |

For the reference 24 GiB system, keep **Concurrent videos** at 1 and
**Parallel face/audio analysis** off.

## Focus Editor

| Control | What it does |
| --- | --- |
| Video title in Focus list | Opens this video's segment editor instead of navigating to YouTube |
| Close icon | Closes the editor and keeps saved segment selections |
| Player controls | Play, pause, seek, change volume, and enter player full screen where supported |
| Timeline | Clicks seek the player; dragging an empty area creates a proposed range |
| Existing clip bar | Click to select; drag either edge to expand or contract it |
| Start / End fields | Accept seconds, `MM:SS`, or `HH:MM:SS` |
| Use current | Copies the player's current time into the adjacent field |
| Add segment | Validates and stores the entered interval |
| Delete selected | Removes the highlighted interval |
| Segment row | Selects the matching bar and loads its times into the fields |
| Selected clip / share | Reports duration and percentage for the selected interval |
| Create focused videos | Stitches all saved Focus intervals for selected videos |

Near-playhead selections snap to the current time. A selected segment is
highlighted both on the timeline and in the segment list.

## Processing Hub

| Control | What it does |
| --- | --- |
| Face tile | Opens native Py-Feat processing, offline readiness, and explicit model preparation |
| Audio tile | Opens the working Audio Processing screen |
| Text tile | Opens native Whisper/RockSteady processing and readiness |
| Import processed face/audio/text toggle | Marks that stream as supplied by an existing folder |
| Browse | Selects the corresponding imported output folder |
| Continue to analysis | Opens Analysis after required processing paths are present |

Imported streams and in-app streams can be mixed in one guided workflow.

## Native Face And Text Processing

Both screens accept a supported file/folder or an immutable Procurement catalog
run. Catalog mode displays ordered manifest rows and arbitrary metadata, but
filtering only changes visibility: **Select visible** and **Clear visible** are
the actions that change the authorized SourceID subset. The exact catalog
SHA-256 and selected SourceIDs are sent as repeated CLI bindings.

Native Face exposes sample FPS, detector confidence, batch size, device,
recursion, overwrite, and debug controls. **Check readiness** is offline;
**Prepare models** is the only Face child allowed to receive a Hugging Face
token. Launcher children inherit a minimal operational environment allowlist,
so unrelated parent-process secrets are not forwarded. Completed results can be opened or handed directly to the distinct
native Face Analysis provider.

Native Text exposes Whisper model/device/language, original or English output,
embedded/custom dictionaries, merge/override behavior, searchable categories,
all categories, thread count, forced RockSteady execution, graphs, and debug.
The dynamic category list is readiness-derived. Completed source-grain results
can be handed directly to Analysis. Their final pair root contains exact catalog
sidecar copies bound by file, catalog, and ordered source-context hashes; the
native importer reads that explicit run root rather than searching ancestors.

## Audio Processing

| Control | What it does |
| --- | --- |
| Back to processing | Returns to the Processing hub |
| Batch folder | Recursively processes MP4 files and preserves the input tree |
| Single video | Processes one MP4 |
| Select input folder | Opens the batch folder picker |
| Select single video | Opens the MP4 file picker |
| Audio source path | Accepts a pasted folder or MP4 path |
| Import existing audio outputs | Uses an existing audio output folder and does not run OpenSMILE |
| Audio output directory | Shows the destination root |
| Change output folder | Selects another destination |
| Run audio processing | Validates the request and starts the batch or single-video run |
| Emotion models | When off, still runs OpenSMILE but leaves model emotion columns blank |
| Advanced audio options | Expands settings intended for technical users |
| Window seconds | Length of each acoustic/model window; default 10 seconds |
| Stride seconds | Distance between window starts; default 5 seconds |
| OpenSMILE feature set | Chooses eGeMAPS, ComParE 2016, or the ComParE alias |
| Emotion model device | Auto, CPU, or required CUDA |
| Keep temporary audio | Preserves extracted WAV windows |
| Debug fallback model | Writes a separate fallback-model comparison |
| Stop on first batch error | Ends a batch at its first failed video |
| Stop | Terminates the active Audio Processing tree |
| Back to audio options | Returns to inputs after completion or failure |
| Open analysis | Carries the completed audio path into Analysis |

For standard research extraction, keep 10-second windows, 5-second stride,
eGeMAPS, Auto device, and temporary/debug outputs off.

## Analysis

Analysis can combine Video / iMotions, Py-Feat / Native Face, Audio, and Text
constructs in one run. The native Face provider remains separate from
iMotions/AFFDEX. Native Text prefers SourceID-grain results while legacy
speaker-level Text imports remain supported.

| Control | What it does |
| --- | --- |
| Video / iMotions | Enables analysis of iMotions emotions, action units, landmarks, movement, and geometry |
| Py-Feat / Native Face | Enables primary-face native emotion, valence, and arousal analysis from a verified Face run |
| Audio | Enables analysis of this tool's audio emotion and OpenSMILE outputs |
| Text | Prefers native `video_level_summary.csv` SourceID observations and retains legacy `speaker_level_summary.csv` compatibility |
| Run analysis | Processes that modality's fresh source before building the combined result |
| Use existing results | Reads an existing Analysis report tree without changing it |
| Source folder | Accepts the enabled modality's fresh input or existing report folder |
| Browse | Selects the folder for that modality |
| Customize output | Opens the nested metadata ordering, filtering, and grouping screen |
| Load source metadata | Finds the paired `source_manifest.json` and `source_metadata.csv` for the selected run |
| Procurement source manifest | Optionally selects the authoritative `source_manifest.json` when every chosen legacy result folder is sidecarless |
| Sort fields | Applies selected metadata fields in the displayed priority order |
| Automatic grouping | Groups remaining sources by any declared metadata field |
| Manual group | Adds whole speakers or individual sources to a named group |
| Visible metadata values | Leaves matching sources out of this Analysis run without changing source sidecars |
| Combined workbook | Builds descriptive group sheets and their adjacent probability mirrors |
| Default reference value | Sets the comparison value used unless a sheet or metric override is supplied |
| Reference overrides | Accepts advanced, case-sensitive per-sheet or per-metric reference values as JSON |
| Generate graphs | Writes SVG histogram graphs for modalities using **Run analysis** |
| Log-scale outputs | Adds `log10(count + 1)` histograms for modalities using **Run analysis** |
| Video / iMotions advanced options | Expands iMotions-specific column controls |
| Include landmarks | Includes raw landmark columns |
| Include timing columns | Includes timing and counter fields |
| Exclude geometry | Omits geometry columns from histogram output |
| Report output directory | Sets the destination for new Analysis and combined outputs |
| Run Analysis | Validates sources and the saved output customization, then runs one coordinated workflow |
| Stop | Terminates active Analysis work |
| Back to analysis options | Returns to the Analysis configuration screen |

### Customize The Output

1. Enable Video / iMotions, Py-Feat / Native Face, Audio, Text, or any useful combination.
2. Choose **Run analysis** or **Use existing results** separately for Video and
   Audio. Text uses **Use existing results** only. Select each source folder.
3. Select **Customize output**. The application loads the immutable source
   sidecars from the selected procurement run. Ordinary legacy Text or
   iMotions result folders do not need duplicate sidecars; their exact speaker,
   title, SourceID, or output-folder identities are matched to the profile. If
   every selected result folder is sidecarless, choose the procurement run's
   `source_manifest.json` in **Procurement source manifest**, then select
   **Load source metadata**.
4. Enable metadata sort fields and use the arrow buttons to set their priority.
5. Optionally hide metadata values or group remaining sources by one metadata
   field.
6. Optionally create manual groups containing a whole speaker, an individual
   source, or both. A source may resolve into only one manual group. When Text
   is enabled, keep every visible source for one speaker in the same group
   only for a legacy speaker-grain Text import. Native SourceID-grain Text may
   be split by SourceID.
7. Review the order/group preview, select **Use this customization**, choose
   the output directory, and select **Run Analysis**.

The application writes these choices to `analysis_profile.json` in the
Analysis output. The profile records the source-manifest path and SHA-256
digest, so the same procurement run can be postprocessed repeatedly with
different groupings while `source_manifest.json` and `source_metadata.csv`
remain unchanged. Unassigned visible sources flow into automatic metadata
groups or one **All other sources** group. The Overall value is the mean of the
available participant means. Metadata values are matched exactly after
surrounding whitespace is removed, so differently capitalized categories remain
distinct. Imported Text construct values are multiplied by `100` only when
written to the combined workbook and appear in the comparison sheet. Raw Text
sources remain unchanged. Text is not used for Video or Audio probability
inference because the modalities are not calibrated equivalents.

Reference override keys must match generated names exactly. A sheet override
uses the quantitative worksheet title, for example
`{"Audio - Group 1": 0}`. A metric override uses
`<worksheet title>|<group id>|<metric>`, for example
`{"Audio - Group 1|group-1|Arousal": 0}`. Names are case-sensitive. Excel
worksheet titles longer than 31 characters are shortened deterministically;
an invalid or stale key stops the run and the error lists valid generated
examples rather than silently applying the default.

### Fresh And Existing Sources

For **Run analysis**, choose the source that has not yet been statistically
analysed:

- Video / iMotions: a folder containing iMotions CSV exports.
- Audio: a folder containing processed `audio_analysis.csv` files and their
  OpenSMILE-derived values.

New modality reports are written below the selected output root in `video/`
and `audio/`. The coordinator uses the reports returned by those fresh runs.

For **Use existing results**, choose an Analysis output tree containing one or
more reports in this established shape:

```text
<source>/<domain>/<speaker>/combined/other_findings/descriptive_statistics.csv
```

Imported folders are read-only. The output directory must be separate from an
imported report folder. A mixed run is valid, for example fresh Audio with
imported Video / iMotions.

### Combined Outputs

The selected output directory contains:

```text
combined_analysis.xlsx
combined_analysis_manifest.json
analysis_profile.json
video/                         # present when Video ran fresh
audio/                         # present when Audio ran fresh
video_column_manifest.csv      # present when Video was selected
```

`combined_analysis_manifest.json` records status, source methods and paths,
the Analysis profile, software version, best-effort Git revision, accepted and
rejected report decisions, modality output roots, resolved reference sources,
workbook path, and warnings. For requested modality `video`, it also records
resolved provider/evidence/warnings, provider version/availability, original
fields, channel availability, and the serialized column-manifest rows. A
failed manifest also records the failed stage
and a sanitized one-line error. Keep it with the workbook when archiving or
sharing a run.

Before a new run uses the same output directory, any previous fixed-name
workbook, manifest, Analysis profile, and Video column manifest are moved into a self-contained run
directory below `combined_analysis_history/`. The archived manifest is rewritten
to identify its matching archived workbook and records that workbook's SHA-256
hash. This prevents a failed rerun from leaving an older
`combined_analysis.xlsx` beside
the new failed manifest or a historical manifest pointing at a later run.
Failed-run state is quarantined in the same contained history directory so the
researcher can correct the input and retry without manual file cleanup.
Imported source trees, manifests, and sidecars are never moved or changed and
remain byte-identical.

#### Combined workbook measure contract

The workbook keeps four semantic sections separate and lists the same contract
in its non-quantitative **Measure Guide** sheet:

- **Emotions:** Audio includes Anger, Contempt, Disgust, Fear, Joy, Sadness,
  Surprise, Neutral, and Other on `0..100` (source probabilities `0..1`
  multiplied by 100; Joy imports the source label `Happiness`). Video includes
  Anger, Contempt, Disgust, Fear, Joy, Sadness, Surprise, Neutral, and
  Confusion on `0..100`. Native Py-Feat Face maps Happy to Joy and Sad to
  Sadness, keeps the other five supported classes, and maps probabilities
  `0..1` to `0..100`; Contempt and Confusion remain blank.
- **Sentiment:** Video Sentimentality is `0..100`. Text Positive Sentiment and
  Negative Sentiment are imported on source scale `0..1` and multiplied by
  `100` for combined-workbook scale `0..100`; imported legacy headers `Positive valence`
  and `Negative valence` are accepted as aliases, with canonical sentiment
  headers preferred when both are present.
- **Valence:** Audio Valence maps source `0..1` to output `-100..100` with
  `(raw * 200) - 100`. Video Valence and Adaptive Valence remain
  `-100..100`. Native Face valence and arousal map source `-1..1` to
  `-100..100`. Text Valence is `(Positive Sentiment - Negative Sentiment) /
  (Positive Sentiment + Negative Sentiment)` on source scale `-1..1`, then is
  multiplied by `100` for combined-workbook scale `-100..100`; it is blank when
  the denominator is zero. Joy and Valence are never substituted for Positive
  or Negative Sentiment.
- **Dimensions:** Audio Arousal and Dominance map source probabilities `0..1`
  to `0..100`. iMotions Video Engagement and Adaptive Engagement are `0..100`.
  Native Face Arousal maps source `-1..1` to `-100..100`, remains named
  `Arousal`, and is never substituted as Engagement. Text Arousal / Activation,
  Dominance / Power, and Affiliation / Social orientation are imported on
  source scale `-1..1` and multiplied by `100` in the combined workbook;
  signed values retain their sign.

The numeric ranges overlap after the Text `x100` conversion, but modality
constructs are not calibrated equivalents. The
Measure Guide records Section, Modality, Display measure, Imported source
label, Workbook sheet, Output range, and Transformation/meaning for every
displayed measure. For the selected speakers, Audio rows and guide entries are
created only for measures with at least one numeric observation. Within each
speaker panel, unavailable optional Audio emotions are omitted; a numeric zero
is retained as a real score. New full reports retain all nine audio emotions.
Action units, muscles, and tones remain available in their detailed reports but
are outside this combined emotional workbook.

The **Construct Comparison** sheet uses seven ordered heuristic families:
Positive Sentiment, Negative Sentiment, Neutral / Other, Arousal / Activation,
Valence, Dominance / Power, and Affiliation / Social orientation. The display
taxonomy assigns all 15 canonical Video measures, all 12 Audio measures, and
all six Text measures exactly once while excluding Action Units. Each speaker
has multiline Face, Audio, and Text boxes followed by four columns: blank,
`Min`, `Max`, blank. `Min` selects the lowest measure inside each available
modality box; `Max` selects the highest. Each column then ranks the selected
modality values high-to-low with Face, Audio, Text tie order. Missing and
no-direct boxes are blank and excluded. These are descriptive raw-score extrema
rather than calibrated effect rankings.

In `combined_analysis.xlsx`, every quantitative descriptive sheet is followed
immediately by one probability mirror. Individual speaker cells in the mirror
remain formula links to their descriptive values. Only the group Overall cells
are replaced by probabilities. Definition and empty placeholder sheets are not
duplicated. **Inference Settings** records resolved references, and
**Inference Details** exposes the values and formulas supporting each result.
The settings sheet records the original submitted key, whether it matched the
default, a sheet, or a metric, the matched source, and the resolved value.

### Interpret The Probability Sheets

The reported quantity is:

```text
P(population mean > reference | observed speaker means)
```

The independent observations are the valid **speaker means in that group**.
The model treats those speaker means as exchangeable, independent and
identically distributed Normal observations. The intended population is the
conceptual speaker population represented by the user-defined group, not the
frames, videos, or CSV rows used to estimate each speaker mean. Generalization
therefore depends on whether the named speakers are a defensible sample of that
population. Individual speaker values remain descriptive; inference is attached
only to the group's Overall result.

- **Posterior probability** is the directional Student-t model estimate that
  the population mean is above the chosen reference, given the observed
  speaker means and the model assumptions.
- **p-value** is the two-sided one-sample test result against the reference. It
  is not the probability that the null hypothesis is true.
- **q-value** is the Benjamini-Hochberg false-discovery-rate adjustment of the
  p-values within that quantitative worksheet. It helps interpret a family of
  metrics tested together.

For two or more speaker means with positive sample variance, the workbook uses
the Student-t result under an unknown-variance Normal model and the
reference/independence prior `pi(mu, sigma^2) proportional to 1/sigma^2`.
When `n < 2`, the descriptive mean remains available but inferential values are
blank. When two or more speaker means are identical, the sample standard
deviation remains available as zero, but the posterior under that improper
prior and the one-sample t statistic are undefined. The standard error,
interval, t statistic, p-value, q-value, effect size, and posterior probability
are therefore left blank rather than reported as limiting conventions.

Missing, formula-empty, and nonnumeric speaker cells are excluded consistently.
The live Excel `COUNT`, `AVERAGE`, and ordinary direct-reference `STDEV.S`
formulas use the source cells themselves, so blanks are not coerced to zero and
the workbook does not require dynamic-array formula support. Python and
recalculated Excel therefore use the same observations.

The workbook stores live formulas and requests automatic full recalculation.
Open it in desktop Excel once before reading or exporting inferential values;
some preview tools display formulas without calculating their latest results.
