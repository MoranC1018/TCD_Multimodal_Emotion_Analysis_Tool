# Audio Pipeline Package

The package has two layers:

- `pipeline.py` analyses one `.mp4` and writes `audio_analysis.csv`,
  `opensmile_features.csv`, and `audio_analysis_manifest.json`.
- `batch.py` discovers `stitched_imotions.mp4` files in a procurement
  `downloads` folder and calls the single-video pipeline for each one.

The batch layer is orchestration. It loads the emotion models once per batch
and passes the same model bundle into every video run.

Supporting modules:

- `cli.py` exposes `python -m audio_pipeline batch ...` and
  `python -m audio_pipeline single ...`. If no `--output` is given, both modes
  write under the project `output` folder.
- `run_batch.py` and `run_single.py` are direct entrypoints for the two modes.
- `media.py` extracts 16 kHz mono WAV audio and per-window WAVs with `ffmpeg`.
- `windows.py` creates overlapping analysis windows.
- `opensmile_runner.py` calls `SMILExtract.exe` and writes
  `opensmile_features.csv`.
- `emotion_models.py` loads and reuses the Hugging Face categorical and
  dimensional emotion models through standard Transformers interfaces.
- `audio_analysis_csv.py` writes the per-window machine-output table.

This stage is audio-only. It does not produce transcripts, pass text into a
sentiment model, write interpretation paragraphs, or run statistical analysis.
