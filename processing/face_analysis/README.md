# Face Processing

This package runs native facial-behaviour analysis on media delivered by
Procurement. A legacy file/folder may run without catalog evidence. When any
catalog evidence is present, the exact top `source_manifest.json` and
`source_metadata.csv`, its SHA-256, the selected SourceIDs, and every mapped
`source_context.json` are mandatory and are validated before model work.
Timestamps always refer to the exact input video passed to this module.

## Why this output design

Three common designs were considered:

1. CSV only: easy to open, but Py-Feat v2 can emit more than 2,000 columns and
   CSV becomes very large and loses type information.
2. iMotions-shaped CSV: superficially compatible, but incorrectly implies that
   Py-Feat probabilities have AFFDEX semantics.
3. Full Parquet + core CSV + JSON manifests: lossless, compact, readable, and
   explicitly model-native.

The third design is implemented.

## Install

Use the project's single environment:

The pinned stack requires Python 3.11 or newer. Python 3.12 is tested and
recommended, while other compatible versions are accepted; the command below
selects the recommended version explicitly.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

On Windows, run `scripts\setup.ps1` for the automatic installation. It creates
the one environment, installs the matched Torch family, all project packages,
and TorchCodec's shared FFmpeg runtime. These are runtime libraries, not a
second Python environment.

Detectorv2 uses three checkpoints: `retinaface_r34`, `arcface_r50`, and
`face_multitask_v2`. Their model cards may impose research/non-commercial
terms; check each upstream licence before use. The supported Windows setup
explicitly prepares these weights; a manual installation should do the same:

```powershell
.venv\Scripts\python -m processing.face_analysis --prepare-models
```

`--prepare-models` is intentionally network-enabled. It downloads each
checkpoint from the immutable revision approved by this release, validates the
exact filename, size, and SHA-256 before model construction, and then constructs
Detectorv2 only from those validated local paths. Mutable `main` revisions and
arbitrary local override bytes are not accepted as ready.

## Run

Check the environment first:

```powershell
.venv\Scripts\python -m processing.face_analysis --check
```

`--check` never downloads a model. It verifies all three local checkpoint
files, constructs a real `Detectorv2` in Hugging Face offline mode, and reports
not-ready with the missing component names when the cache is incomplete. Run
`--prepare-models` once while online, then use `--check` at any time to prove
the installed model remains locally loadable without a surprise download.

```powershell
.venv\Scripts\python -m processing.face_analysis path\to\stitched_imotions.mp4
```

Batch directories are supported:

```powershell
.venv\Scripts\python -m processing.face_analysis Videos --sample-fps 5 --device auto
```

The desktop Processing page exposes the same input, output, sampling, threshold,
batch, device, recursion, overwrite, debug, readiness, and model-preparation
controls. It accepts one supported video, a directory, or an authorized catalog
subset. A completed run is handed to the distinct **Py-Feat / Native Face**
Analysis provider; it is never relabelled as iMotions or AFFDEX.

## Output

```text
processing/face_analysis/output/
  source_manifest.json    # catalog mode: exact byte copy of the sealed top JSON
  source_metadata.csv     # catalog mode: exact byte copy of the sealed top CSV
  run_manifest.json
  run_index.csv          # one readable row per input video
  <input-relative-folders>/
   <video-name>__<sha-prefix>/
    face_features.parquet  # every original Py-Feat column, one row per face
    face_core.csv          # readable core fields plus explicit no-face rows
    video_manifest.json    # input hash, model/config, quality and provenance
```

The run manifest records `catalog_sha256` and the ordered
`processed_source_ids` subset separately; the copied source manifest is never
rewritten to look like a smaller catalog. In catalog mode only canonical final
media is selected. Caches, raw clips, focus/segment intermediates, and other
processing artifacts are excluded. Output folders come from each row's
`output_mapping.video_directory`; only `Speaker` may add grouping folders.
Country, Language, Gender, and all other catalog fields stay metadata. Repeated
identical links remain separate SourceIDs.

For a single-file input, `<video-name>__<sha-prefix>/` stays directly below the
output root. For a directory input, country/speaker folders are mirrored so a
result can be located without searching by hash. `run_index.csv` provides the
input-to-output mapping, status, face coverage and any per-video error;
`run_manifest.json` retains the complete machine-readable provenance.

`face_core.csv` uses the input video's frame number and time. A sampled frame
without a detected face has `face_detected=false` and blank emotion/AU fields;
it is never represented as zero emotion. Every detected face is retained.
`is_primary_face` marks the highest-confidence face for convenience.

### Reading `face_core.csv`

| Field | Meaning |
| --- | --- |
| `media_id` | Stable video stem plus the first 12 characters of its content SHA-256. |
| `frame_index` | Zero-based frame number in the exact input video. |
| `timestamp_seconds` | `frame_index / source FPS`; time is measured against the input video, not wall-clock time. |
| `face_detected` | `true` for a real accepted detection; `false` for an explicit sampled no-face frame. |
| `face_count` | Number of accepted faces in that sampled frame. |
| `face_index` | Zero-based face number within one frame. It is not a cross-frame person identifier. |
| `is_primary_face` | Highest-`FaceScore` face in that frame. This is a convenience flag, not proof of speaker identity. |
| `FaceRectX/Y/Width/Height` | Py-Feat face box in source-frame pixel coordinates. |
| `FaceScore` | Detector confidence in `[0, 1]`; rows below `--face-threshold` are not detections. |
| `AUxx` | Py-Feat action-unit model scores in `[0, 1]`; these are model estimates, not human-coded FACS intensities. |
| `Neutral` … `Anger` | Seven model-native emotion probabilities in `[0, 1]`. They do not have AFFDEX/iMotions semantics. |
| `valence`, `arousal` | Continuous Py-Feat estimates in `[-1, 1]`. |
| `gaze_pitch`, `gaze_yaw` | Gaze angles in radians using Py-Feat's canonical sign convention. |
| `Pitch`, `Roll`, `Yaw` | Head-pose rotations in radians using Py-Feat's canonical convention. |
| `Identity` | Backend-provided identity label. Validate it before treating it as a persistent real-person identity. |

The integer frame step is `round(source_fps / requested_sample_fps)`, with a
minimum of one. Consequently `--sample-fps` is a requested rate. The exact
`frame_step`, `effective_sample_fps`, and number of expected frames are stored
in every `video_manifest.json`.

### Manifests, recovery, and failures

Each per-video manifest records:

- source path, size, media SHA-256, dimensions, duration and FPS;
- SourceID, raw/display speaker, catalog digest, arbitrary user/system
  metadata, output mapping, exact source-context object and its SHA-256;
- requested configuration, resolved CPU/CUDA/MPS device, Py-Feat model
  components, and relevant package versions;
- for each actual Detectorv2 checkpoint (`retinaface_r34`, `arcface_r50`, and
  `face_multitask_v2`): repository, selected filename, requested revision,
  resolved cache commit, local path, byte size, and content SHA-256. Custom
  `FEAT_ARCFACE_R50_PATH` and `FEAT_MULTITASK_WEIGHTS` files receive the same
  content fingerprint;
- the exact sampling contract and quality/coverage counts;
- for both CSV and Parquet: byte size, SHA-256, rows, columns and ordered-column
  schema fingerprint.

An existing result is skipped only when its manifest version, SourceID/context/
catalog binding, input hash,
three-weight model signature, analysis fingerprint, artifact hashes, schemas,
row counts and column counts all verify. A legacy manifest that identifies
only one checkpoint is a cache miss. Empty, truncated, unreadable, modified or
legacy-schema artifacts are recomputed automatically. `--overwrite`
deliberately recomputes even a verified result.

After the backend returns, Face re-probes the media, recomputes its content
digest, and compares its exact filesystem identity before transforming or
publishing results. A file changed or replaced during analysis fails at the
`integrity` stage and cannot produce a completed per-video manifest.

`run_index.csv` is the first file to open after a batch. It contains one row per
discovered video, including source/output mapping, coverage, and structured
`error_stage`, `error_type`, and `error_message` columns. The CLI also prints
each failed video and reason to stderr. `run_manifest.json` is published last
as the run-level completion marker and contains a unique `run_id`; orchestrators
may supply their own with `--run-id`.

The possible per-video error stages are `probe`, `provenance`, `resume`,
`analyse`, `integrity`, `transform`, and `write`, making the failing responsibility directly
searchable in the source package.

## Analysis contract and limits

Analysis reads verified `face_core.csv` plus its manifest without requiring
PyArrow. It uses only rows with `face_detected=true` and
`is_primary_face=true`; sampled no-face rows are missing observations, not
zeros. Happy maps to Joy, Sad maps to Sadness, and Anger, Disgust, Fear,
Surprise, and Neutral map directly. Probabilities are multiplied by 100;
valence and arousal are multiplied by 100 from `[-1,1]` to `[-100,100]`.
Contempt and Confusion are unsupported blanks. Primary face is a confidence
heuristic, not verified speaker identity, and Py-Feat scores must not be treated
as AFFDEX-equivalent or as clinical ground truth.

For catalog runs, Analysis also requires every duplicated outer source label
(raw/display speaker, user/system metadata, and output mapping) to equal the
hash-bound embedded context and the copied run-root sidecars. Outer manifest
labels therefore cannot relabel a valid core artifact.

Analysis profiles may sort, filter, and regroup the actual SourceID set, then
rerun without mutating this processing tree or either source sidecar. Native
source counts are actual counts rather than a fixed display minimum.
