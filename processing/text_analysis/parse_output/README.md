# RockSteady CSV Output

This directory is retained only for older, pre-manifest RockSteady exports.
The current Text pipeline does not overwrite or trust these files for resume.

## Current contract

```text
processing/text_analysis/output/current/rocksteady/
  all/<Country>/<Speaker>/<Video>.csv   # canonical General Language categories
  core/<Country>/<Speaker>/<Video>.csv  # derived 6-category view
  core/derived_view_manifest.json
```

The default pipeline runs RockSteady exactly once against
`output/current/prepared_segments/` with General Language English and dynamically exports
all 45 categories in that dictionary. It writes the canonical CSV under
`rocksteady/all/`, then derives `rocksteady/core/` by copying identity fields
and these categories:

```text
Active, Negativ, Passive, Positiv, Strong, Weak
```

Because `selected` is derived rather than independently analysed, shared counts
come from the same RockSteady result.

A researcher can opt into any additional licensed dictionary and categories;
custom categories are dynamic rather than privileged by the native pipeline.

Run the complete workflow or resume at RockSteady:

```powershell
python -m processing.text_analysis Videos
python -m processing.text_analysis Videos --from-stage rocksteady
```

RockSteady uses **Total** counts. Segment text is often short, so storing raw
counts avoids misleading input-level percentages; postprocessing derives
proportions with the matched Whisper word counts.

Final reports are written to:

```text
analysis/output/text/text_output/selected/
analysis/output/text/text_output/extra/
analysis/output/text/text_output/multimodal/
```

Each contains segment-level data, video and speaker summaries, descriptor
statistics, alignment audits and SVG graphs. See
[`../README.md`](../README.md) and
[`../NAMING_CONVENTION.md`](../NAMING_CONVENTION.md).
