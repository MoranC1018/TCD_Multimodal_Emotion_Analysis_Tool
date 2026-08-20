# Multimodal Emotion Analysis Tool Audio Analysis

This is the audio research data-extraction stage for the larger Multimodal
Emotion Analysis Tool. It takes `.mp4` files produced by procurement, extracts
audio-only per-window machine outputs, and preserves the speaker/video folder
structure for later statistical analysis.

This stage does not transcribe speech, does not run text sentiment analysis,
and does not make final emotion conclusions. Interpretation and any resulting
action remain the researcher's responsibility; this is not a diagnostic
system.

## Input

For catalog batch runs, point the script at the catalog run root containing
`source_manifest.json` and `source_metadata.csv`. Legacy procurement
`downloads` folders remain valid when they do not claim catalog provenance.
For example:

```text
C:\research\multimodal-emotion-analysis\procurement\output\<catalog-run>
```

The expected structure is:

```text
downloads/
  Speaker_Name/
    Video_Title_[youtube_id]/
      stitched_imotions.mp4
      raw_clips/
      extraction_metadata.json
      _extraction_complete.json
```

The batch script analyses `stitched_imotions.mp4` files and ignores `raw_clips`.

## Project Layout

Core operation:

- `audio_pipeline/` contains the runnable extraction package.
- `run_audio_analysis.py` is the repo-root friendly wrapper.
- The root `requirements.txt` lists Python dependencies for the extraction
  package.
- OpenSMILE is resolved from `OPENSMILE_HOME`, an explicit CLI path, or the
  bundled `opensmile-3.0-win-x64/` distribution.

Testing, QA, and verification:

- `tests/` contains fast automated unit and contract tests.
- Full real-media QA is maintained in the standalone `Audio_Analysis` workspace.

Research outputs:

- `output/` is the default destination for pipeline runs.

## Output

If you do not pass `--output`, results are written under:

```text
processing\audio_analysis\output
```

The batch output mirrors the input tree:

```text
audio_output/
  audio_analysis_manifest.csv
  run_log.txt
  Speaker_Name/
    Video_Title_[youtube_id]/
      audio_analysis.csv
      opensmile_features.csv
      audio_analysis_manifest.json
```

`audio_analysis.csv` starts with a small metadata block for source file,
speaker/video identifiers, model names, model availability, device/load
warnings, and window settings. After `#DATA`, it contains one row per analysis
window: window timing, categorical emotion probabilities, the max-probability
emotion label, emotion confidence, and dimensional affect scores when the
models are enabled. It does not contain
plain-English interpretation text, trend claims, persistence claims,
histograms, or final conclusions.

`opensmile_features.csv` is the full OpenSMILE numeric acoustic feature table.
It is kept for audit and later statistical work.

`audio_analysis_manifest.json` records per-video provenance. The batch-level
`audio_analysis_manifest.csv` and `run_log.txt` record processed files,
output paths, model names, window settings, and any errors.

For catalog inputs, the processor verifies that every discovered MP4 maps
exactly once to a selected manifest SourceID and that its speaker, source,
metadata, catalog digest, local-media identity, and output location match
`source_context.json`. Procurement cache/download directories are excluded from
discovery.
Missing, duplicate, unknown, or mismatched contexts fail before model loading.
The top-level `source_manifest.json` and `source_metadata.csv` are copied
byte-for-byte to the audio run and full-stack export; conflicting reused output
roots are rejected rather than overwritten. Per-video CSV/JSON outputs include
`SourceID`, raw `SourceSpeaker`, exact `SourceMetadata`, researcher
`UserLanguage`, and separate API-derived `YouTubeLanguage`. A pooled source
keeps a blank raw `SourceSpeaker` value while the analysis-facing `SpeakerName`
uses the explicit display label `Pooled (no speaker)`.

## Setup

Install Python 3.12 or newer, then make sure these external tools are available:

- `ffmpeg`
- `ffprobe`
- the bundled OpenSMILE 3.0.0 Windows distribution (revision `e882501`), or a
  compatible installation selected through `OPENSMILE_HOME`

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

The emotion models use Hugging Face Transformers and PyTorch. CPU-only machines
are supported, but CUDA is used automatically when available.

Check the exact Python environment the pipeline will use:

```powershell
python processing\audio_analysis\run_audio_analysis.py doctor
```

The doctor command checks Python packages, `ffmpeg`, `ffprobe`, and OpenSMILE
executable/config resolution. Run this before a large batch if model columns are
unexpectedly blank.

If `doctor` reports a missing package, run `pip install -r requirements.txt`
again from the repository root and restart the pipeline. Already-running batch
jobs do not pick up packages installed after they were started.

Optional Vox-Profile backend:

The pipeline can use the model author's local `vox-profile-release` wrapper for
the preferred categorical Whisper emotion model when it is explicitly
configured. Keep that checkout outside git, install its extra dependency if
needed, and set:

```powershell
$env:VOX_PROFILE_RELEASE_DIR="C:\path\to\vox-profile-release"
```

If that variable is not set, the tool first uses the standard Transformers
route for the preferred model. If the preferred adapter cannot load, the main
output uses `superb/wav2vec2-base-superb-er` so categorical columns remain
available. The manifest records the exact model and fallback warning.
Vox-Profile is not bundled or covered by this project's MIT License. Researchers
must review its current source, licence, model terms, and ethics implications
before configuring it.

## OpenSMILE Licence And Citation

The local `opensmile-3.0-win-x64/` directory is the OpenSMILE 3.0.0 Windows
distribution, revision `e882501`, sourced from audEERING's OpenSMILE project:
https://github.com/audeering/opensmile.

OpenSMILE is excluded from the root MIT License. It remains under the
audEERING Research License, including its non-commercial boundary and stated
conditions for limited commercial research. Further commercial or product use
requires the additional permission described in that licence. Preserve both:

```text
processing/audio_analysis/opensmile-3.0-win-x64/LICENSE
processing/audio_analysis/opensmile-3.0-win-x64/licenses/
```

Research publications using OpenSMILE should cite Florian Eyben, Martin
Wöllmer, and Björn Schuller, “openSMILE — The Munich Versatile and Fast
Open-Source Audio Feature Extractor,” ACM Multimedia, 2010,
https://doi.org/10.1145/1873951.1874246. See the root
`THIRD_PARTY_NOTICES.md` for the complete redistribution boundary.

## Run a Batch

```powershell
python processing\audio_analysis\run_audio_analysis.py batch "path\to\downloads"
```

Repeat `--source-id` to analyze only authorized catalog sources and provide the
digest shown in that same run's `source_manifest.json`. The digest is checked
before model loading or output writes, and output order remains
catalog/discovery order:

```powershell
python processing\audio_analysis\run_audio_analysis.py batch "path\to\catalog-run" `
  --catalog-sha256 <sha256> `
  --source-id source-0001 --source-id source-0003
```

Use `--output "path\to\audio_output"` only when you want a different output
folder.

The console prints progress while it runs: input/output folders, model loading,
videos found, the current video number, OpenSMILE progress, model progress, and
any error message. A copy of the batch result is also written to `run_log.txt`.

## Run QA

For fast code checks from the repository root:

```powershell
python -m unittest discover -s processing\audio_analysis\tests
```

Full real-media QA is run from the standalone `Audio_Analysis` workspace so
generated reports and media fixtures stay out of the main repository.

## Run One Video Directly

```powershell
python processing\audio_analysis\run_audio_analysis.py single "path\to\stitched_imotions.mp4"
```

For a `stitched_imotions.mp4` inside a procurement `downloads` tree, the
single-video command writes to the same speaker/video subfolder that the batch
command would use.

Equivalent direct modules are also available:

```powershell
python -m processing.audio_analysis.audio_pipeline.run_batch "path\to\downloads"
python -m processing.audio_analysis.audio_pipeline.run_single "path\to\stitched_imotions.mp4"
```

## Options

```powershell
--window-seconds 10
--stride-seconds 5
--opensmile-feature-set egemaps
--device auto
--skip-emotion-models
--keep-temp-audio
--debug
--catalog-sha256 <sha256>  # binds selected SourceIDs to this batch folder
--source-id source-0001  # batch commands only; repeat as needed
```

Use `egemaps` for the standard OpenSMILE feature set. `compare16` is available
for larger OpenSMILE feature extraction if needed later.

Use `--skip-emotion-models` when you need OpenSMILE-only extraction or when the
Hugging Face model dependencies/models are unavailable. The CSV schema is still
written, but model-output cells are blank.

Use `--device cpu` to force CPU, `--device cuda` to require CUDA, or
`--device auto` to use CUDA when PyTorch reports it is available.

`--keep-temp-audio` keeps extracted WAV windows under `_debug_audio` in each
per-video output folder. Without it, temporary audio is cleaned up.

`--debug` also writes the fallback categorical model to
`debug/fallback_audio_analysis.csv` for an explicit comparison. This debug CSV
is separate from the main `audio_analysis.csv`. If the preferred model was
already unavailable, the main manifest will show that the same fallback model
was used there. If `--skip-emotion-models` is also set, debug fallback output
is skipped.

## Model Outputs

Categorical model:

```text
tiantiaf/whisper-large-v3-msp-podcast-emotion
```

If the preferred categorical model is unavailable, the main output uses:

```text
superb/wav2vec2-base-superb-er
```

The manifest records the selected model and the preferred-model error. The
categorical columns are blank only when neither categorical model can load, or
when `--skip-emotion-models` is selected.

`audio_analysis.csv` includes probability columns for:

```text
Anger, Contempt, Disgust, Fear, Happiness, Neutral, Sadness, Surprise, Other
```

`PredictedEmotion` is the highest-probability class for that window.
`EmotionConfidence` is that probability.

Dimensional model:

```text
audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim
```

When enabled, `audio_analysis.csv` includes raw model scores for:

```text
Arousal, Dominance, Valence
```

These model outputs are estimates. They must be validated later against
manually labelled samples before being treated as research conclusions.
