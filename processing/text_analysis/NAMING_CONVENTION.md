# Text Analysis Identity Convention

The current integrated Text pipeline preserves procurement's technical video
identity:

```text
<Speaker>/<Video>
```

Example:

```text
Research Speaker/Interview_[abc123].json
Research Speaker/Interview_[abc123].csv
```

`Speaker` is the existing first directory below the procurement `downloads`
folder. `Video` is the existing procurement video-directory name; the
transport-only `_full_video` suffix is removed when present. Text does not infer
a country, comparison group, language, or other research label from either
name.

The older three-level identity remains readable for existing/manual datasets:

```text
<Country>/<Speaker>/<Video>
```

Its canonical video name is `NNN_Country_Speaker_YYYYMMDD`. This is a legacy
compatibility format, not a requirement for procurement output.

## Layout by stage

For current procurement-backed runs:

```text
processing/text_analysis/output/current/transcripts/
  original/<Speaker>/<Video>.json
  eng/<Speaker>/<Video>.json
  bilingual/<Speaker>/<Video>.json

processing/text_analysis/output/current/prepared_segments/
  <Speaker>/<Video>/<Video>__segment_000001.txt

processing/text_analysis/output/current/rocksteady/
  all/<Speaker>/<Video>.csv
  core/<Speaker>/<Video>.csv

analysis/output/text/text_output/
  selected/segment_counts/<Speaker>/<Video>_segment_counts.csv
  extra/segment_counts/<Speaker>/<Video>_segment_counts.csv
```

The same stages also accept the legacy country directory before `Speaker`.

## Identity and validation

- The transcription inventory is authoritative for later Text stages.
- Whisper JSON, prepared segments, RockSteady CSV, and postprocessing records
  must resolve to the same complete two- or three-level identity.
- Duplicate identities and unsafe or incomplete paths are rejected.
- A two-level identity records country as an empty value; it does not guess one.
- Research comparison fields such as group or country belong to postprocessing
  metadata and may be changed without rerunning procurement or RockSteady.

Spaces, underscores, hyphens, letter case, and accents are normalised only for
comparison where a legacy filename must be checked against its directories.
Output retains the source directory spelling.
