# Unified Video Analysis and Branding Specification

## Authority and scope

- Replace the Analysis-facing split between iMotions and Py-Feat with one
  provider-detecting Video modality.
- Restore the compact Trinity shield beside the tool title and remove the full
  horizontal wordmark from the visible header.
- Present stage explanations as subtitles rather than title text separated by
  punctuation.
- Replace U+2014 em dash characters with ordinary ASCII hyphens throughout
  project-owned source, documentation, and tests. Bundled third-party trees
  remain byte-identical.
- Keep all work local and unpushed.
- Do not modify the previously identified security findings in Jiaming-derived
  Text engine code.

## Product result

Analysis presents one Video card with one source path. The researcher never
chooses a video provider. The application validates the selected path and
detects exactly one of these providers before any output is archived or
created:

- `imotions_affdex`
- `pyfeat_native_face`

The detected provider is displayed as status information and recorded in
provenance. It is not an Analysis modality choice. A path with no supported
provider evidence is rejected. A path with evidence for both providers is also
rejected rather than being resolved by file order, even though the normal UI
workflow supplies only one provider source.

## Canonical Video measure contract

Both providers produce one Analysis modality named `video` and one quantitative
workbook sheet named `Video`.

Common Py-Feat measures are normalized to the existing Video names and scales:

- `Happy` becomes `Joy`.
- `Sad` becomes `Sadness`.
- Anger, Disgust, Fear, Surprise, Neutral, and Valence retain those names.
- Emotion probabilities are scaled from `0..1` to `0..100`.
- Valence is scaled from `-1..1` to `-100..100`.

Provider-specific measures retain scientifically truthful names:

- Py-Feat exposes `Arousal`, scaled from `-1..1` to `-100..100`.
- iMotions exposes `Engagement` and `Adaptive Engagement`.
- Py-Feat Arousal is never relabelled Engagement.
- iMotions-only Contempt, Confusion, Sentimentality, Adaptive Valence,
  Engagement, and Adaptive Engagement remain blank for Py-Feat. Missing values
  are never converted to zero.
- Arousal remains blank for iMotions unless an actual supported iMotions field
  provides that measure.

The Video sheet uses the union of canonical common and provider-specific
measures. The Measure Guide records provider availability, source channel,
scale, and missing-value semantics. Existing probability, group, formula, and
profile behavior remains dynamic for arbitrary source counts.

## Provider detection and provenance

Add one provider detection boundary shared by the backend and workflow.

Py-Feat evidence requires verified native Face run artifacts, including the
bound run/video manifests and `face_core.csv`. Incomplete or tampered Py-Feat
evidence fails as Py-Feat and never falls through to iMotions discovery.

iMotions evidence requires accepted iMotions CSV headers and usable data rows,
or imported reports whose adjacent column manifests identify the iMotions
provider. Existing legacy report shape inference remains a compatibility
fallback with a warning.

New workflow manifests record:

- requested modality: `video`
- resolved provider
- provider detection evidence
- normalization contract version
- canonical metric availability
- original provider and channel information

Provider identity remains visible in provenance and the Measure Guide but does
not create a second worksheet or second UI modality.

## CLI contract

The complete workflow remains accessible without the desktop UI.

`python -m analysis.workflow` gains:

- `--video-source PATH`
- `--video-method run|import`

These options use the same provider detection and canonical Video contract as
the UI. Existing `--imotions-source`, `--imotions-method`,
`--native_face-source`, and `--native_face-method` options remain accepted as
compatibility aliases for one release. Supplying more than one Video alias is a
duplicate Video error.

Lower-level commands remain usable for larger automated systems and partial
pipelines:

- `python -m processing.face_analysis`
- `python -m processing.text_analysis`
- `python processing/audio_analysis/run_audio_analysis.py`
- `python -m analysis.imotions`
- `python -m analysis.native_face`
- `python -m analysis.audio`
- `python -m analysis.workflow`

The unified workflow CLI is the stable orchestration boundary. Provider-level
commands remain explicit expert tools and retain their native manifests and
provenance. This does not require a new plugin system, daemon API, or large SDK
rewrite.

## Desktop application

The Analysis screen contains three modality cards:

- Video
- Audio
- Text

The Video card has one enable control, one run/import choice, and one source
path. It accepts either iMotions or Py-Feat results and reports the provider
after validation. iMotions-only advanced controls are enabled only when
iMotions is detected and are validated again in the backend.

Native Face Processing remains a separate Processing action because it creates
Py-Feat results. Its completed-output handoff populates the single Video source
field in Analysis.

The backend accepts the canonical request name `video`, performs provider
detection, and emits the canonical workflow CLI arguments. Legacy request names
remain compatibility aliases but are never exposed as separate cards.

## Branding and copy

The home header uses the transparent `trinity-shield.png` beside the title. The
opaque horizontal JPEG is no longer rendered. The shield remains compact on
desktop and narrow layouts so it does not force the title below it or create a
contrasting background rectangle.

Stage tiles and the stage rail use semantic title and subtitle elements:

- Procurement / Source collection and preprocessing
- Processing / Generate or import modality results
- Analysis / Postprocessing and reporting

The title contains only the stage name. The explanation is a separate subtitle.
Face Processing follows the same rule, with Py-Feat information in supporting
copy rather than appended to the heading.

All project-owned U+2014 characters are converted to ASCII hyphens. This covers
visible UI copy, generated report text, CLI messages, documentation, and their
tests. Bundled OpenSMILE and other third-party source trees are not rewritten.

## Compatibility and migration

- Existing iMotions outputs remain valid Video inputs.
- Existing Py-Feat outputs remain valid Video inputs.
- Existing provider-specific CLI flags remain temporary aliases.
- Existing imported reports with provider metadata are normalized into Video.
- Legacy provider-specific workbook sheets remain readable as imports, but new
  workbooks write only `Video`.
- Existing reference override keys receive an actionable migration error if
  they target a removed provider-specific sheet name.
- Source manifests, source contexts, profile sidecars, and processing inputs are
  never rewritten by Analysis.

## Error handling

Validation occurs before archival, model work, report generation, or workbook
publication.

- No provider evidence: report the accepted iMotions and Py-Feat signatures.
- Both providers: ask for a root containing one provider.
- Incomplete or tampered provider evidence: fail under that provider's
  validation rules.
- Unsupported provider-specific option: identify the detected provider and the
  unsupported option.
- Missing provider metric: preserve a blank value and record availability.
- Contradictory imported provenance: reject the import.

## Verification

Use test-driven development for every production change.

The verification matrix covers each provider at 1, 7, and 14 sources and proves:

- exactly one `Video` worksheet
- identical canonical names and common scales
- Py-Feat Arousal remains Arousal
- iMotions Engagement remains Engagement
- unsupported measures are blank, not zero
- exact SourceID ordering and no fixed source-count cap
- provider provenance in manifests and Measure Guide
- profile/group/filter behavior and formulas
- immutable source trees and sidecars
- provider detection success and fail-closed none/both/tamper cases
- canonical UI, HTTP, backend, and CLI payloads
- legacy CLI alias behavior
- Trinity shield alignment at desktop and narrow widths
- no horizontal logo block or viewport overflow
- title/subtitle structure
- zero project-owned U+2014 occurrences

Run the focused Analysis, application, CLI, Node, and real browser gates before
the full repository suite. Preserve the established separate execution evidence
for inherited resource-sensitive and suite-order tests if they remain unstable
only in the all-in-one process.

## Non-goals

- No new network service, plugin protocol, or public Python SDK.
- No blending or simultaneous processing of iMotions and Py-Feat in one Video
  request.
- No false conversion of Py-Feat Arousal into iMotions Engagement.
- No synthetic zeroes for unavailable measures.
- No changes to bundled third-party files.
- No fixes to the retained Jiaming-derived Text security findings.
- No push or pull-request interaction.
