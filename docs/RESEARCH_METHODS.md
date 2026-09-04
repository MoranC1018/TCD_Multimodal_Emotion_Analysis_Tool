# Research Methods And Reproducibility

## Document Purpose

This document describes the implemented Multimodal Emotion Analysis Tool
as a research instrument. It distinguishes source selection, machine-generated
measurements, statistical transformations, and interpretation. It should be
read with:

- `analysis/CALCULATIONS.md` for exact report formulas;
- `processing/audio_analysis/README.md` for the audio schema and models;
- `procurement/procurement_beta/SETUP.md` for Clean speaker confidence rules;
- `procurement/procurement_beta/THIRD_PARTY_NOTICES.md` for licences and
  upstream methods; and
- `../THIRD_PARTY_NOTICES.md` for the project-wide licence boundary and bundled
  OpenSMILE provenance.

The software does not establish that a person experienced a particular emotion.
It records model outputs and observable acoustic/facial descriptors that may be
analysed under an approved study design. Interpretation and any resulting
action remain the researcher's responsibility; this is not a diagnostic system.

## Study Unit And Data Flow

The primary unit is a source video associated with a speaker. Speaker folder
structure is retained through Procurement and Processing. Analysis writes both
per-video reports and a combined report for each speaker.

```text
Source record
  -> metadata and licence review
  -> selected media intervals
  -> face/audio/text processing or import
  -> common numeric table
  -> per-video and within-speaker combined reports
```

Cross-speaker aggregation is not performed implicitly. Researchers should
define any cross-speaker comparison, exclusion, weighting, and repeated-measure
model explicitly outside the launcher.

## Procurement Inputs

The source resolver accepts:

- one direct YouTube URL;
- a recursive local folder containing MP4, MOV, MKV, WebM, or AVI;
- a CSV or DOCX catalog containing a required `Link` column;
- one local video in a supported container.

For folder input, the relative subfolder structure is retained. CSV and DOCX
catalogs use the same ordered row model: stable SourceIDs distinguish repeated
links, relative local links resolve from the catalog directory, optional
`Speaker` alone controls grouping, and every other nonignored nonblank field is
user metadata. Blank speakers are pooled without inventing a speaker identity.
DOCX tables without a normalized `Link` header are skipped as unrelated
document content; valid Link-bearing tables retain their document order.
For a direct URL, the canonical YouTube video identifier is retained as
provenance.

Catalog selection is explicit and independent of metadata filters or sorting.
Before processing, the run seals `source_manifest.json` and
`source_metadata.csv`, recording the exact catalog digest, selection, options,
source identity, user metadata, and output mapping. The JSON retains raw
metadata; the CSV is spreadsheet-safe. Researcher-supplied `Language` is not
overwritten by YouTube metadata. The separate YouTube language field uses API
`defaultAudioLanguage`, then `defaultLanguage`, else blank.
The audio batch screen reopens the sealed manifest in the chosen input folder,
can apply its metadata visibility/sort controls, and binds the selected
SourceIDs plus catalog digest back to that folder. Pooled audio reports retain
a blank raw source-speaker field but use `Pooled (no speaker)` as the
analysis-facing display label.

Selected local media is streamed once into a temporary snapshot. The SHA-256
and byte count recorded in the manifest and per-source context describe that
snapshot-the bytes actually supplied to Procurement-not a later reopening of a
mutable original path. Clean-speaker processing revalidates that snapshot's
digest and byte count immediately before use. Its successful catalog result is
atomically copied from the private reusable cache to `stitched_imotions.mp4`
beside the source context, so downstream audio discovery retains the same
SourceID and manifest binding while private cache files remain excluded.

### YouTube Metadata

Metadata is resolved in this order:

1. YouTube Data API when a configured API key is available.
2. Public YouTube oEmbed for title and thumbnail fallback.
3. `yt-dlp` metadata for a direct URL when title or duration is still absent.

The review record can contain title, duration, upload date, thumbnail, and
licence. Missing metadata is represented as unknown rather than inferred.
Researchers should archive the generated manifest because online metadata may
change after collection.

### Standard Sample

Standard sampling targets a user-defined percentage of source duration,
default 10%. A maximum clip length, default 30 seconds, constrains each selected
interval. Local intervals are non-overlapping. The final interval can be
shorter to meet the requested duration.

Random or percentage sampling changes the estimand: the result represents the
sampling design, not the complete speech. The percentage, segment cap, random
seed where applicable, source duration, and selected intervals should be
reported.

### Full Video

Full mode preserves the complete local source or retrieves the complete online
source. It is appropriate only where the researcher has the necessary rights
and storage. No inference about licence permission is made from mode selection.

### Focus

Focus stores researcher-selected closed-open time intervals in seconds. The
interface accepts seconds, `MM:SS`, or `HH:MM:SS` and normalizes them to numeric
seconds.

For each source:

1. Each selected interval is encoded to H.264 video and AAC audio.
2. If `gap_seconds > 0`, a black video/silent audio clip is generated using the
   first selected clip's width, height, frame rate, sample rate, and channel
   layout.
3. Selected clips and gaps are concatenated in selection order.
4. The source path/URL, interval list, gap duration, and output path are written
   to a manifest.

A zero gap inserts no extra media. Container duration may differ from arithmetic
duration by a frame or audio-packet boundary.

### Clean Speaker Segments

The Clean speaker mode attempts to identify intervals where the target face is visible and
the dominant voice is active.

Face evidence uses OpenCV-based detection/recognition when the required models
are installed. Candidate frames are evaluated for identity, confidence, face
size, centrality, sharpness, and diversity. Strict rejection of audience,
projection-screen, multiple-face, and no-face frames intentionally favours
precision over recall.

Voice evidence uses diarization or speaker embeddings when configured. A
low-confidence audio-activity fallback is diagnostic only and cannot pass the
clean-overlap gate. Face and voice intervals are intersected, filtered by the
configured minimum duration/confidence, and recorded with accepted/rejected
reasons.

This mode is experimental. Identity drift, ageing, pose, occlusion, dubbing,
cross-talk, applause, music, poor microphones, and editing can all alter error
rates. A study using beta outputs should manually audit a prespecified sample
and report false-positive/false-negative estimates.

## Audio Processing

The audio stage analyses MP4 files or a recursive MP4 folder. It preserves
speaker/video structure and writes:

```text
audio_analysis.csv
opensmile_features.csv
audio_analysis_manifest.json
```

When catalog provenance is present, every audio input must bind one-to-one to
a selected manifest row through its immutable `source_context.json`. SourceID,
raw Speaker, user metadata, researcher Language, and YouTube language are
carried into audio metadata and manifests. The top catalog JSON/CSV sidecars
are propagated byte-identically into audio and full-stack output roots so later
analysis can audit source selection without reconstructing it from folder
names.

`audio_analysis.csv` contains one row per configured analysis window. Window
duration and stride are explicit run parameters. Overlapping windows are not
independent observations and must not be treated as independent replicates in
inferential statistics.

### Acoustic Features

The bundled OpenSMILE 3.0.0 distribution (revision `e882501`) produces numeric
acoustic descriptors. The standard feature set is eGeMAPS; ComParE 2016 can be
selected for a larger descriptor space. Feature definitions, extraction
configuration, version, and revision should be reported. OpenSMILE is excluded
from the project's MIT License and remains under the audEERING Research
License. Its complete local `LICENSE` and `licenses/` tree must be retained;
see `../THIRD_PARTY_NOTICES.md` for the non-commercial boundary, upstream
source, and required citation.

Raw features are preserved in `opensmile_features.csv` so downstream analyses
can be audited independently of emotion-model outputs.

### Emotion Model Outputs

The configured categorical model produces probabilities for:

```text
Anger, Contempt, Disgust, Fear, Happiness, Neutral, Sadness, Surprise, Other
```

The configured dimensional model produces Arousal, Dominance, and Valence
scores. The main research output does not silently substitute a fallback
categorical model. If the preferred model cannot load, fields remain blank and
the manifest records the error. Debug fallback output is separate.

Model probabilities are estimates learned from their training domains. They
may be affected by language, accent, microphone, compression, room acoustics,
speaker identity, speaking style, and domain shift. They require
speaker-independent validation against study-relevant labels before use as
dependent variables or explanatory evidence.

## Face And Text Processing

Native Face and Text can execute in-app from a legacy file/folder or an
authorized Procurement catalog subset. Catalog mode validates the exact top
`source_manifest.json`/`source_metadata.csv` pair, digest, selection, and every
mapped `source_context.json` before model work or publication. The exact top
pair is copied byte-for-byte to the processing root while the ordered processed
SourceID subset is recorded separately. Only Speaker affects grouping; all
other fields remain metadata. Repeated links remain distinct SourceIDs.

Face uses Py-Feat Detectorv2 and emits full Parquet, readable `face_core.csv`,
and manifests. Its offline readiness check requires the pinned native stack,
trusted FFmpeg/TorchCodec runtime, verified cached checkpoints, and a real
offline model construction. Model preparation is a separate network-enabled
action; only that child may receive a Hugging Face token.

Text uses Whisper followed by RockSteady. Language precedence is the catalog
row's YouTube-reported language, then explicit Whisper language, then blank;
researcher `Language` remains ordinary metadata. RockSteady 0.4, its
dictionaries, and a JDK/Javac are separately installed/licensed external
requirements and are not downloaded by repository setup. SourceID and context
identity pass through every stage and resume fingerprint.

iMotions face CSVs are parsed after the `#DATA` marker or a detected
`Row,Timestamp` header. Parsing stops at the first blank row to exclude appended
summary tables. Duplicate exports are deduplicated by normalized source label,
retaining the larger candidate.

## Common Analysis Table

Face and audio sources are converted into a common numeric table before report
generation. Columns are classified as:

- core emotion score on 0 to 100;
- other score on 0 to 100;
- valence on -100 to 100;
- other numeric;
- descriptor-only structural/timing/landmark data.

Scaling contracts remain source-specific:

- core iMotions emotion values in 0 to 1 can scale to 0 to 100;
- iMotions valence in -1 to 1 scales to -100 to 100;
- iMotions FEA `Index` columns already on 0 to 100 are not rescaled;
- native Py-Feat primary-face probabilities in 0 to 1 scale to 0 to 100;
- native Py-Feat valence and arousal in -1 to 1 scale to -100 to 100;
- audio categorical probabilities are multiplied by 100;
- audio valence in 0 to 1 is transformed as
  `signed_valence = (raw_valence * 200) - 100`.

Native Face maps Happy to Joy and Sad to Sadness, with Anger, Disgust, Fear,
Surprise, and Neutral direct. Only detected primary-face rows contribute;
no-face rows, Contempt, and Confusion are missing rather than fabricated zero.
The provider remains `Py-Feat / Native Face`, distinct from
`Video / iMotions` and AFFDEX.

Face media identity and SHA-256 are revalidated after Py-Feat returns and
before result publication. Catalog Analysis also compares duplicated outer
identity/metadata fields with the hash-bound source context and copied root
sidecars. A changed input or relabelled manifest is rejected rather than
reported against stale provenance.

Native Text retains Positive/Negative Sentiment on 0 to 1. Text Valence is
`(Positive Sentiment - Negative Sentiment) / (Positive Sentiment + Negative Sentiment)`
on -1 to 1 and is blank at a zero denominator.

These transformations should be stated when reporting values.

## Reusable Analysis Profiles

Postprocessing choices are stored in `analysis_profile.json`, separate from the
procurement sidecars. The profile records the source-manifest path and digest,
ordered metadata sort fields, optional metadata filters and automatic grouping,
and manual groups whose members are stable speaker or SourceID identities.
Manual membership is resolved to SourceIDs and duplicate assignment is rejected.
This permits several ordered or grouped analyses of the same acquired sources
without rewriting `source_manifest.json` or `source_metadata.csv`.
The profile manifest remains authoritative when an ordinary legacy Text or
iMotions export has no duplicate sidecars; exact speaker, SourceID, title, and
output-folder identities provide the linkage. When every selected legacy
folder is sidecarless, researchers select the procurement run's
`source_manifest.json` explicitly in **Customize output**. Because imported
legacy Text is one observation per speaker, legacy Text-enabled profiles must
not split one speaker's visible sources across output groups.
Native `video_level_summary.csv` is SourceID-grain, is validated against its
manifest/hash/sidecars, and permits SourceID splits. Text Valence is recomputed
from the selected positive/negative totals after every profile selection rather
than averaging child valences. Profile reruns never mutate processing output or
source sidecars.

The native Text pair root contains exact copies of the validated catalog JSON
and CSV sidecars. Its completion manifest hashes both files and the ordered
source contexts, so import is explicit and relocatable without a parent-depth
search. Analysis applies the producer's bounded 512 MiB/10,000,000-item JSON
manifest and 384 MiB CSV envelope rather than a narrower consumer limit.

## Statistical Outputs

### Histograms

Scores use fixed 5-point bins. Core/other scores span 0 to 100, and valence
spans -100 to 100. Empty bins remain present to make sources comparable. Values
outside a fixed scale are excluded from that histogram but remain eligible for
descriptive statistics.

Optional logscale reports transform each count as:

```text
log_count = log10(count + 1)
```

Linear histograms remain the primary output.

### Descriptive Statistics

`other_findings/descriptive_statistics.csv` records finite count, missing
count, mean, sample standard deviation, min, max, interpolated quartiles,
median, excess kurtosis, non-zero count, and non-zero percentage.

Machine-readable descriptive statistics retain floating-point precision until
aggregation; workbook presentation rounds to two decimals. Releases before
2026-09-04 rounded per-recording statistics before weighting them. Reproducing
those historical files and regenerating corrected estimates are distinct tasks.
Audio dimensional bounds are nominal regression ranges, so finite values outside
them must retain the same declared scaling and be accounted for when comparing
histogram totals with descriptive-statistic counts.

For `n > 1`, sample standard deviation uses:

```text
s = sqrt(sum((x_i - mean)^2) / (n - 1))
```

Population excess kurtosis uses:

```text
kurtosis = mean((x_i - mean)^4) / variance^2 - 3
```

Constant descriptors are reported with kurtosis zero. Exact formatting and edge
cases are documented in `analysis/CALCULATIONS.md`.

### Chi-Squared Comparisons

For each metric, non-empty histogram bins form rows and sources form columns.
Expected counts are:

```text
expected_ij = row_total_i * column_total_j / grand_total
```

Pearson's statistic is:

```text
X^2 = sum((observed_ij - expected_ij)^2 / expected_ij)
df = (non_empty_bins - 1) * (sources - 1)
```

Pairwise matrices repeat this calculation for each source pair, so pairwise
degrees of freedom equal `non_empty_bins_for_pair - 1`.

### Spearman Comparisons

Spearman rho is the Pearson correlation of average-tie-ranked histogram count
vectors. It compares distribution shape across the displayed bins. The report
includes rho, an approximate two-tailed p-value, and bin count.

P-values are descriptive pipeline outputs, not automatic evidence of a
hypothesis. Multiple comparisons, dependence between windows, repeated speakers,
sampling design, and prespecified hypotheses must be handled in the study's
statistical analysis plan.

## Resource Controls

Launcher-owned processes can be constrained by CPU affinity, system or
process-tree RAM, and system-wide NVIDIA utilization telemetry.

- CPU percentage maps to a logical-processor count.
- RAM percentage uses overall system-used memory.
- RAM gigabytes uses resident memory across the pipeline process tree.
- GPU percentage uses `nvidia-smi` and is unavailable on unsupported devices.

The monitor pauses/resumes descendants with hysteresis. Sustained RAM pressure
terminates the process tree after 30 seconds. This is operational protection,
not a deterministic resource reservation. Native libraries, drivers, other
users, and operating-system caches may sit outside measured values.

## Provenance And Reproducibility Checklist

For each reported experiment, retain:

1. Repository commit and branch.
2. Python version, operating system, CPU/GPU, and installed dependency versions.
3. SourceID, catalog SHA-256, source URL/canonical local identity, title,
   user metadata, YouTube-reported language, and collection date.
4. Procurement mode and every non-default setting.
5. Selected interval and extraction manifests.
6. Audio window/stride, OpenSMILE feature set/version, model names, model
   availability, and device.
7. Py-Feat/checkpoint and Whisper/RockSteady/JDK versions, readiness results,
   settings, and external tool versions for any imported outputs.
8. Analysis flags such as logscale, timing/landmark inclusion, and geometry
   exclusion.
9. Generated run logs, column manifests, and skipped/duplicate records.
10. Manual quality-control protocol and exclusion decisions.

Credentials and downloaded model weights should not be archived in the
repository. Archive hashes, versions, and model identifiers instead.

## Validation And Quality Control

Recommended minimum quality control:

- manually verify source/speaker identity before processing;
- inspect all missing metadata and licence values;
- inspect Focus boundaries against the original timeline;
- audit a prespecified random sample of beta face/voice intervals;
- verify model columns are populated and read the manifest warnings;
- compare raw input ranges against generated histogram ranges;
- verify speaker grouping and duplicate handling;
- preserve rejected/failed manifests rather than silently dropping them;
- run automated tests and one real-media smoke on the deployment environment.

No current automated suite establishes construct validity, demographic
fairness, cross-language performance, or causal interpretation.

## Ethics, Copyright, And Data Protection

Researchers remain responsible for copyright, platform terms, consent,
institutional ethics approval, data-minimization, retention, and secure handling
of biometric or potentially identifiable data. The Full-video warning is an
interface safeguard, not legal advice.

The application stores credentials locally and masks their browser-visible
status. It should run only on a trusted machine and should not be exposed as a
network service.

The project affiliation is the School of Computer Science, Trinity College
Dublin, the University of Dublin. The root MIT License does not grant rights
to institutional names, logos, or other marks. Inclusion of an institutional
identifier must not be treated as permission for reuse or as endorsement of
particular findings; release packaging should include such material only when
the applicable permission and current identity guidance have been verified.

## Reporting Language

Prefer:

> The model assigned a higher estimated probability to class X in the selected
> windows.

Avoid:

> The speaker felt X.

Prefer:

> The acoustic descriptor distribution differed between the sampled videos.

Avoid:

> The videos prove a psychological difference.

This distinction should be maintained in papers, presentations, and exported
interpretive material.
