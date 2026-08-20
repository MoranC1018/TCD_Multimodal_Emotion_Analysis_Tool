# Text Processing

The package keeps each scientific stage independent while adding one command
for the complete **Text-only** pipeline. It never starts Face or Audio.
Existing CSV and graph formats are produced by the same
`analysis.text_pipeline.postprocess` implementation, so automation does not change the
current Text output contract.

## One-command workflow

```powershell
python -m processing.text_analysis Videos
```

Stages:

1. Whisper bilingual transcription.
2. Discover every country and select the English Whisper pass by default,
   matching the embedded General Language English dictionary. Per-country
   `language_policy` overrides remain available when a different variant is
   intentionally required.
3. One text file per Whisper segment.
4. One canonical RockSteady Total analysis with the General Language English
   dictionary. With the default empty `categories` list, RockSteady discovers
   and exports all 45 categories in that dictionary. A mechanically filtered
   seven-category core CSV view is then derived from the same run, guaranteeing
   that common `selected` and `extra` counts are identical.
5. Current-format segment, video, speaker, descriptor and SVG outputs.

Long-running work can resume at a stage:

```powershell
python -m processing.text_analysis Videos --from-stage prepare
python -m processing.text_analysis Videos --from-stage postprocess
```

Resume is provenance-bound: the command validates the exact upstream manifest,
source content hashes and identity set before it runs a later stage. It will
not scan in old videos from a previous output directory.

Check Java, the adapter, the JAR, dictionaries and categories without requiring
an input video:

```powershell
python -m processing.text_analysis --check
python -m processing.text_analysis --check --config path\to\text-config.json
```

The check prints JSON and exits `0` only when the exact requested configuration
is ready. A normal CLI error is concise; add `--debug` when a traceback is
useful for development. Any stage range containing RockSteady performs this
preflight before Whisper starts, so a missing runtime cannot waste a long
transcription run.

The current run is easy to inspect in one Text-owned tree:

```text
processing/text_analysis/output/
  pipeline_manifest.json
  runs/<run-id>/pipeline_manifest.json
  current/
    transcripts/{original,eng,bilingual}/<Country>/<Speaker>/<Video>.json
    selected_transcripts/<Country>/<Speaker>/<Video>.json
    prepared_segments/<Country>/<Speaker>/<Video>/*.txt
    rocksteady/all/<Country>/<Speaker>/<Video>.csv
    rocksteady/core/<Country>/<Speaker>/<Video>.csv
```

The final statistical locations and file formats remain:

```text
analysis/output/text/text_output/selected
analysis/output/text/text_output/extra
analysis/output/text/text_output/multimodal
```

`processing/text_analysis/output/pipeline_manifest.json` is written as
`running` before work begins and records the shared `run_id`, commands, stage
inputs/outputs/counts, failure details, actual artifacts, and one authoritative
per-video inventory. Each underlying module remains directly callable for
testing or specialist use.

## Configuration boundaries

`config.example.json` documents the supported orchestration settings. Output
roots, Whisper model/device, thread count, dictionaries, categories, dictionary
merge policy, graph generation, and per-country language overrides are
configurable.
An empty `language_policy` means “discover every country and use
`default_language_variant`”, which defaults to English.

Use the same file with either entry point:

```powershell
python -m processing.text_analysis Videos --config path\to\text-config.json
python -m processing.text_analysis --check --config path\to\text-config.json
```

An explicit category list may contain only the extra categories a caller wants;
the pipeline automatically includes the seven stable core categories needed by
the `core` view. An empty list still means every category in the selected
dictionaries.

RockSteady's Simple analyser is intentionally the only production analyser:
the bundled Stanford analyser in RockSteady 0.4 returns no tokens and would
silently produce zero-valued results. Percentage and z-score exports remain
available from the standalone adapter, but this automated pipeline fixes
`value_type=total` because the current postprocessing contract is count-based.

The normal example uses only General Language. The opt-in
`config.integrated.example.json` shows the merged Oil/Finance/Economics setup
and its explicit 17-category contract; it is intentionally not the default.

Older generated folders under `transcribe/output`, `prepare_input`, and
`parse_output` are left untouched. They predate content hashes and complete
model provenance, so the current pipeline does not silently trust or relabel
them as resumable v2 output.
