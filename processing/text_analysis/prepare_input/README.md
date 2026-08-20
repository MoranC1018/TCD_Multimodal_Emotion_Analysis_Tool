# Prepare Text Input

A command-line tool for the *Multimodal Emotion Analysis Tool* project.

Converts Whisper transcription JSON files into plain-text files ready for
RockSteady sentiment analysis. For bilingual JSONs, the English translation
(`text_en`) is used; for standard JSONs, the `text` field is used.

**Batch mode** mirrors the input directory structure in the output — so if your
JSONs live in nested folders (e.g. one subfolder per speaker), the `.txt` files
come out in the same layout.

---

## Requirements

- **Python 3.9 or newer**
- No additional packages — standard library only (`argparse`, `json`, `pathlib`)

---

## Usage

### Basic — single file

```bash
python whisper_to_rocksteady.py path/to/video.json
```

Writes `rocksteady_input/video.txt` by default.

### Batch — whole folder

```bash
python whisper_to_rocksteady.py processing/text_analysis/transcribe/output/
```

Recursively finds every `.json` under the folder and converts each one.
The output tree mirrors the input tree under `rocksteady_input/`:

```
transcribe/output/                          rocksteady_input/
  Jordan Bardella/                            Jordan Bardella/
    Le_9_juin,..._[ygpHlnyS-V4].json  →        Le_9_juin,..._[ygpHlnyS-V4].txt
  Marine_Le_Pen/                              Marine_Le_Pen/
    Appel_de_Marine_Le_Pen_...[p0q].json →     Appel_de_Marine_Le_Pen_...[p0q].txt
```

### Custom output directory

```bash
python whisper_to_rocksteady.py transcribe/output/ -o my_output/
```

### Full options

| Flag | Default | Purpose |
|------|---------|---------|
| `input` | (required) | A Whisper `.json` file **or a folder** of them |
| `-o` / `--output` | `rocksteady_input/` (next to this script) | Root output folder; structure mirrors input |
| `--lang` | `en` | Output language for bilingual JSONs: `en` or `fr` |
| `--help` | | Show all options |

---

## Input format

Whisper JSON files produced by `transcribe/transcribe.py`. Two variants are
supported:

**Standard** (`--task transcribe` or `--task translate`):
```json
{
  "task": "transcribe",
  "segments": [
    {"id": 0, "start": 0.0, "end": 4.2, "text": "Mes chers compatriotes,"},
    {"id": 1, "start": 4.2, "end": 9.8, "text": "ce soir je veux vous parler..."}
  ]
}
```

**Bilingual** (`--task bilingual`):
```json
{
  "task": "bilingual",
  "segments": [
    {"id": 0, "start": 0.0, "end": 4.2, "text_fr": "Mes chers compatriotes,", "text_en": "My dear fellow citizens,"},
    {"id": 1, "start": 4.2, "end": 9.8, "text_fr": "ce soir je veux vous parler...", "text_en": "tonight I want to talk to you..."}
  ]
}
```

For bilingual files, `text_en` is extracted; for all others, `text` is used.

---

## Output format

Each output `.txt` file contains all segment texts joined by spaces — a single
continuous paragraph of English text:

```
My dear fellow citizens, tonight I want to talk to you...
```

Segments with empty text are silently skipped.

---

## Workflow context

This script is **step 2** of the *Feeling Political Multimodal Emotion Analysis
Tool* text-modality workflow, sitting between Whisper transcription and
RockSteady sentiment scoring:

```
1. transcribe.py --from-preprocessing  →  transcribe/output/<Speaker>/<title>.json
2. whisper_to_rocksteady.py (this)     →  rocksteady_input/<Speaker>/<title>.txt
3. RockSteady (external, Percentage)   →  parse_output/output_percentage.csv
4. postprocessing/text.py split        →  text_output/<run>/<Speaker>.csv
5. postprocessing/text.py analyse      →  histograms, chi-squared, Spearman reports
```

---

*Part of the COALESCE-funded 'Multimodal Emotion Analysis Tool' project, TCD x Maynooth.*
