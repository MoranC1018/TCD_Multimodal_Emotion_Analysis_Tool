# Ranked Construct Comparison Design

## Goal

Restore the compact, grouped `Construct Comparison` layout used by the earlier
combined workbooks, then add per-speaker `Min` and `Max` summaries without
changing the raw Audio, Video/iMotions, or Text source files.

The output must support the political-speaker dataset in two independent
groupings:

1. Country: United Kingdom, France, Poland, and Italy, with three speakers per
   country.
2. Ideology: Left, Centre, and Right, with four speakers per ideology.

Both workbooks use the same 60 source recordings: 12 speakers with five
recordings each.

## Comparison layout

Each speaker keeps the existing four-column source table:

1. Psychological construct
2. Face / Video
3. Audio
4. Text

After that table, reserve four columns before the next speaker:

1. blank visual gutter
2. `Min`
3. `Max`
4. blank visual gutter

The final speaker in a row also receives the same four-column suffix so every
speaker has its own `Min` and `Max` output.

The Face, Audio, and Text cells remain multiline boxes. Each line contains one
classified measure and its score. The comparison sheet uses `Face` as the
display name for the workbook's Video modality because these political-speaker
inputs are iMotions facial outputs.

## Construct classification

Action Units are excluded. Every canonical core emotion and every canonical
Text output is assigned to a comparison box. Other non-Action-Unit dimensions
already exposed by the combined workbook are retained as well.

| Box | Face / Video measures | Audio measures | Text measures |
| --- | --- | --- | --- |
| Positive Sentiment | Joy | Joy | Positive Sentiment |
| Negative Sentiment | Anger; Contempt; Disgust; Fear; Sadness | Anger; Contempt; Disgust; Fear; Sadness | Negative Sentiment |
| Neutral / Other | Neutral; Confusion; Sentimentality | Neutral; Other | none |
| Arousal / Activation | Surprise; Arousal; Engagement; Adaptive Engagement | Surprise; Arousal | Arousal / Activation |
| Valence | Valence; Adaptive Valence | Valence | Text Valence |
| Dominance / Power | none | Dominance | Dominance / Power |
| Affiliation / Social orientation | none | none | Affiliation / Social orientation |

These seven rows assign all 15 canonical Video measures, all 12 canonical Audio
measures, and all six canonical Text measures exactly once. Missing provider
outputs are omitted from a multiline box. A modality with no assigned or
available measure remains blank and is excluded from extrema ranking. Numeric
zero is an available score and must not be hidden.

## Text scaling

The imported political-speaker Text values used for the speaker-level workbook
are all between 0 and 1. Postprocessing multiplies every imported Text construct
by 100 before writing the `Text sentiment` sheet. The comparison boxes and
`Min`/`Max` summaries therefore use those scaled values.

The source Text CSV files are immutable. The scale conversion happens only in
the combined-workbook postprocessor. If a future signed Text input is negative,
the same multiplication preserves its sign (for example, `-0.25` becomes
`-25.00`).

## Min and Max rules

For each speaker and each construct row:

1. Parse the numeric candidates already represented in the Face, Audio, and
   Text boxes.
2. `Min` selects the lowest available score inside each modality box.
3. `Max` selects the highest available score inside each modality box.
4. Rank the resulting modality selections from highest score to lowest score.
5. Render one line per available modality as
   `<Modality>: <Measure> <score>`, with two decimal places.
6. Break equal-score ties deterministically in Face, Audio, Text order.

Example for the Positive Sentiment row:

- Face contains `Joy: 18.75`.
- Audio contains `Joy: 44.49`.
- Text contains `Positive Sentiment: 4.00` after scaling.
- `Min` becomes `Audio: Joy 44.49`, `Face: Joy 18.75`, `Text: Positive
  Sentiment 4.00` because each modality has one assigned candidate.
- `Max` becomes `Audio: Joy 44.49`, `Face: Joy 18.75`, `Text: Positive
  Sentiment 4.00`.

Valence is evaluated separately in the following row after Arousal /
Activation. It contains Face Valence and Adaptive Valence, Audio Valence, and
Text Valence.

## Formula and provenance behavior

The three modality boxes remain formula-linked to their corresponding source
sheets. The ranked summaries are generated deterministically from the same
speaker-level numeric cells, avoiding dependence on parsing displayed Excel
text. Workbook calculation-on-open remains enabled.

The Measure Guide documents the Text `x100` postprocessing transformation and
the comparison-sheet ranking contract. No source processing artifacts are
overwritten.

## Validation

Automated tests must prove:

- the original four-column grouped boxes are present;
- all 15 canonical Video measures, all 12 canonical Audio measures, and all six
  canonical Text constructs appear in exactly one classification row;
- the four-column inter-speaker layout has blank outer gutters and populated
  `Min`/`Max` middle columns;
- Text values are multiplied by 100 in the combined workbook;
- `Min` and `Max` select the correct per-modality extreme and sort the three
  selections high-to-low;
- unavailable metrics are absent from speaker boxes and do not enter rankings;
- the comparison sheet can still be disabled;
- all 60 iMotions, Audio, and Text inputs are represented in both final runs;
- both final workbooks contain no formula errors and render legibly.
