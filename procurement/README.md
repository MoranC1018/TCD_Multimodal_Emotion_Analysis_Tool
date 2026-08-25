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
- a CSV or DOCX catalog with a required `Link` column;
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

## Reusable Source Catalogs

CSV and DOCX catalogs share one row model. Header matching Unicode-normalizes,
trims, case-folds, and removes spaces, underscores, and hyphens. `Link` is the
only required header; `Speaker` is optional. Normalized variants of `Upload
Date`, `Engagement`, `Date Accessed`, and `Length` are ignored, while every
other nonblank label/value is researcher metadata. Values keep their original
Unicode content apart from outer whitespace trimming.

In a DOCX, tables without a normalized `Link` header are treated as unrelated
notes or appendices and skipped. Rows from all Link-bearing tables retain their
document order; a document with no Link-bearing table is rejected.

Relative local paths resolve from the catalog's directory. Absolute local
files outside that directory require the explicit CLI option
`--allow-external-local-paths`. UNC/network shares, device namespaces, and
symbolic-link or junction paths are rejected before access. Local and YouTube
rows retain their mixed order, and repeated links remain separate stable
SourceIDs. The UI exposes arbitrary metadata filters and sorting, but these are
visibility-only. Selection changes only through explicit source/speaker
checkboxes or **Select visible**/**Clear visible** controls.
Audio Processing reads the metadata fields from the sealed manifest in the
chosen batch folder for a second visibility-only filter/sort pass. It submits
only explicitly selected SourceIDs and the matching catalog digest; changing to
an unrelated or legacy folder clears the catalog controls.

Each run writes these immutable files before processing its selected rows:

```text
<run-root>/
  source_manifest.json
  source_metadata.csv
```

The JSON preserves exact user metadata and records the catalog SHA-256,
selection, mode/options, the SHA-256 of the exact temporary local-media snapshot
processed (or the YouTube ID/URL), API-reported YouTube language, and output
mapping. Clean-speaker processing verifies those sealed snapshot bytes
immediately before use, so a later change to the original local file cannot
change the run. `source_metadata.csv` neutralizes
spreadsheet formulas and uses a collision-free mapping for arbitrary headers;
the JSON records that export mapping. Researcher `Language` remains separate
from `YouTubeLanguage`, whose API precedence is `defaultAudioLanguage`, then
`defaultLanguage`, then blank.

Only `Speaker` controls speaker folders. Blank speakers are pooled directly at
the run root; metadata never creates folders. Each source output also receives
`source_context.json`, which carries SourceID and metadata into permitted audio
processing adapters. Local contexts also carry the sealed media identity; audio
processing rejects missing, orphaned, duplicate, or mismatched contexts before
model loading. A successful catalog clean-speaker run keeps its reusable private
cache and atomically publishes `stitched_imotions.mp4` beside that source
context, where audio discovery can bind it to the same manifest row.

The reusable coordinator CLI is:

```powershell
python -m procurement.catalog_runner sources.csv --run-root output\run `
  --catalog-sha256 <sha256> --source-id source-0001
```

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

## Legacy Command-Line DOCX Pipeline

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
