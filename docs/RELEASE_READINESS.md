# Release Readiness Report

Date: 2026-07-23

## Outcome

The implemented Procurement, audio Processing, import, and Analysis workflows
are ready for local Windows research use. The release is intentionally bounded:
Face and Text are import-only, and Clean speaker segments remains labelled
Beta. The launcher is a local desktop application backed by a loopback HTTP
service; media paths are passed to local tools rather than uploaded into the
interface.

This report records tested behaviour and practical limits. It is not a claim
that machine-learning estimates are validated measures of human emotion.
Interpretation and action remain the researcher's responsibility; the software
is not a diagnostic system.

## Release Changes

- Replaced the three source-specific browse actions with one universal source
  field and one Search command.
- Added direct YouTube URL support for watch, share, Shorts, and embed links.
- Added layered title/duration/date/licence metadata lookup through the YouTube
  Data API, public oEmbed, and direct `yt-dlp` metadata fallback.
- Replaced the former Manual selection name with Focus throughout the visible
  product.
- Removed Focus maximum clip length. Focus now has one mode-specific output
  setting: black/silent gap duration, where zero means no gap.
- Added timeline/player synchronization, click-to-seek, drag-to-select, live
  playhead display, and seconds/`MM:SS`/`HH:MM:SS` editing.
- Added masked `Configured`/`Not configured` states for YouTube and Hugging Face
  credentials without returning raw secrets to browser state.
- Added CPU, NVIDIA GPU, and RAM controls with process-tree pause/resume,
  hysteresis, and sustained-RAM-pressure termination.
- Restored the official Trinity College Dublin horizontal mark on the home
  screen after the project confirmed that this official tool is authorised to
  use it. The original shield assets are used for the browser and native app
  icons; none of the supplied identity artwork is redrawn or modified.
- Renamed the analysis output from
  `descriptor_statistics.csv` to `descriptive_statistics.csv`; stale legacy
  files are removed on rerun.
- Added a repeatable non-media launcher stress tool at
  `tools/benchmark_launcher_limits.py`.

## Bugs Found And Fixed

- A single local video in Focus failed because the source file was treated as a
  directory root, yielding `WindowsPath('.') has an empty name`. The output
  stem now handles single-file and folder inputs separately, with a regression
  test.
- Focus timeline clicks could lose their seek while the YouTube iframe API was
  still becoming ready. Pending seeks are retained, reflected immediately in
  the UI, and applied when the player is ready.
- Selected-range overlays intercepted timeline pointer events. They no longer
  block seeking or range creation.
- A blank secret field could overwrite an existing credential. Blank values now
  preserve the stored secret; clearing requires the explicit clear control.
- Launcher state exposed more settings than the browser needed. State snapshots
  now use a public settings projection containing only masks, booleans,
  capabilities, and non-secret resource settings.
- Direct beta URL input could retain a synthetic `YouTube video <id>` title.
  It now uses the same metadata resolution path as the main Procurement scan.
- Stopping or revoking access could leave descendants running. Process-tree
  termination now includes child processes.
- Focus local FFmpeg extraction emitted excessive banner/progress noise. It now
  keeps researcher-facing progress while suppressing routine FFmpeg banners.
- The Windows launcher could select Python 3.11 despite the documented 3.12+
  requirement and did not prefer a project environment. It now validates
  Python 3.12+ and selects the ignored repository `.venv` first.

## Supported Inputs

| Stage | Input | Behaviour |
| --- | --- | --- |
| Procurement | YouTube URL | Direct scan; canonical URL and available metadata retained. |
| Procurement | MP4, MOV, MKV, WebM, AVI folder tree | Recursive scan; subfolders retained for speaker grouping. |
| Procurement | DOCX with YouTube links in tables | Table rows become review items; speaker and existing metadata retained. |
| Procurement | One MP4, MOV, MKV, WebM, or AVI | Standard, Full, Focus, and compatible beta paths. |
| Focus preview | YouTube, MP4, WebM | Most reliable embedded playback. Browser codec support controls local preview. |
| Audio Processing | MP4 file or recursive MP4 folder | Existing audio outputs can instead be imported. |
| Face/Text Processing | Existing processed folder | Import-only in this release. |
| Analysis | iMotions exports or audio processing outputs | Produces per-video and combined speaker reports. |

Unsupported local files, missing paths, empty folders, and DOCX files without
YouTube rows are rejected with actionable errors.

## Real-Media Acceptance Checks

All media below was synthetic and written outside the repository.

| Check | Result |
| --- | --- |
| Standard sample | 60 s, 720p H.264/AAC source; 10% selected; completed in 1.33 s and produced a 5.94 s stitched file. |
| Focus with gap | Two 2.0 s intervals plus one 0.5 s black/silent gap; completed in 1.23 s; FFprobe reported 4.521 s. |
| Direct YouTube metadata | A live direct URL returned its real title, 4,997 s duration, upload date, thumbnail, and Standard YouTube Licence metadata. |
| Focus long interval | A 3,600 s selection was accepted without clipping it to the Standard-mode 30 s setting. |
| Focus timecode | `1:02.5` parsed as 62.5 s; `1:10:00` parsed as 4,200 s; invalid `1:72` was rejected. |

The small duration difference in stitched media is normal container/audio frame
rounding. It is below one encoded frame/audio-packet boundary and is not a
logical extra segment.

## Bounded Stress Results

Measurements were taken on Windows 11, Python 3.12.1, 24 logical processors,
and 23.9 GiB system RAM. Times are local references, not guarantees.

| Operation | Scale | Time | Peak traced Python memory |
| --- | ---: | ---: | ---: |
| Folder scan with sidecar metadata | 100 videos | 0.0819 s | 0.115 MB |
| Folder scan with sidecar metadata | 1,000 videos | 0.7389 s | 1.006 MB |
| Folder scan with sidecar metadata | 5,000 videos | 3.6698 s | 4.998 MB |
| DOCX table scan | 100 rows | 0.4909 s | 2.225 MB |
| DOCX table scan | 1,000 rows | 4.7481 s | 2.623 MB |
| DOCX table scan | 5,000 rows | 24.0104 s | 7.655 MB |

The memory figures cover Python allocations observed by `tracemalloc`; they do
not include FFmpeg, browser, OpenCV, PyTorch, CUDA, or model-native allocations.
DOCX parsing is the slowest metadata-only path at large row counts because
python-docx materializes table proxies and hyperlinks. Review-screen rendering
can become less ergonomic before the scanner reaches a structural limit.

The launcher request guard is 2,097,152 bytes. A representative Focus payload
fit 6,177 segment objects under that limit; the next payload measured
2,097,346 bytes. This limit applies to JSON instructions, not media bytes.

## Maximum Video Size

There is no application-level maximum local video file size. Videos remain on
disk and are addressed by path. The deciding factors are:

1. **Free output storage.** Full mode requires approximately another source-file
   size. Encoded samples and debug artifacts add overhead.
2. **Filesystem limits.** NTFS supports files far larger than normal research
   media, but removable FAT32 media has a 4 GiB single-file limit.
3. **Codec/container support.** FFmpeg controls processing support. The embedded
   player has a narrower codec set, which mainly affects Focus preview.
4. **Duration, resolution, and codec complexity.** These determine decode and
   encode time more directly than compressed file size.
5. **Native model memory.** Clean speaker beta and audio emotion models can use
   substantially more RAM/VRAM than Procurement scanning.
6. **External services.** Network speed, YouTube availability, API quota,
   authentication, and model-host access can dominate online runs.

The largest structural list tested was 5,000 items. Larger lists are not
explicitly blocked, but should be split into meaningful research batches for
reviewability, API recovery, and provenance.

## Resource-Control Semantics

- **CPU percent** is translated to a stable logical-processor affinity count.
  It limits how many logical processors descendants can use; it is not a
  real-time power or utilization governor.
- **GPU percent** monitors peak system-wide NVIDIA utilization via
  `nvidia-smi`. It pauses the launcher process tree above the configured limit.
  It cannot attribute utilization to one process and is unavailable on
  unsupported GPUs.
- **RAM percent** monitors overall system-used memory. It protects headroom
  against the pipeline plus other applications.
- **RAM gigabytes** monitors resident memory across the pipeline process tree.
  This is more attributable to the run, but native driver allocations may not
  be fully represented.

Pause/resume uses hysteresis so a process does not oscillate at one threshold.
Sustained RAM pressure terminates descendants after 30 seconds. The controls
reduce crash risk but cannot prevent hardware faults, driver resets, kernel
failures, or memory allocated outside observable process accounting.

## Verification Commands

The post-commit release sweep completed 275 tests plus 25 parameterized
subtests in 11.99 seconds. Run the same root-level collection with:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check application/static/app.js
python -m compileall -q application procurement processing/audio_analysis/audio_pipeline processing/face_analysis processing/text_analysis analysis tools
python processing/audio_analysis/run_audio_analysis.py doctor
python tools/benchmark_launcher_limits.py --scales 100,1000,5000
```

`pytest.ini` scopes collection to the desktop application and three source stages, excludes ignored
local/recovery/vendor folders, and exposes the audio package to root-level
tests. This avoids environment-specific collection failures.

Rendered desktop and narrow-window checks cover Home, Procurement source,
review, Focus, and Settings. Assertions include no horizontal overflow, one
source action, real YouTube metadata, masked credentials, a synchronized Focus
playhead, and long-segment acceptance.

## Release Boundaries

- Face and Text do not execute in-app yet; they accept imported processed
  folders.
- Clean speaker segments is experimental and depends on optional models,
  confidence gates, and model terms.
- Model estimates are not ground truth. Validation against a labelled,
  speaker-independent sample is required before inferential claims.
- The bundled OpenSMILE 3.0.0 distribution remains under the audEERING
  Research License, is excluded from the project MIT License, and carries a
  non-commercial boundary. Its complete local licence tree must be retained.
- A missing YouTube API key reduces metadata completeness but does not prevent
  public fallback lookup or local inputs.
- YouTube download/reuse remains subject to copyright, platform terms, and the
  researcher's legal and ethical approvals.
- The launcher is intended for a trusted local machine. It binds to loopback and
  should not be exposed as a network service.

## Affiliation And Branding Boundary

The project affiliation is the School of Computer Science, Trinity College
Dublin, the University of Dublin. Project authority has confirmed use of the
supplied Trinity identity assets for this official tool. Institutional names,
logos, and marks are not licensed by the root MIT License, so downstream forks
must obtain their own permission before reusing them. Their inclusion does not
imply institutional endorsement of research findings produced with the tool.
