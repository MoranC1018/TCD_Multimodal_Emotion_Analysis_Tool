# Prepare Text Input

A command-line tool for the *Multimodal Emotion Analysis Tool* project.

Converts Whisper transcription JSON files into plain-text files ready for
RockSteady sentiment analysis. By default, each Whisper segment becomes one
RockSteady input file, so text postprocessing can analyse segment-level
emotion-word distributions instead of one whole-speech aggregate. For bilingual
JSONs, the original-language text (`text_original`) is used by default; for
standard JSONs, the `text` field is used.

**Batch mode** mirrors the input directory structure in the output - so if your
JSONs live in nested folders (e.g. one subfolder per speaker), the segment
`.txt` files come out in the same layout.

---

## Requirements

- **Python 3.11 or newer** (Python 3.12 is tested and recommended; other
  versions compatible with the pinned stack are accepted)
- No additional packages - standard library only (`argparse`, `json`, `pathlib`)

---

## Usage

### Basic - single file

```bash
python -m processing.text_analysis.prepare_input.whisper_to_rocksteady path/to/video.json
```

Writes files like `rocksteady_input_segments/video/video__segment_000001.txt`,
`rocksteady_input_segments/video/video__segment_000002.txt`, and so on by default.

### Batch - whole folder

```bash
python -m processing.text_analysis.prepare_input.whisper_to_rocksteady \\
    processing/text_analysis/transcribe/output/selected \\
    -o processing/text_analysis/prepare_input/rocksteady_selected
```

Recursively finds every `.json` under the folder and converts each one.
The output tree mirrors the input tree under `rocksteady_input_segments/`:

```
transcribe/output/                          rocksteady_input_segments/
  Research Speaker A/                         Research Speaker A/
    001_20250609_France_...json       →        001_20250609_France_.../
                                                  001_20250609_France_...__segment_000001.txt
                                                  001_20250609_France_...__segment_000002.txt
  Research_Speaker_B/                         Research_Speaker_B/
    002_20250501_France_...json       →        002_20250501_France_.../
                                                  002_20250501_France_...__segment_000001.txt
                                                  002_20250501_France_...__segment_000002.txt
```

### Custom output directory

```bash
python -m processing.text_analysis.prepare_input.whisper_to_rocksteady \\
    processing/text_analysis/transcribe/output/selected -o rocksteady_selected/
```

### Pick a bilingual output language

```bash
python -m processing.text_analysis.prepare_input.whisper_to_rocksteady \\
    processing/text_analysis/transcribe/output/selected \\
    -o processing/text_analysis/prepare_input/rocksteady_selected --lang original
```

For newer bilingual JSONs, `original` means the source language recorded in the
top-level `language` field. Language-specific options such as `--lang it` are
kept for compatibility with older JSONs and fall back to `text_original`.

### Full options

| Flag | Default | Purpose |
|------|---------|---------|
| `input` | (required) | A Whisper `.json` file **or a folder** of them |
| `-o` / `--output` | `rocksteady_input_segments/` (next to this script) | Root output folder; structure mirrors input |
| `--lang` | `original` | Output language for bilingual JSONs: `original` or `en`; language codes are accepted for older JSONs and fall back to original text |
| `--join-segments` | off | Write one full-speech `.txt` per JSON, matching the old behavior |
| `--inventory` | - | Completed `selection_manifest.json`; restricts input to its exact identity set and verifies every selected JSON hash |
| `--batch-manifest` | `<output parent>/_manifests/<output>_prepare_run_manifest.json` | Structured batch status, lineage and artifact inventory |
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
  "language": "fr",
  "task": "bilingual",
  "segments": [
    {"id": 0, "start": 0.0, "end": 4.2, "text_original": "Mes chers compatriotes,", "text_en": "My dear fellow citizens,"},
    {"id": 1, "start": 4.2, "end": 9.8, "text_original": "ce soir je veux vous parler...", "text_en": "tonight I want to talk to you..."}
  ]
}
```

For bilingual files, `text_original` is extracted by default; pass `--lang en`
to extract `text_en`. For older bilingual files with language-specific fields
such as `text_fr`, `text_it`, or `text_pl`, those fields are still used when
requested; otherwise the script falls back to `text_original`. For all
non-bilingual files, `text` is used.

---

## Output format

Each output `.txt` file contains exactly one Whisper segment in the selected
language, with no timestamp or metadata. This keeps RockSteady from counting
timecodes as text:

```
My dear fellow citizens,
```

Segments with empty text are excluded from RockSteady input, but never silently
forgotten: each video has a `.prepare_manifest.json` mapping contiguous,
one-based `analysis_segment_id` values back to the zero-based
`source_segment_index` and original nullable `source_segment_id`. Postprocessing
uses this mapping instead of assuming the two numbering systems are identical.
If the old whole-speech format is needed, pass `--join-segments`.

The per-video manifest also binds the exact selected Whisper JSON SHA-256 to a
digest of every segment filename, text byte and mapping row. Before reuse, the
tree validator recomputes that digest and rejects gaps, reordered mappings,
changed text, or a prepare/selection lineage mismatch.

Each video's segment files are staged in a temporary directory and then replace
the previous video directory as one complete set. Re-running the converter after
a transcription changes therefore removes obsolete higher-numbered segment
files instead of mixing them with the new output.

Batch conversion writes a structured manifest (`--batch-manifest`) and accepts
the exact selection inventory with `--inventory`. It attempts every video but
returns nonzero and preserves the previous complete output root if any input
fails. A whole-stage lock prevents two standalone/pipeline writers targeting
the same root. Ctrl-C removes the new staging tree, marks the manifest
`interrupted`, and leaves the previous visible output untouched.

---

## Workflow context

This script is **step 3** of the *TCD Multimodal Emotion Analysis Tool*
text-modality workflow, sitting between Whisper transcription and
RockSteady sentiment scoring:

```
1. transcribe.py --task bilingual      →  output/current/transcripts/{original,eng,bilingual}/...
2. selection.py                        →  output/current/selected_transcripts/<Country>/<Speaker>/<Video>.json
3. whisper_to_rocksteady.py (this)     →  output/current/prepared_segments/.../<Video>__segment_000001.txt
4. rocksteady_adapter (Total mode)     →  output/current/rocksteady/{all,core}/...
5. analysis/text.py              →  selected/extra summaries, audits and SVG graphs
```

These are the integrated pipeline locations. Direct standalone commands above
may use any explicit `--output` directory.

All stages follow the rules in
[`../NAMING_CONVENTION.md`](../NAMING_CONVENTION.md).

---

*Part of the COALESCE-funded 'Multimodal Emotion Analysis Tool' project, TCD x Maynooth.*
