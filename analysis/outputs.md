# Analysis Output Files

All reports are written under `analysis/output/<run_folder>/`. Each run
folder contains the files described below. `other_findings/` holds supplementary
outputs that are useful for debugging but not the primary deliverables.

---

## `analysis_profile.json`

Records one reusable Analysis ordering, metadata filter, and grouping choice.
The profile binds to a `source_manifest.json` path and SHA-256 digest, lists
ordered sort fields, an optional automatic metadata grouping field, and manual
groups made from speaker or SourceID members. It never changes
`source_manifest.json` or `source_metadata.csv`, so researchers can produce
multiple postprocessing views of the same source run.

When legacy imported Text is enabled, the profile must keep all visible sources
for a speaker in one output group because that format contributes one
speaker-level observation. Native `video_level_summary.csv` contributes one
verified SourceID observation and permits SourceID splits. Sidecarless legacy Text and iMotions folders are matched exactly
to identities in the authoritative profile manifest. If every selected legacy
folder is sidecarless, choose the procurement run's `source_manifest.json`
explicitly in the desktop **Customize output** screen.

---

## `combined_analysis.xlsx`

The combined workbook separates measures into four direct semantic sections:

- **Emotions:** Audio Anger, Contempt, Disgust, Fear, Joy, Sadness, Surprise,
  Neutral, and Other are `0..100` (source probability `0..1` multiplied by
  100; source `Happiness` becomes Joy). Video Anger, Contempt, Disgust, Fear,
  Joy, Sadness, Surprise, Neutral, and Confusion are `0..100`. The separate
  `Py-Feat / Native Face` provider maps Happy to Joy and Sad to Sadness and
  maps its seven primary-face probabilities to `0..100`; Contempt and
  Confusion remain blank.
- **Sentiment:** Video Sentimentality is `0..100`. Text Positive Sentiment and
  Negative Sentiment are `0..1`. Text imports also accept legacy
  `Positive valence` and `Negative valence` headers, while preferring canonical
  sentiment headers when both are present.
- **Valence:** Audio Valence converts source `0..1` to `-100..100` using
  `(raw * 200) - 100`. Video Valence and Adaptive Valence are `-100..100`.
  Native Face valence and arousal convert source `-1..1` to `-100..100`.
  Text Valence is `(Positive Sentiment - Negative Sentiment) / (Positive
  Sentiment + Negative Sentiment)` on `-1..1` and is blank when its denominator
  is zero. Joy and Valence are never used as Positive/Negative Sentiment proxies.
- **Dimensions:** Audio Arousal and Dominance convert source `0..1` to
  `0..100`. Video Engagement and Adaptive Engagement are `0..100`. Text
  Arousal / Activation, Dominance / Power, and Affiliation / Social
  orientation are `-1..1`.

The **Measure Guide** sheet is non-quantitative and has the columns Section,
Modality, Display measure, Imported source label, Workbook sheet, Output range,
and Transformation/meaning. It states that cross-modality scales are not
directly comparable without rescaling and is not given a probability mirror.
Valid legacy audio reports that lack optional emotion classes show blank cells
plus one warning; new full reports retain all nine audio emotions. Action
units, muscles, and tones remain in detailed/raw outputs rather than this
combined emotional workbook.

Native Face reads only manifest-verified `face_core.csv` rows where
`face_detected=true` and `is_primary_face=true`. No-face rows are missing
observations. Its worksheet name is `Py-Feat - Native Face` because Excel sheet
names cannot contain `/`; the Measure Guide retains the exact provider label
`Py-Feat / Native Face`. Source columns use the actual selected count, including
small, large, and greater-than-twelve profiles.

Native Text summaries are bound to the explicit postprocessing run-root source
sidecars, their exact hashes, catalog digest, ordered source-context hashes,
artifact hash, ordered SourceID set, and identity mapping. The consumer uses
the same bounded manifest/metadata envelope as the catalog producer, so valid
large catalogs are not rejected by a lower Analysis-only ceiling. On profile rerun, Text Valence
is recomputed from the selected positive/negative totals. Neither processing
artifacts nor source sidecars are modified.

---

## `histograms.csv` and `histograms.xlsx`

Frequency distributions of every emotion and affect metric, with one column per
video source and one row per bin. Bins are fixed-width (5 units) and cover the
full scale of each metric type:

- **Core emotions and other 0–100 metrics** — bins from 0 to 100 (20 bins)
- **Valence** — bins from −100 to 100 (40 bins)

The CSV uses section headers to separate metrics. The Excel workbook splits the
same data across three sheets: Core emotions, Other 0-100 findings, and Valence.

A `total` column shows the row sum across all sources.

**What to look for:** The shape of the distribution. Most facial-expression
scores spend the majority of frames near 0 (no expression detected). A source
with a noticeably different shape — heavier tail, earlier peak — is where the
per-source statistical tests will flag differences.

---

## `chi_squared_results.csv`

Pearson chi-squared tests comparing the histogram distributions across video
sources. One block per metric, structured as follows:

### Overall test

```
x_squared,  df,  p_value
```

- **x_squared** — sum of `(observed − expected)² / expected` across all bins
  and sources. Larger values mean the distributions are further from being
  identical.
- **df** — degrees of freedom = `(bins − 1) × (sources − 1)`. Determines which
  chi-squared distribution is used to compute the p-value.
- **p_value** — probability of observing a chi-squared this large or larger if
  all sources came from the same distribution. Values below 0.05 indicate
  significant differences.

### Pairwise matrices

Three source × source matrices covering every pair of videos:

- **Pairwise X-squared matrix** — the chi-squared statistic for each pair.
  Higher values mean a more dissimilar pair.
- **Pairwise df matrix** — usually `bins − 1` (19 for 0-to-100 metrics). A
  value one lower than expected means a bin where both sources had zero counts
  was dropped for that pair.
- **Pairwise p-value matrix** — significance for each pair independently.

### Observed vs expected table

Row-level detail for the overall test:

| Column | Meaning |
|--------|---------|
| `bin_start` | Lower bound of the bin |
| `source` | Video source |
| `observed` | Actual frame count in this bin |
| `expected` | Count predicted if all sources shared the same distribution: `row_total × col_total / grand_total` |
| `observed_minus_expected` | Signed difference; positive means this source has more frames here than expected |
| `pearson_residual` | `(observed − expected) / sqrt(expected)`. Removes the effect of differing sample sizes. Values beyond ±2 are notable; beyond ±5 are strongly anomalous. |

**What to look for:** Large residuals in specific bins point to where a source
deviates from the group pattern — for example, a video that spends unusually
little time in low-anger bins.

---

## `spearman_results.csv`

Spearman rank correlations between every pair of video sources, computed on the
histogram bin counts (not raw frame values). One block per metric, with three
pairwise matrices:

- **Spearman rho matrix** — rank correlation coefficient (−1 to 1). Values near
  1 mean the two sources have similarly shaped distributions.
- **p-value matrix** — significance of each rho via Student's t-distribution.
- **n matrix** — number of bins used for that pair (usually equal to the total
  bin count).

**Chi-squared vs Spearman:** Chi-squared tests whether distributions differ.
Spearman measures how similarly shaped they are. Two sources can differ
significantly on chi-squared while still having a high rho if one is just a
scaled-up version of the other.

---

## `other_findings/descriptor_statistics.csv`

Per-source summary statistics for every numeric column, including structural
columns that do not appear in the histogram outputs. One block per column,
with sources laid out across columns.

| Metric | Meaning |
|--------|---------|
| `count` | Number of rows with a parseable numeric value |
| `missing` | Total rows minus count |
| `mean` | Arithmetic mean of finite values |
| `stddev` | Sample standard deviation (divided by n − 1) |
| `min` / `max` | Minimum and maximum finite values |
| `q1` / `median` / `q3` | 25th, 50th, 75th percentiles via linear interpolation |
| `nonzero_count` | Rows where the value is not exactly zero |
| `nonzero_percent` | `nonzero_count / count × 100` |

**Why nonzero_percent matters:** iMotions facial-expression scores are zero
whenever no face is detected. A column with 95% zeros contributes almost
nothing to the histogram. If `nonzero_percent` is very low for a metric,
treat its distribution statistics with caution.

**Structural columns** (Row, Timestamp, EventSource, SampleNumber, Duration)
appear here but are excluded from histograms and statistical tests. Their
statistics are not analytically meaningful — they are iMotions bookkeeping
fields.

---

## `other_findings/facial_region_correlations.csv`

Pearson correlations between pairs of facial regions, computed per video source
and across all sources combined. Regions are derived by grouping action-unit
columns by anatomical area:

| Region | Columns included |
|--------|-----------------|
| `brow` | Brow Furrow, Brow Raise, Inner Brow Raise |
| `eye` | Eye Closure, Eye Widen, and related eye action units |
| `mouth_lips_jaw` | Jaw Drop, Lip movements, Chin Raise, Dimpler, etc. |
| `cheek_nose` | Cheek Raise, Nose Wrinkle |
| `head_rotation` | Attention and orientation-related outputs |

Each region's time series is the frame-by-frame average of all columns assigned
to that region. Rows where any region has no finite value are excluded from that
pair's correlation.

The file reports `pearson_r` and `n` for each source, plus `all_sources_pearson_r`
and `all_sources_n` computed by pooling all sources together.

**Note:** Per-source correlations can differ substantially from the pooled value
if the sources have different baseline activity levels. A high per-source r with
a near-zero pooled r typically means the regions move together within each
video but not in the same direction across videos.

---

## `other_findings/column_manifest.csv`

A row for every column in every source file, recording how the pipeline
classified it and how many numeric values it contained.

| Column | Meaning |
|--------|---------|
| `classification` | How the column was treated: `emotion_0_to_100`, `other_0_to_100`, `valence_minus100_to_100`, `other_numeric`, `descriptor_only`, or `not_numeric` |
| `numeric_values` | Count of rows the pipeline could parse as a number |
| `channel_identifier` | iMotions internal ID (e.g. `FEA_Emotion_Anger`) |
| `provided_by` | Source module: `Affectiva` for facial expressions, `iMotions` for platform columns |

**Use this file to debug missing columns.** If a metric does not appear in
`histograms.csv`, check here whether it was classified as `descriptor_only` or
`not_numeric`, and whether `numeric_values` is zero.

---

## `other_findings/facial_region_column_map.csv`

Lists every column that was assigned to a facial region, with its region label
and original iMotions metadata. Use this to verify that action-unit columns
were grouped into the expected regions before interpreting
`facial_region_correlations.csv`.
