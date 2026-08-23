# Whisper Transcription Tool

A command-line tool for the *Multimodal Emotion Analysis Tool* project.

Transcribes a single video/audio file **or an entire folder tree** of videos
using OpenAI Whisper. Supports 99 languages, optional English translation, and
bilingual (original + English) output. Results are JSON files with segment-level
transcripts and timestamps, designed to feed into RockSteady or any downstream
sentiment-analysis tool.

**Batch mode** mirrors the input directory structure in the output - so if your
videos live in nested folders, the JSON files come out in the same layout.

---

## Requirements

- **Python 3.11 or newer** (Python 3.12 is tested and recommended; other
  versions compatible with the pinned stack are accepted)
- **NVIDIA GPU with CUDA** (optional but strongly recommended - ~20x faster than CPU)
- **ffmpeg** (used by Whisper to read video/audio)
- **PyTorch** (with CUDA if using GPU)
- **openai-whisper**

---

## One-time setup

Use the repository installer so Whisper, Py-Feat and the other processing
modules share one tested Torch family:

```powershell
# Automatically selects CUDA for a compatible NVIDIA GPU, otherwise CPU
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# Optional explicit overrides
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -TorchRuntime cu128
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -TorchRuntime cpu
```

Do not independently reinstall Torch from this submodule: doing so can replace
TorchVision, TorchAudio or TorchCodec with an incompatible build. The setup
script also installs the supported shared FFmpeg runtime and verifies the final
environment. Without an NVIDIA GPU, Whisper automatically uses CPU and runs
more slowly.

---

## Usage

### Basic - single file

```bash
python -m processing.text_analysis.transcribe.transcribe path/to/video.mp4
```

By default it uses `small` model, auto-detects language and device, and writes
the output to `output/<filename>.json`.

### From a procurement run (recommended)

Point at a procurement run folder and the script automatically finds the
right video per speech (stitched iMotions sample or full CC download) and
names each output JSON after the video title - not the filename:

```bash
python -m processing.text_analysis.transcribe.transcribe \
    --from-procurement procurement/output/<RUN_FOLDER> \
    --task bilingual --skip-existing \
    --output-dir processing/text_analysis/transcribe/output
```

The existing procurement layout is used directly:
`downloads/<Speaker>/<Video>/`. An optional transport-only `_full_video`
suffix is removed from the Text video identity. No country or comparison group
is inferred from the folder name. Output uses
`original|eng|bilingual/<Speaker>/<Video>.json`.

### Batch - whole folder

```bash
python -m processing.text_analysis.transcribe.transcribe Videos/ --output-dir output
```

Recursively finds every video/audio file under the folder and transcribes each
one. The output tree mirrors the input tree:

```
Videos/                     output/
  GroupA/                     GroupA/
    clip1.mp4       →           clip1.json
    clip2.mp4       →           clip2.json
  GroupB/                     GroupB/
    clip3.mkv       →           clip3.json
```

Resume an interrupted batch run with `--skip-existing`. In bilingual mode, a
video is skipped only when all three outputs exist. If `original` and/or `eng`
already exist but `bilingual` is missing, the saved Whisper passes are reused;
alignment is retried without rerunning those expensive passes:

```bash
python -m processing.text_analysis.transcribe.transcribe Videos/ --skip-existing
```

### Specifying language and model

```bash
# English video, medium model
python -m processing.text_analysis.transcribe.transcribe speech.mp4 --model medium --language en

# French video, large-v3 (best quality)
python -m processing.text_analysis.transcribe.transcribe discours.mp4 --model large-v3 --language fr

# Polish video, medium model
python -m processing.text_analysis.transcribe.transcribe przemowienie.mp4 --model medium --language pl
```

### Windows paths with spaces

If your path contains spaces, **wrap it in double quotes**:

```bash
python -m processing.text_analysis.transcribe.transcribe "E:/Multimodal Emotion Analysis Tool/Videos/speech.mp4" --model small --language fr
```

Tip: in File Explorer, hold **Shift** + right-click a file → **Copy as path** to
get a pre-quoted path on the clipboard.

### Translating French to English

```bash
python -m processing.text_analysis.transcribe.transcribe discours.mp4 --task translate --language fr
```

Output segments will contain English text only (`"text": "..."`).

### Bilingual output (original language + English side by side)

```bash
python -m processing.text_analysis.transcribe.transcribe discours.mp4 --task bilingual --language fr
```

Runs Whisper twice (one transcription pass, one translation pass) and writes
three separate output trees:

```text
output/original/<Country>/<Speaker>/<Video>.json
output/eng/<Country>/<Speaker>/<Video>.json
output/bilingual/<Country>/<Speaker>/<Video>.json
```

`original` and `eng` preserve their own Whisper segments unchanged, so either
tree can be converted directly for the matching RockSteady dictionary.
`bilingual` aligns the two passes by timestamp overlap for side-by-side review.
Equal segment counts are not assumed to mean
equal boundaries. One-to-many and many-to-one matches are merged into a single
aligned segment, and each source segment is used exactly once. Alignments with
no overlap or less than 25% interval overlap are rejected instead of silently
pairing unrelated text. The audit records every source segment ID and hashes of
both standalone segment lists; any duplicate or omitted ID aborts the output.
Each merged segment contains `text_original` and `text_en`; the top-level
`language` field records what language `text_original` is, such as `fr`, `it`,
or `pl`. Useful for manually checking translation quality or feeding into tools
that need both.
Note: takes roughly 2× longer than a single-pass run.

The automated pipeline selects one tree per country. By default every discovered
country uses the English pass, matching the default English dictionaries:

```powershell
python -m processing.text_analysis Videos --from-stage select
```

Per-country source-language overrides are available through `language_policy`
in the Text JSON configuration. The `bilingual` tree remains intended for human
comparison and alignment auditing, not as a third RockSteady input.

#### Known bilingual limitations (recorded, not automatically corrected)

- Whisper itself may repeat text, return empty segments, omit speech, or produce
  an inaccurate English translation. The pipeline does not remove or repair
  Whisper-generated content.
- The structural audit guarantees only that every segment returned by each
  Whisper pass is referenced once in the merged file. It cannot prove that
  Whisper heard every word in the audio or that repeated text is intentional.
- `--skip-existing` reuses a pass only when its JSON structure, task, model,
  source SHA-256 and complete Whisper/checkpoint/runtime/decoding provenance
  match. Bilingual completion is validated as an exact three-artifact set, so
  a missing or mismatched `original`, `eng`, or `bilingual` companion forces
  repair instead of skipping. A same-size file replacement cannot therefore
  reuse an unrelated transcript. Legacy
  output is not reusable by default; `--trust-legacy` is an explicit unsafe
  migration option.
- Each expensive Whisper pass is saved immediately. If bilingual alignment
  fails, `original` and `eng` remain usable and can be reused on the next
  `--skip-existing` run. One output-set lock prevents concurrent standalone and
  full-pipeline writers. Ctrl-C changes a running batch manifest to
  `interrupted`; temporary JSON files are removed, and automation never treats
  a partial state as complete.
- The reported overlap is calculated for each merged alignment group. A high
  group overlap can still contain coarse local matching, so the merged file is
  suitable for comparison but not guaranteed sentence-level alignment.
- The independent `original` and `eng` trees can have different segment counts
  and boundaries. Their RockSteady rows must not be joined directly by segment
  number; a later comparison must use the bilingual mapping.

### Full options

| Flag | Default | Purpose |
|------|---------|---------|
| `input` | (required unless `--from-procurement`) | Path to a video/audio file **or a folder** |
| `--from-procurement` | - | Procurement run or `downloads` folder; auto-finds stitched/full videos and preserves the existing `Speaker/Video` identity |
| `--model` | `small` | `tiny`, `base`, `small`, `medium`, `large`, `large-v2`, `large-v3` |
| `--language` | auto-detect | ISO code: `en`, `fr`, `pl`, `de`, `es`, ... |
| `--task` | `transcribe` | `transcribe`, `translate` (→ English), or `bilingual` (original + en) |
| `--device` | auto | `cpu` or `cuda` |
| `--output-dir` | `output` | Root output folder; structure mirrors input when using folder mode |
| `--skip-existing` | off | Resume safely; reuse saved original/eng passes and skip only complete bilingual sets |
| `--trust-legacy` | off | Unsafely allow pre-v2 outputs without complete provenance to be reused during migration |
| `--canonical-layout` | off | Legacy/manual input mode: require `NNN_Country_Speaker_DATE` names and write `Country/Speaker/Video.json` |
| `--speaker-parent-layout` | off | General media mode: use the media file's direct parent folder as `Speaker` and its filename stem as `Video`; the full Text pipeline uses this for non-`downloads` input |
| `--batch-manifest` | `<output>/_manifests/transcription_run_manifest.json` | Structured batch status and authoritative video inventory |
| `--help` | | Show all options |

---

## Choosing a model

| Model | Size | VRAM (fp16) | Speed (GPU) | Quality |
|-------|------|-------------|-------------|---------|
| `tiny` | 75 MB | ~1 GB | very fast | poor |
| `base` | 140 MB | ~1 GB | very fast | okay |
| `small` | 460 MB | ~2 GB | fast | good for English |
| `medium` | 1.5 GB | ~5 GB | medium | good for most languages |
| `large-v3` | 3 GB | ~6–10 GB | slow | best (recommended for non-English) |

**Recommendations:**
- **English clean audio** → `small` is often enough
- **French or Polish** → use `medium` minimum, `large-v3` if VRAM allows
- **Noisy audio, strong accents, low-volume speech** → `large-v3`

On a laptop RTX 4070 (8 GB VRAM), `large-v3` with `fp16` fits - just close
other GPU programs first.

---

## Output

For `transcribe` and `translate`, the script writes one JSON per input file and
mirrors the input tree. For `bilingual`, it writes the three trees described
above:

```
output/
├── speech.json          # single-file mode
└── GroupA/              # folder mode - subfolder preserved
    └── clip1.json
```

Structure (`--task transcribe` or `--task translate`):

```json
{
  "schema_version": "2.0",
  "source": "speech.mp4",
  "source_fingerprint": {"size": 123456, "mtime_ns": 1770000000000000000},
  "source_sha256": "...",
  "language": "fr",
  "task": "transcribe",
  "duration_sec": 423.5,
  "model": "medium",
  "device": "cuda",
  "segments": [
    {"id": 0, "start": 0.0, "end": 4.2, "text": "Mes chers compatriotes,"},
    {"id": 1, "start": 4.2, "end": 9.8, "text": "ce soir je veux vous parler..."}
  ]
}
```

Structure (`--task bilingual`):

```json
{
  "source": "speech.mp4",
  "language": "fr",
  "task": "bilingual",
  "duration_sec": 423.5,
  "model": "medium",
  "device": "cuda",
  "bilingual_alignment": {
    "method": "mutual_best_time_overlap_components",
    "original_input_segments": 2,
    "english_input_segments": 2,
    "aligned_output_segments": 2,
    "original_segments_used_once": true,
    "english_segments_used_once": true,
    "minimum_overlap_ratio": 0.91,
    "mean_overlap_ratio": 0.95
  },
  "segments": [
    {"id": 0, "start": 0.0, "end": 4.2, "text_original": "Mes chers compatriotes,", "text_en": "My dear fellow citizens,", "alignment_original_segments": 1, "alignment_en_segments": 1, "alignment_overlap_ratio": 0.95, "source_original_segment_indexes": [0], "source_en_segment_indexes": [0], "source_original_segment_ids": [0], "source_en_segment_ids": [0]},
    {"id": 1, "start": 4.2, "end": 9.8, "text_original": "ce soir je veux vous parler...", "text_en": "tonight I want to talk to you..."}
  ]
}
```

Each segment has its own timestamp range, so you can later align sentiment
scores back to specific moments in the video.

---

## First-time model download

On the first run with a given model size, Whisper will download the model
weights automatically. Sizes range from 75 MB (`tiny`) to 3 GB (`large-v3`).

**Storage location:**
- **Windows:** `C:\Users\<you>\.cache\whisper\`
- **macOS / Linux:** `~/.cache/whisper/`

Subsequent runs use the cached file - no re-download.

---

## Troubleshooting

**`error: unrecognized arguments: Research Project\Videos\speech.mp4`**
Your path contains a space. Wrap the whole path in `"double quotes"`.

**`CUDA: False` after installing PyTorch**
Confirm that the NVIDIA driver supports CUDA 12.8, then rerun the Text
installer:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -TorchRuntime cu128
```

**`torch.cuda.OutOfMemoryError: CUDA out of memory`**
Your model is too big for the available VRAM. Try, in order:
1. Close other GPU programs (Chrome, other ML scripts)
2. Drop down one model size (`large-v3` → `medium`)
3. Process shorter clips with ffmpeg first:
   ```bash
   ffmpeg -i long.mp4 -ss 00:00:00 -t 00:05:00 -c copy clip.mp4
   ```

**`FileNotFoundError` mentioning ffmpeg**
Rerun `scripts\setup.ps1`; it installs the shared FFmpeg build used by both
Whisper and TorchCodec and verifies discovery before returning.

**`WARNING: Ignoring invalid distribution ~ip ...`**
Harmless leftover from a previously-interrupted install. To clean up, open
the site-packages folder shown in the warning and delete any folder whose
name starts with `~` (e.g. `~ip`).

**Transcription quality is poor**
- Use a larger model (`medium` or `large-v3`)
- Make sure `--language` is set correctly - auto-detect occasionally picks the
  wrong language for very short or unclear audio
- Check the audio is actually audible: `ffplay your_video.mp4`

---

## Workflow context

This script is **step 1** of the *TCD Multimodal Emotion Analysis Tool*
text-modality workflow:

```
0. procurement                    →   videos arranged by Speaker/Video
1. transcribe.py --task bilingual   →   output/current/transcripts/{original,eng,bilingual}/...
2. language selection               →   output/current/selected_transcripts/<Speaker>/<Video>.json
3. whisper_to_rocksteady.py         →   output/current/prepared_segments/<Speaker>/<Video>/...
4. RockSteady (external, Total)     →   output/current/rocksteady/{all,core}/...
5. analysis/text.py           →   selected/extra reports
```

Those are the integrated Text-pipeline locations. The standalone transcription
command still defaults to a local `output/` directory unless `--output-dir` is
provided.

The JSON output here feeds into
`processing/text_analysis/prepare_input/whisper_to_rocksteady.py`.

---

## Notes on non-English audio

Whisper supports 99 languages, but quality varies. As a rough guide:

- **Tier 1** (excellent): English, Spanish, French, German, Italian, Portuguese
- **Tier 2** (very good): Polish, Dutch, Russian, Mandarin, Japanese, Korean
- **Tier 3** (acceptable, use large-v3): most other European/Asian languages

For French and Polish - both relevant to the *Multimodal Emotion Analysis Tool* project -
`medium` is usually fine, `large-v3` is best.

**One caveat:** the downstream sentiment tool (RockSteady) may only support
English in the current version. If so, two options:

1. Run sentiment analysis only on English-source videos for now
2. Use `--task translate` to get English text from any source language
3. Use `--task bilingual` to keep both the original language and English translation

This is one of the things to confirm with Tracey before workshop day.

---

*Part of the COALESCE-funded 'Multimodal Emotion Analysis Tool' project, TCD x Maynooth.*
