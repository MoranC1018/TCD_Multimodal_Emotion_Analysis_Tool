# Procurement

The Procurement stage accepts one source through the desktop launcher or the
command line. The desktop application is the recommended path for non-technical
users because it provides metadata review, mode controls, progress, and a guided
transition into Processing.

## Desktop Application

Launch from the repository root:

```text
Launch_Video_Processing_Stack.bat
```

Or run:

```powershell
python -m application.launcher
```

The launcher uses a native desktop shell. On first launch it presents the EULA
in a native dialog, then stores acceptance in ignored `_local/eula.txt`.
Acceptance is rechecked by each application screen.

## Universal Source Field

The Procurement input screen has one source field and one **Search** command.
The field accepts:

- a YouTube watch, share, Shorts, or embed URL;
- a folder tree containing MP4, MOV, MKV, WebM, or AVI files;
- a DOCX file containing YouTube links in table rows;
- one MP4, MOV, MKV, WebM, or AVI file.

Wrapping quotes copied with a Windows path are removed safely. Folder trees are
scanned recursively, and speaker/subfolder grouping is retained. After scanning,
the review screen shows title, duration, upload date, licence, and thumbnail
when that metadata is available.

YouTube metadata resolution is layered:

1. YouTube Data API when a local API key is configured.
2. Public YouTube oEmbed title/thumbnail lookup.
3. `yt-dlp` metadata for a directly pasted URL when duration or title remains
   missing.

The Settings screen reports whether the YouTube API key and Hugging Face token
are configured without exposing either secret to the browser.

## Procurement Modes

### Standard Sample

Selects a configurable fraction of the source, default 10%, in clips no longer
than the configurable maximum, default 30 seconds. Local sampling uses
non-overlapping intervals and records a manifest.

### Full Video

Copies a local video or downloads the complete online source after an explicit
copyright warning. The user is responsible for permissions, licence terms, and
research-use compliance.

### Focus

Focus lets the researcher select exact intervals in the embedded player.

- There is no maximum segment length.
- Start/end values accept seconds, `MM:SS`, and `HH:MM:SS`.
- The timeline follows the active player time.
- Clicking seeks; dragging selects a range.
- The only mode-specific output option is black/silent gap duration.
- A gap value of `0` concatenates the selected clips directly.

MP4 and WebM provide the most reliable local preview. MOV, MKV, and AVI remain
available to FFmpeg-backed Standard and Full processing even when the embedded
decoder cannot preview them.

### Clean Speaker Segments (Beta)

This experimental mode intersects strict target-face visibility with
dominant-speaker activity. It can produce a full clean compilation or a
percentage sample. Model setup, confidence gates, outputs, performance, and
licence notices are documented in:

- `procurement/procurement_beta/SETUP.md`
- `procurement/procurement_beta/THIRD_PARTY_NOTICES.md`

The beta fails closed when model-backed identity or voice evidence is
unavailable. A successful process with `no_clean_segments` therefore means the
confidence rules rejected the media; it is not equivalent to a validated clean
video.

## Command-Line DOCX Pipeline

Run:

```powershell
python -m procurement.run_pipeline INPUT.docx
```

Useful options:

```powershell
python -m procurement.run_pipeline INPUT.docx --limit 3
python -m procurement.run_pipeline INPUT.docx --force
python -m procurement.run_pipeline INPUT.docx --no-stitch
python -m procurement.run_pipeline INPUT.docx --dry-run
```

The pipeline audits YouTube licences and writes outputs under
`procurement/output/`. Creative Commons rows use full download. Standard
YouTube Licence rows use the configured sampling workflow. Unknown licences are
treated conservatively as Standard and recorded in the manifest.

Use the same Python interpreter that launches the desktop application. On
Windows, an explicit interpreter path may be needed:

```powershell
& "C:\Path\To\Python\python.exe" -m procurement.run_pipeline source_catalog.docx
```

## Local Settings And Outputs

EULA state, nonsecret settings, generated media, logs, edited DOCX files, and
output folders are gitignored. Launcher credentials use Windows user-protected
storage outside the repository. Command-line licence checks accept an explicit
`YOUTUBE_API_KEY` process environment variable; `config.env` is for nonsecret
workflow settings only.

Settings provides CPU, NVIDIA GPU, and RAM controls for launcher-owned process
trees. CPU is controlled through processor affinity. RAM can use overall
system-used percentage or pipeline process-tree gigabytes. GPU telemetry
requires `nvidia-smi`; systems without compatible telemetry continue without a
GPU cap and show that limitation in Settings.
