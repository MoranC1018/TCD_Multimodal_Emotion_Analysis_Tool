# Text Processing

The package keeps each scientific stage independent while adding one command
for the complete **Text-only** pipeline. It never starts Face or Audio.
Existing CSV and graph formats are produced by the same
`analysis.text_pipeline.postprocess` implementation, so automation does not change the
current Text output contract.

## One-command workflow

```powershell
.\.venv\Scripts\python.exe -m processing.text_analysis Videos
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
.\.venv\Scripts\python.exe -m processing.text_analysis Videos --from-stage prepare
.\.venv\Scripts\python.exe -m processing.text_analysis Videos --from-stage postprocess
```

Resume is provenance-bound: the command validates the exact upstream manifest,
source content hashes and identity set before it runs a later stage. It will
not scan in old videos from a previous output directory.

Check Java, the adapter, the JAR, dictionaries and categories without requiring
an input video:

```powershell
.\.venv\Scripts\python.exe -m processing.text_analysis --check
.\.venv\Scripts\python.exe -m processing.text_analysis --check --config path\to\text-config.json
```

The check prints JSON and exits `0` only when the exact requested configuration
is ready. A normal CLI error is concise; add `--debug` when a traceback is
useful for development. Any stage range containing RockSteady performs this
preflight before Whisper starts, so a missing runtime cannot waste a long
transcription run.

RockSteady 0.4, its dictionaries, and a supported JDK/Javac remain separately
licensed requirements. The supported Windows installer materializes and
validates the tracked RockSteady Git LFS JAR, including its embedded default
dictionary, and locates or installs a complete JDK with both `java` and `javac`.
Use `-TextMode Require` to fail unless Text readiness succeeds. Git/Git LFS and
repository LFS access are needed when the JAR is missing or still a pointer;
see [Installation and validation](../../docs/INSTALLATION_VALIDATION.md).
Whisper, Torch, trusted FFmpeg, Java, the adapter/JAR, dictionaries, and selected
categories must all pass the structured readiness contract for the requested
stage range.

The Whisper preflight checks its installed engine, expected checkpoint identity,
Torch and FFmpeg. It does not load local Whisper weights or transcribe audio.
The first transcription can still need a checkpoint download. Verify a short
representative input before a large or offline batch.

The current run is easy to inspect in one Text-owned tree:

```text
processing/text_analysis/output/
  source_manifest.json      # catalog mode: exact sealed top JSON bytes
  source_metadata.csv       # catalog mode: exact sealed top CSV bytes
  pipeline_manifest.json
  runs/<run-id>/pipeline_manifest.json
  current/
    transcripts/{original,eng,bilingual}/<Country>/<Speaker>/<Video>.json
    selected_transcripts/<Country>/<Speaker>/<Video>.json
    prepared_segments/<Country>/<Speaker>/<Video>/*.txt
    rocksteady/all/<Country>/<Speaker>/<Video>.csv
    rocksteady/core/<Country>/<Speaker>/<Video>.csv
```

The pipeline manifest stores the exact catalog digest and ordered
`processed_source_ids` separately; it never rewrites the full source manifest
to resemble the selection. Every transcript, selected/prepared item,
RockSteady job, derived row, and postprocessing manifest retains SourceID,
raw/display speaker, content hash/size, user/system metadata, output mapping,
catalog digest, and source-context identity. Resume fingerprints include this
binding, so two identities cannot exchange SourceIDs merely because their media
bytes match.

Catalog discovery is manifest ordered and accepts only canonical final media.
It excludes private caches, raw clips, focus/segment/intermediate artifacts,
and validates all sidecars before Whisper, cleanup, RockSteady, or publication.
Only `Speaker` can create grouping folders; Country, researcher `Language`,
Gender, and all other fields remain metadata. Repeated links remain distinct
SourceIDs. Transcription language precedence is YouTube-reported
`system_metadata.youtube_language`, then the explicit Whisper language, then
blank; the researcher `Language` field never overrides it.

The final statistical locations and file formats remain:

```text
analysis/output/text/text_output/selected
analysis/output/text/text_output/extra
analysis/output/text/text_output/multimodal
analysis/output/text/text_output/source_manifest.json
analysis/output/text/text_output/source_metadata.csv
```

Native postprocessing publishes a SourceID-grain `video_level_summary.csv`
with its bound pair manifest. Catalog runs also copy the exact validated
sidecar bytes into this explicit postprocessing run root. The pair manifest
binds their SHA-256 values, the catalog digest, and each ordered source-context
object/hash; Analysis never searches a fixed number of parent directories or
accepts a replacement catalog with coincidentally matching SourceIDs. Analysis
prefers that file, validates its hash, sidecars, ordered SourceID coverage, and
identity alignment, and supports SourceID profile splits. It retains the legacy speaker-grain
`speaker_level_summary.csv` importer, for which one speaker may not be split
across groups.

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
.\.venv\Scripts\python.exe -m processing.text_analysis Videos --config path\to\text-config.json
.\.venv\Scripts\python.exe -m processing.text_analysis --check --config path\to\text-config.json
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

## Text constructs and profile reruns

Positive Sentiment and Negative Sentiment use `[0,1]`; legacy `Positive
valence` and `Negative valence` headers are accepted only as compatibility
aliases. Text Valence is
`(Positive Sentiment - Negative Sentiment) / (Positive Sentiment + Negative Sentiment)`
on `[-1,1]` and is blank when the denominator is zero. After every profile
selection Analysis recomputes this value from the selected source-grain
positive and negative totals; it never averages child valences. A profile rerun
therefore changes only Analysis output and never processing artifacts or source
sidecars. RockSteady category counts remain dictionary-derived text indicators,
not diagnoses or direct measurements of emotion.
