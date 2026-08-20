# Whisper Transcription Tool

A command-line tool for the *Multimodal Emotion Analysis Tool* project.

Transcribes a single video/audio file **or an entire folder tree** of videos
using OpenAI Whisper. Supports 99 languages, optional English translation, and
bilingual (original + English) output. Results are JSON files with segment-level
transcripts and timestamps, designed to feed into RockSteady or any downstream
sentiment-analysis tool.

**Batch mode** mirrors the input directory structure in the output — so if your
videos live in nested folders, the JSON files come out in the same layout.

---

## Requirements

- **Python 3.9 or newer** (tested on 3.12)
- **NVIDIA GPU with CUDA** (optional but strongly recommended — ~20x faster than CPU)
- **ffmpeg** (used by Whisper to read video/audio)
- **PyTorch** (with CUDA if using GPU)
- **openai-whisper**

---

## One-time setup

### 1. Check Python and GPU

```bash
python --version          # need 3.9+
nvidia-smi                # check GPU and CUDA version (NVIDIA cards only)
```

`nvidia-smi` will show something like `CUDA Version: 12.x`. Note that number;
you'll use it when installing PyTorch.

If you don't have an NVIDIA GPU, the script still works — it will fall back to
CPU automatically. Just much slower.

### 2. Install PyTorch

**GPU version (NVIDIA, recommended):**

Pick the CUDA version that matches (or is older than) the one shown by
`nvidia-smi`. CUDA 12.1 builds work with any 12.x driver.

```bash
# For CUDA 12.x drivers (most common)
pip install torch --index-url https://download.pytorch.org/whl/cu121

# For CUDA 11.8 drivers
pip install torch --index-url https://download.pytorch.org/whl/cu118
```

**CPU-only version (no NVIDIA GPU):**

```bash
pip install torch
```

Verify GPU is detected:

```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

Should print:
```
CUDA: True
GPU: NVIDIA GeForce RTX ...
```

### 3. Install Whisper

```bash
pip install openai-whisper
```

### 4. Install ffmpeg

**Windows:**
```bash
winget install ffmpeg
```
Then **restart your terminal** so the PATH update takes effect.

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt install ffmpeg
```

Verify:
```bash
ffmpeg -version
```

---

## Usage

### Basic — single file

```bash
python transcribe.py path/to/video.mp4
```

By default it uses `small` model, auto-detects language and device, and writes
the output to `output/<filename>.json`.

### From a preprocessing run (recommended)

Point at a preprocessing run folder and the script automatically finds the
right video per speech (stitched iMotions sample or full CC download) and
names each output JSON after the video title — not the filename:

```bash
python -m processing.text_analysis.transcribe.transcribe \
    --from-preprocessing preprocessing/output/<RUN_FOLDER> \
    --task bilingual --skip-existing \
    --output-dir processing/text_analysis/transcribe/output
```

Output structure mirrors `<Speaker>/<video_title>.json`.

### Batch — whole folder

```bash
python transcribe.py Videos/ --output-dir output
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

Resume an interrupted batch run with `--skip-existing` — any file whose JSON
already exists is silently skipped:

```bash
python transcribe.py Videos/ --skip-existing
```

### Specifying language and model

```bash
# English video, medium model
python transcribe.py speech.mp4 --model medium --language en

# French video, large-v3 (best quality)
python transcribe.py discours.mp4 --model large-v3 --language fr

# Polish video, medium model
python transcribe.py przemowienie.mp4 --model medium --language pl
```

### Windows paths with spaces

If your path contains spaces, **wrap it in double quotes**:

```bash
python transcribe.py "E:/Multimodal Emotion Analysis Tool/Videos/speech.mp4" --model small --language fr
```

Tip: in File Explorer, hold **Shift** + right-click a file → **Copy as path** to
get a pre-quoted path on the clipboard.

### Translating French to English

```bash
python transcribe.py discours.mp4 --task translate --language fr
```

Output segments will contain English text only (`"text": "..."`).

### Bilingual output (French + English side by side)

```bash
python transcribe.py discours.mp4 --task bilingual --language fr
```

Runs Whisper twice (one transcription pass, one translation pass) and merges
the results. Each segment contains both `text_fr` and `text_en`. Useful for
manually checking translation quality or feeding into tools that need both.
Note: takes roughly 2× longer than a single-pass run.

### Full options

| Flag | Default | Purpose |
|------|---------|---------|
| `input` | (required unless `--from-preprocessing`) | Path to a video/audio file **or a folder** |
| `--from-preprocessing` | — | Preprocessing run folder; auto-finds stitched/full videos, names outputs by title |
| `--model` | `small` | `tiny`, `base`, `small`, `medium`, `large`, `large-v2`, `large-v3` |
| `--language` | auto-detect | ISO code: `en`, `fr`, `pl`, `de`, `es`, ... |
| `--task` | `transcribe` | `transcribe`, `translate` (→ English), or `bilingual` (original + en) |
| `--device` | auto | `cpu` or `cuda` |
| `--output-dir` | `output` | Root output folder; structure mirrors input when using folder mode |
| `--skip-existing` | off | Skip files whose JSON output already exists (useful for resuming) |
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

On a laptop RTX 4070 (8 GB VRAM), `large-v3` with `fp16` fits — just close
other GPU programs first.

---

## Output

The script writes one JSON per input file. In folder mode the output tree
mirrors the input tree:

```
output/
├── speech.json          # single-file mode
└── GroupA/              # folder mode — subfolder preserved
    └── clip1.json
```

Structure (`--task transcribe` or `--task translate`):

```json
{
  "source": "speech.mp4",
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
  "segments": [
    {"id": 0, "start": 0.0, "end": 4.2, "text_fr": "Mes chers compatriotes,", "text_en": "My dear fellow citizens,"},
    {"id": 1, "start": 4.2, "end": 9.8, "text_fr": "ce soir je veux vous parler...", "text_en": "tonight I want to talk to you..."}
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

Subsequent runs use the cached file — no re-download.

---

## Troubleshooting

**`error: unrecognized arguments: Political\Videos\speech.mp4`**
Your path contains a space. Wrap the whole path in `"double quotes"`.

**`CUDA: False` after installing PyTorch**
You installed the CPU version by mistake. Uninstall and reinstall with the
`--index-url` flag:
```bash
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cu121
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
ffmpeg isn't installed or isn't on PATH. Install it (see setup step 4) and
**restart your terminal**.

**`WARNING: Ignoring invalid distribution ~ip ...`**
Harmless leftover from a previously-interrupted install. To clean up, open
the site-packages folder shown in the warning and delete any folder whose
name starts with `~` (e.g. `~ip`).

**Transcription quality is poor**
- Use a larger model (`medium` or `large-v3`)
- Make sure `--language` is set correctly — auto-detect occasionally picks the
  wrong language for very short or unclear audio
- Check the audio is actually audible: `ffplay your_video.mp4`

---

## Workflow context

This script is **step 1** of the *Feeling Political Multimodal Emotion Analysis
Tool* text-modality workflow:

```
0. preprocessing/run_pipeline.py     →   downloads/<Speaker>/<title>/stitched_imotions.mp4
1. transcribe.py --from-preprocessing →  transcribe/output/<Speaker>/<title>.json
2. whisper_to_rocksteady.py          →   rocksteady_input/<Speaker>/<title>.txt
3. RockSteady (external, Percentage) →   parse_output/output_percentage.csv
4. postprocessing/text.py split      →   text_output/<run>/<Speaker>.csv
5. postprocessing/text.py analyse    →   histograms, chi-squared, Spearman reports
```

The JSON output here feeds into
`processing/text_analysis/prepare_input/whisper_to_rocksteady.py`.

---

## Notes on non-English audio

Whisper supports 99 languages, but quality varies. As a rough guide:

- **Tier 1** (excellent): English, Spanish, French, German, Italian, Portuguese
- **Tier 2** (very good): Polish, Dutch, Russian, Mandarin, Japanese, Korean
- **Tier 3** (acceptable, use large-v3): most other European/Asian languages

For French and Polish — both relevant to the *Multimodal Emotion Analysis Tool* project —
`medium` is usually fine, `large-v3` is best.

**One caveat:** the downstream sentiment tool (RockSteady) may only support
English in the current version. If so, two options:

1. Run sentiment analysis only on English-source videos for now
2. Use `--task translate` to get English text from any source language
3. Use `--task bilingual` to keep both the original French and English translation

This is one of the things to confirm with Tracey before workshop day.

---

*Part of the COALESCE-funded 'Multimodal Emotion Analysis Tool' project, TCD x Maynooth.*
