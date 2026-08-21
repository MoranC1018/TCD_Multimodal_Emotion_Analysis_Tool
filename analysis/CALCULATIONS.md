# Analysis Calculations

This document explains what the analysis reports contain and how the
numbers are calculated. The source-specific scripts, `imotions.py`,
`native_face.py`, and `audio.py`, find and parse their own input files. The shared calculation engine
is `histograms.py`, so face and audio reports use the same histogram,
descriptor, chi-squared, Spearman, and graph logic once the inputs have been
converted into the common table format.

## Folder Flow

iMotions face inputs are read from:

```text
analysis/iMotions_Output/<run-or-speaker-folder>/
```

Audio inputs are read from:

```text
analysis/audio_outputs/<run-folder>/
```

Native Face inputs are read from a processing run root containing verified
`run_manifest.json`, `run_index.csv`, per-video `face_core.csv` and
`video_manifest.json`, plus the exact source sidecars for catalog runs. Native
Text prefers its manifest-bound SourceID-grain `video_level_summary.csv`;
legacy `speaker_level_summary.csv` remains supported.

Reports are written under:

```text
analysis/output/emotion/<input-folder>/
analysis/output/raw/<input-folder>/
```

The report engine first splits parsed columns into two parent folders.
`emotion/` contains core emotion, valence, and audio affect model outputs.
`raw/` contains action units, head movement, geometry, timing descriptors, and
raw OpenSMILE acoustic feature reports. Inside each parent folder, files are
grouped by speaker. For each speaker it writes one report folder per video and
one `combined/` folder. Single-video folders are useful for histograms, graphs,
manifests, and descriptive statistics. Comparison reports such as chi-squared
and Spearman are meaningful when a folder contains at least two sources,
usually in `combined/`.

Each report folder can contain:

- `histograms.csv` and `histograms.xlsx`
- `chi_squared_results.csv`
- `spearman_results.csv`
- `other_findings/descriptive_statistics.csv`
- `other_findings/column_manifest.csv`
- `other_findings/facial_region_column_map.csv`
- `other_findings/facial_region_correlations.csv`
- `other_findings/run_log.txt`
- `other_findings/histogram_graphs/*.svg`
- Optional `other_findings/logscale_histograms.csv` and
  `other_findings/logscale_histogram_graphs/*.svg`

## Input Parsing

iMotions CSVs can contain metadata before the data table. The parser looks for
the real header at `Row,Timestamp`, either after `#DATA` or directly in the
file. Data rows stop at the first blank row, which avoids reading summary
tables appended below the export.

When a folder contains CSVs directly, those direct files are analysed. If there
are no direct CSVs, the parser searches recursively so run folders such as
`DemoDay/<speaker>/Sensor Data/*.csv` can be handled.

Duplicate re-exports are deduplicated by source label. For example,
`005_April 2022 April 24 2026.csv` and `005_April 2022.csv` collapse to the
same source label, and the larger file is kept.

Audio `audio_analysis.csv` files are converted into the same table shape as
iMotions exports. Audio categorical probabilities are multiplied by 100, and
audio valence is mapped from `0..1` to `-100..100` using:

```text
signed_valence = (raw_valence * 200) - 100
```

Native Face input is accepted only when the core CSV hash and manifest binding
verify. Rows contribute only when `face_detected=true` and
`is_primary_face=true`; explicit no-face samples are missing observations.
Happy maps to Joy, Sad maps to Sadness, and the other five supported emotions
map directly. Contempt and Confusion are unsupported blanks.

Native Text validates the summary artifact hash, run-root sidecars, exact
SourceID coverage, and identity alignment. SourceID-grain profiles may split a
speaker; legacy speaker-grain Text may not.

## Column Classification

Each numeric column is classified before histogramming:

- `emotion_0_to_100`: core emotion scores such as Anger, Joy, Fear, Sadness,
  Surprise, Contempt, and Disgust.
- `other_0_to_100`: other score-like measures in the 0-100 range, such as
  action units or audio dimensional measures.
- `valence_minus100_to_100`: valence-like columns.
- `other_numeric`: numeric values that are not score-like. These are kept for
  descriptive statistics, but are not included in the main histogram report.
- `descriptor_only`: structural, timing, counter, raw landmark, or optionally
  excluded geometry columns. These are kept for descriptive statistics only.

By default, structural timing columns and raw landmark feature columns are
excluded from histograms. Use `--include-timing` or `--include-landmarks` if
those should be histogrammed. Use `--exclude-geometry` to keep geometry columns
out of histogram output.

## Scaling Rules

The code keeps provider-specific face-score scale contracts separate:

- Core iMotions face emotions are allowed to auto-scale from `0..1` to
  `0..100` when the raw CSV values are in that range.
- iMotions valence is kept on `-100..100`. If raw valence is `-1..1`, it is
  multiplied by 100.
- Other iMotions FEA index columns that already have unit `Index` are treated
  as `0..100` and are not auto-scaled again.
- Native Py-Feat probabilities are multiplied from `0..1` to `0..100`.
- Native Py-Feat valence and arousal are multiplied from `-1..1` to
  `-100..100`.

Audio probabilities are converted before they reach the shared engine:
categorical emotion probabilities become `0..100`, and audio valence becomes
`-100..100`.

## Combined Workbook Semantic Sections

The combined workbook does not collapse distinct constructs merely because
their labels or signs look similar. Its four direct-mapping sections are:

- **Emotions:** Audio Anger, Contempt, Disgust, Fear, Joy, Sadness, Surprise,
  Neutral, and Other use `0..100`, calculated as source probability `* 100`
  (`Happiness` is the imported source label for Joy). Video Anger, Contempt,
  Disgust, Fear, Joy, Sadness, Surprise, Neutral, and Confusion use `0..100`.
  The distinct `Py-Feat / Native Face` provider contributes its seven mapped
  primary-face probabilities on `0..100`; it is never labelled AFFDEX.
- **Sentiment:** Video Sentimentality uses `0..100`. Text Positive Sentiment
  and Negative Sentiment use `0..1`. `Positive valence` and `Negative valence`
  are legacy text-header aliases only; canonical sentiment headers take
  precedence when both are present.
- **Valence:** Audio Valence uses `(raw * 200) - 100` from source `0..1` to
  output `-100..100`. Video Valence and Adaptive Valence use `-100..100`.
  Native Face valence and arousal use `-100..100`. Text Valence uses
  `(Positive Sentiment - Negative Sentiment) / (Positive Sentiment + Negative Sentiment)`
  on `-1..1` and is blank when the denominator is zero. Neither Joy nor
  Valence is used as a Positive/Negative Sentiment proxy.
- **Dimensions:** Audio Arousal and Dominance use source probability `* 100`
  and output `0..100`. Video Engagement and Adaptive Engagement use
  `0..100`. Text Arousal / Activation, Dominance / Power, and Affiliation /
  Social orientation use `-1..1`.

Cross-modality scales are not directly comparable without rescaling. The
non-quantitative **Measure Guide** is generated from these same ordered metric
constants and records Section, Modality, Display measure, Imported source
label, Workbook sheet, Output range, and Transformation/meaning. Missing
optional classes in valid legacy audio reports remain blank with one warning;
full new reports retain all nine audio emotions. Action units, muscles, and
tones are deliberately outside the combined emotional workbook.

For a native Text profile, Text Valence is recomputed from the selected
SourceID positive and negative totals. Averaging per-source valences would give
different weights and is deliberately not used. Repeated profile runs only
write new Analysis outputs; processing summaries and source sidecars remain
byte-identical. Native Face workbook columns use the actual selected source
count, with no fixed participant count.

## Histograms

`histograms.csv` is divided into three sections:

- Core emotions `(0-100)`
- Other `0-100` findings
- Valence `(-100 to 100)`

Each statistic has one table. Rows are bins, columns are sources, and `total`
is the row total across sources.

For 0-100 values, bins are 5-point intervals:

```text
0-5, 5-10, 10-15, ..., 95-100
```

For valence, bins are also 5-point intervals:

```text
-100--95, -95--90, ..., 95-100
```

The stored `bin_start` is the left edge of the bin, and `bin_end` is
`bin_start + 5`. A value exactly at the upper endpoint goes into the final bin,
so `100` goes into `95-100`. Values outside the fixed range are ignored for
that histogram. Empty bins remain in the table so every video has the same
visible range.

`histograms.xlsx` mirrors the same layout as the CSV, split into workbook
sheets for the three histogram sections.

## Logscale Histograms

`--logscale` is opt-in. When used, the main histogram report stays unchanged.
The script additionally writes:

```text
other_findings/logscale_histograms.csv
other_findings/logscale_histogram_graphs/*.svg
```

Each count is transformed as:

```text
log10(count + 1)
```

The `+ 1` keeps zero-count bins at zero and avoids taking a logarithm of zero.
The logscale `total` is `log10(sum(row_counts) + 1)`.

## Descriptive Statistics

`other_findings/descriptive_statistics.csv` contains every numeric descriptor,
including columns that are not histogrammed. The layout is comparison-first:
each statistic appears once, then each metric is shown across the sources.

For each source and descriptor:

- `count`: number of finite numeric values.
- `missing`: number of data rows minus `count`.
- `mean`: arithmetic mean.
- `stddev`: sample standard deviation using denominator `n - 1`; if `n = 1`,
  this is `0`.
- `min` and `max`: smallest and largest finite values.
- `q1`, `median`, `q3`: linear-interpolated percentiles at 25%, 50%, and 75%.
- `kurtosis`: population excess kurtosis, calculated as
  `mean((x - mean)^4) / variance^2 - 3`; constant descriptors are written as
  `0`.
- `nonzero_count`: count of finite values not equal to zero.
- `nonzero_percent`: `nonzero_count / count * 100`.

Report numbers are formatted to at most two decimal places. Integers stay as
integers, `NaN` is written as `NA`, and infinite values are written as `Inf` or
`-Inf`.

## Facial Region Correlations

`other_findings/column_manifest.csv` records the parsed columns for each source:
original source file, original column name, display statistic name,
classification, metadata category/group/unit, number of numeric values,
provider/channel metadata, scale hint, and description.

`other_findings/facial_region_column_map.csv` records which columns were placed
into which facial region. Regions are keyword-based:

```text
brow
eye
mouth_lips_jaw
cheek_nose
head_rotation
```

For each row of a source CSV, the region score is the mean of all finite values
from columns mapped to that region. If no mapped column has a finite value for
that row, the region score is blank for that row.

`other_findings/facial_region_correlations.csv` then calculates Pearson
correlations between every active pair of regions. For each pair:

- `n`: number of rows where both regions have finite values.
- `pearson_r`: Pearson correlation between the two region score series.

The file also includes `all_sources_pearson_r` and `all_sources_n`, calculated
by concatenating each region's row-level values across all sources and then
running the same Pearson calculation.

`other_findings/run_log.txt` is a rerun audit trail. It records the input and
output folders, selected CSVs, skipped duplicates, report counts, graph counts,
and whether logscale was enabled.

## Chi-squared Results

`chi_squared_results.csv` is calculated from the histogram count tables. Each
statistic is treated as a contingency table:

```text
rows = non-empty bins
columns = sources
cell = observed count for that bin and source
```

Bins where the row total is zero are removed before the chi-squared test. This
is important for the degrees of freedom.

For each remaining bin and source:

```text
expected = (bin_row_total * source_column_total) / grand_total
pearson_residual = (observed - expected) / sqrt(expected)
```

The overall Pearson chi-squared statistic is:

```text
x_squared = sum(pearson_residual^2)
```

The overall degrees of freedom are:

```text
df = (number_of_non_empty_bins - 1) * (number_of_sources - 1)
```

The p-value is the chi-square survival probability:

```text
p_value = Q(df / 2, x_squared / 2)
```

where `Q` is the regularized upper incomplete gamma function implemented in the
code.

The `Observed vs expected` section writes the details behind the overall test:

- `observed`: the actual histogram count.
- `expected`: the count expected under independence.
- `observed_minus_expected`: `observed - expected`.
- `pearson_residual`: the standardized contribution for that cell.

## Pairwise Chi-squared Matrices

The pairwise matrices answer: "If I compare only video/source A against
video/source B for this one statistic, what is the chi-squared result?"

For each pair of sources, the code builds a two-column contingency table:

```text
rows = bins where source A count + source B count > 0
columns = source A and source B
```

Then it runs the same chi-squared calculation described above.

This means the pairwise degrees of freedom are:

```text
pairwise_df = (number_of_non_empty_bins_for_that_pair - 1) * (2 - 1)
            = number_of_non_empty_bins_for_that_pair - 1
```

That is why the `Pairwise df matrix` can vary from cell to cell. If one pair
has counts in 19 bins, its df is `18`. If another pair has counts in all 20
bins, its df is `19`. The diagonal is blank because a source is not compared
against itself.

The pairwise matrix sections are:

- `Pairwise X-squared matrix`: the chi-squared statistic for each two-source
  comparison.
- `Pairwise df matrix`: the degrees of freedom for each two-source comparison.
- `Pairwise p-value matrix`: the chi-square p-value for each two-source
  comparison.

## Spearman Results

`spearman_results.csv` compares the shapes of two source histograms. For each
statistic and source pair:

1. Take the histogram count vector for source A.
2. Take the histogram count vector for source B.
3. Rank each vector, using average ranks for ties.
4. Calculate Pearson correlation between the two rank vectors.

That Pearson correlation of ranks is Spearman's rho.

The file includes:

- `Spearman rho matrix`: rho for each source pair.
- `Spearman p-value matrix`: two-tailed p-value from the t approximation.
- `Spearman n matrix`: number of bins in the ranked vectors.

The code also calculates:

```text
S = (1 - rho) * n * (n^2 - 1) / 6
```

For the p-value, if `|rho|` is less than 1:

```text
df = n - 2
t = abs(rho) * sqrt(df / (1 - rho^2))
p_value = two_tailed_student_t_p(t, df)
```

If `|rho|` is exactly 1, the p-value is written as `0`.

Unlike pairwise chi-squared, Spearman uses the displayed histogram bin vectors
for the statistic. This is meant to compare the overall distribution shape,
including bins where both sources may have zero counts.

## Graphs

`other_findings/histogram_graphs/*.svg` renders the same histogram tables as
grouped bar charts. The y-axis is linear by default. With `--logscale`, the
additional graph folder uses `log10(count + 1)` for bar height. Tooltips still
show the original count.

## Output Precision

The report writer caps non-integer numeric values at two decimal places to keep
CSV files readable. Very small p-values are kept in compact scientific
notation, and values smaller than `2.2e-16` are shown as `< 2.2e-16`.
