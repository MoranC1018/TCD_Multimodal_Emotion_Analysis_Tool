# Analysis

Analysis is split into source-specific feeders and one shared report
engine:

- `imotions.py` discovers/parses iMotions face CSV exports.
- `audio.py` discovers/parses audio `audio_analysis.csv` outputs.
- `text.py` splits and analyses RockSteady text-emotion CSV exports.
- `histograms.py` owns the shared data classes, histogram normalization,
  descriptive statistics, Spearman, chi-squared, and report writers for all
  sources.

These reports contain measurements and statistical summaries, not diagnoses or
direct observations of a person's internal state. Interpretation and any
resulting action remain the researcher's responsibility.

## Stable Workflow And Expert Entry Points

Use the provider-neutral workflow CLI for coordinated Analysis runs. A Video
source may be an iMotions/AFFDEX export or a verified Py-Feat native Face run;
the workflow detects which provider is present before creating, archiving, or
publishing anything in the output directory:

```bash
python -m analysis.workflow \
  --output-root OUTPUT_FOLDER \
  --video-source VIDEO_FOLDER --video-method run \
  --audio-source AUDIO_FOLDER --audio-method import
```

Use `--video-method run` for provider source data that still needs statistical
Analysis and `--video-method import` for an existing Analysis report tree.
`--imotions-source` / `--imotions-method` and `--native_face-source` /
`--native_face-method` remain deprecated compatibility aliases for one release.
They normalize to the same single Video request and print a deprecation warning.
Do not combine canonical flags with an alias or supply both provider aliases.

The documented command-line layers are:

```bash
python -m processing.face_analysis --help
python -m processing.text_analysis --help
python processing/audio_analysis/run_audio_analysis.py --help
python -m analysis.imotions --help
python -m analysis.native_face --help
python -m analysis.audio --help
python -m analysis.workflow --help
```

The three `analysis.<provider>` commands remain available as lower-level expert
tools. `analysis.workflow` is the stable coordinated interface and exposes only
the modality names `video`, `audio`, and `text` in its normalized request and
manifest.

For the calculation details behind each generated file, including
chi-squared expected counts, the pairwise df matrix, Spearman matrices,
descriptive statistics, and logscale histograms, see
[`CALCULATIONS.md`](CALCULATIONS.md).

Reports are separated first by analysis domain:

- `analysis/output/emotion/` for core emotion scores, valence, and audio
  emotion/affect model outputs.
- `analysis/output/raw/` for action units, head rotation, geometry,
  timing descriptors, and raw OpenSMILE acoustic feature reports.

Inside each analysis domain, outputs stay separated by speaker. Each speaker has
one folder per video plus a `combined/` folder that runs the same report format
over all videos for that speaker.

## iMotions Face Outputs

Use this step after iMotions has exported CSV files for a speaker, video set, or
analysis run:

```bash
python -m analysis.imotions SPEAKER_OR_RUN_FOLDER
```

The script looks for that folder inside `analysis/iMotions_Output/`.
You can also pass a full path. Reports are written to
`analysis/output/emotion/` and `analysis/output/raw/` by default.

For a face input folder called `Speaker_A`, the output is:

```text
analysis/output/emotion/Speaker_A/
  001_First_Video/
  002_Second_Video/
  combined/
analysis/output/raw/Speaker_A/
  001_First_Video/
  002_Second_Video/
  combined/
```

Each video folder and the `combined/` folder contain the same report files.

Main outputs:

- `histograms.csv` - one sectioned CSV with core emotions, other 0-100
  findings, and valence.
- `histograms.xlsx` - the same histogram report split across workbook sheets.
- `chi_squared_results.csv` and `spearman_results.csv` - comparison tables
  across the videos in the folder.
- `other_findings/descriptive_statistics.csv` - descriptive metrics, including
  kurtosis, laid out so each row can compare the same measure across videos.
- `other_findings/facial_region_correlations.csv` - grouped facial-region
  correlations across videos.
- `other_findings/histogram_graphs/` - SVG histogram graphs.

Add `--logscale` if large count differences make the normal histogram graphs
hard to read. This writes `other_findings/logscale_histograms.csv` and matching
SVG graphs in `other_findings/logscale_histogram_graphs/`.

Useful options:

```bash
python -m analysis.imotions INPUT_FOLDER --output-root SOME_OTHER_FOLDER
python -m analysis.imotions INPUT_FOLDER --no-graphs
python -m analysis.imotions INPUT_FOLDER --logscale
```

Generated CSV, XLSX, SVG, and iMotions input/output folders are ignored by git.

## Audio Outputs

Use this step after `processing/audio_analysis` has written `audio_analysis.csv`
and/or `opensmile_features.csv` files:

```bash
python -m analysis.audio AUDIO_RUN_FOLDER
```

The audio handler accepts either a full path to an audio output folder or a
folder name under `analysis/audio_outputs/`. It converts per-window audio
model outputs into the shared analysis table shape, then writes those
reports under `analysis/output/emotion/`. Raw OpenSMILE feature tables
are parsed as acoustic descriptor reports under `analysis/output/raw/`.

For an audio extraction run containing videos for two example speakers, the
analysis layout is:

```text
analysis/output/emotion/<audio-run-name>/
  Speaker_A/
    <video_1>/
    <video_2>/
    combined/
  Speaker_B/
    <video_1>/
    <video_2>/
    combined/
```

The original audio extraction outputs remain unchanged in
`processing/audio_analysis/output/`; this step only creates analysis
reports from those files.

Audio categorical probabilities are table-normalized to 0-100 bins for:

```text
Anger, Contempt, Disgust, Fear, Joy, Sadness, Surprise, Neutral, Other
```

Audio dimensional affect outputs are kept as audio-derived measures and are not
treated as iMotions facial-expression readings.

## Combined Workbook Measure Contract

The combined workbook and its **Measure Guide** use four explicit sections:

- **Emotions:** Audio Anger, Contempt, Disgust, Fear, Joy, Sadness, Surprise,
  Neutral, and Other are `0..100`; source probabilities are multiplied by 100
  and source `Happiness` is displayed as Joy. Video Anger, Contempt, Disgust,
  Fear, Joy, Sadness, Surprise, Neutral, and Confusion are `0..100`.
- **Sentiment:** Video Sentimentality is `0..100`. Text Positive Sentiment and
  Negative Sentiment are imported on `0..1` and multiplied by `100` for the
  combined workbook. Legacy imported headers `Positive valence`
  and `Negative valence` remain accepted aliases, but canonical sentiment
  headers win when both versions exist.
- **Valence:** Audio Valence maps source `0..1` to output `-100..100` with
  `(raw * 200) - 100`. Video Valence and Adaptive Valence are `-100..100`.
  Text Valence is derived on source scale `-1..1` and multiplied by `100` for
  combined-workbook scale `-100..100`. Joy and Valence are not
  Positive/Negative Sentiment proxies.
- **Dimensions:** Audio Arousal and Dominance map source `0..1` to `0..100`.
  Video Engagement and Adaptive Engagement are `0..100`. Text Arousal /
  Activation, Dominance / Power, and Affiliation / Social orientation are
  imported on `-1..1` and multiplied by `100` in the combined workbook;
  signed values retain their sign.

Numeric ranges overlap after Text `x100` scaling, but the modality constructs
are not calibrated equivalents. The
Measure Guide columns are Section, Modality, Display measure, Imported source
label, Workbook sheet, Output range, and Transformation/meaning. Audio rows and
guide entries are created only for measures with a numeric observation among
the selected speakers. A speaker's unavailable optional Audio emotions are
omitted, while numeric zero remains a valid displayed score. Newly generated
full reports retain all nine emotions. Action units, muscles, and tones stay in
detailed/raw reports and are outside the combined emotional workbook.

The **Construct Comparison** sheet uses seven ordered heuristic construct
families: Positive Sentiment, Negative Sentiment, Neutral / Other, Arousal /
Activation, Valence, Dominance / Power, and Affiliation / Social orientation.
Its taxonomy assigns all 15 canonical Video measures, all 12 Audio measures,
and all six Text measures exactly once while excluding Action Units. Every
speaker keeps multiline Face, Audio, and Text boxes. A four-column suffix adds
blank, `Min`, `Max`, blank: Min/Max select the per-modality internal extreme
and rank the resulting modality values high-to-low, using Face, Audio, Text tie
order. Missing/no-direct boxes are blank and excluded, and the rankings are
descriptive raw-score extrema only.

## Reusable Output Customization

The desktop application's **Customize output** screen reads the paired
`source_manifest.json` and `source_metadata.csv` from a procurement run. It can
order sources by any declared metadata fields, hide selected metadata values,
automatically group by one field, and create manual groups containing whole
speakers or individual SourceIDs. A SourceID can resolve into only one manual
group. If Text is included, every visible source for a speaker must resolve to
one output group because the imported Text summary has speaker-level rather
than source-level observations.

Metadata values are matched exactly after surrounding whitespace is removed;
capitalization remains meaningful for sorting, filtering, and grouping.

Each Analysis output stores the choices in `analysis_profile.json`, including
the source-manifest path and SHA-256 digest. This file is separate from the
source sidecars: rerunning postprocessing with a different profile creates a
different ordering/grouping without modifying procurement provenance. Previous
fixed-name workbooks, manifests, and profiles are archived together when the
same output directory is reused. A failed run is quarantined under the same
reparse-checked history directory so a corrected run can be retried normally.
Sidecarless legacy Text and iMotions exports remain usable when their exact
speaker, SourceID, title, or output-folder identities map unambiguously to the
profile's authoritative procurement manifest. When every selected legacy
result folder is sidecarless, choose that procurement `source_manifest.json`
explicitly in **Customize output** before loading source metadata.

## RockSteady Text-Emotion Outputs

`text.py` has two subcommands: `split` (split a combined export by speaker)
and `analyse` (run histogram and stats reports on per-speaker CSVs).

### Step 1 - Split a combined export by speaker

RockSteady typically produces one combined CSV for all speeches. Split it into
one file per speaker using the `rocksteady_input/` folder as a reference:

```bash
python -m analysis.text split \
    --input  processing/text_analysis/parse_output/output_percentage.csv \
    --reference processing/text_analysis/prepare_input/rocksteady_input \
    --output-dir analysis/text_output/MY_RUN
```

The reference folder must have one subdirectory per speaker, each containing
the speech `.txt` files used as RockSteady input. The script matches rows by
title stem and writes one `<Speaker>.csv` per speaker. Unmatched rows go to
`unmatched.csv`.

### Step 2 - Analyse per-speaker CSVs

```bash
python -m analysis.text analyse analysis/text_output/MY_RUN
```

Reports are written to `analysis/output/MY_RUN/`. Each CSV file in the
input folder is treated as one source (one speaker).

RockSteady must be run in **Percentage** output mode. Emotion columns (Anger,
Disgust, Fear, Joy, Sadness, Surprise) are histogrammed as core emotions
(0-100). Sentiment columns (Positive, Negative) appear under "Other 0-100
findings".

Useful options:

```bash
python -m analysis.text analyse FOLDER --output-root SOME_OTHER_FOLDER
python -m analysis.text analyse FOLDER --no-graphs
python -m analysis.text analyse FOLDER --logscale
```
