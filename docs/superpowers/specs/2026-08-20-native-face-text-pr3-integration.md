# Native Face and Text PR 3 Integration Specification

## Authority and provenance

- Integrate the useful work from `JMLal250209/feeling-political` pull request 3 at exact head `e6e886255b55b76137fdc40ca8734e971cd420b8`.
- The destination baseline is local commit `8dc927bb429026af1398c6544ac6e18d5f85ff76`.
- Do not merge or cherry-pick the PR history. Port the audited source into new local commits and preserve authorship with `PR-Source` and `Co-authored-by` trailers.
- Do not fetch, inspect, or merge any different profile pull request. Do not push.

## Product result

- Processing exposes native Face (Py-Feat) and native Text (Whisper plus an externally supplied RockSteady runtime) alongside the existing Audio path.
- Researchers can run one media file or a procurement catalog run. Catalog runs remain bound to immutable `source_manifest.json`, `source_metadata.csv`, `source_context.json`, selected SourceIDs, and catalog digest.
- Speaker alone controls folder grouping. Country, Language, Gender, and all other researcher columns remain metadata and never acquire folder semantics.
- Native Text results feed Analysis at SourceID grain so profiles can be reused for different filtering/grouping runs.
- Native Face results feed Analysis as a distinct `Py-Feat / Native Face` provider. They are never relabelled AFFDEX or silently blended with iMotions.

## Native Face analysis contract

- Read verified `face_core.csv` plus `video_manifest.json` outputs.
- Use primary-face rows only. Explicit no-face rows are missing observations, not zeros.
- Map `Happy` to `Joy` and `Sad` to `Sadness`; map Anger, Disgust, Fear, Surprise, and Neutral directly.
- Convert emotion probabilities from `[0, 1]` to `[0, 100]` for display.
- Convert native valence and arousal from `[-1, 1]` to `[-100, 100]` for display.
- Keep Contempt and Confusion blank because Py-Feat does not supply them.
- Include every supplied native emotion plus valence and arousal in the final workbook, with provider and scale recorded in the Measure Guide.

## Native Text analysis contract

- Keep legacy `speaker_level_summary.csv` import compatibility.
- New runs include SourceID in video/segment results and aggregate only after profile selection.
- Emit `Positive Sentiment` and `Negative Sentiment`; accept legacy positive/negative-valence aliases on import.
- Emit Text Valence as `(positive - negative) / (positive + negative)`, blank when the denominator is zero, range `[-1, 1]`.
- User dictionaries may contain any category, including Political, but no political category is built in, mandatory, or privileged.

## Safety and release boundaries

- Preserve lexical output paths across application and CLI boundaries so Windows junction/reparse checks see the path selected by the user.
- Reuse the existing bounded source-context/sidecar validation and canonical-media filtering. Reject stale, missing, duplicate, ambiguous, tampered, or unselected contexts before model work or output publication.
- Neutralize spreadsheet formulas in all researcher-controlled CSV/XLSX values and dynamic headers while preserving strict numeric literals and intentional workbook formulas.
- Keep optional ML imports lazy. The desktop shell and existing tests must start without Py-Feat, PyArrow, Whisper, Java, or RockSteady installed; readiness must report exactly what is absent.
- RockSteady JAR/dictionaries, downloaded model weights, generated outputs, private fixtures, and caches remain untracked.
- Remove `feeling-political` namespaces, political example identities, fixed `POLIT` defaults, `political_proportion`, and obsolete `preprocessing`/`postprocessing` runtime paths from the port.
- Preserve current token/origin/CSP protections, credential scoping, Trinity branding, responsive invalid-link containment, manifest authorization, Analysis profile UI, and all existing Audio behavior.

## Verification boundary

- Port and adapt the PR's face, text, RockSteady-adapter, text-postprocessing, and shared-I/O tests.
- Add end-to-end regressions for pooled/named catalogs, selected SourceIDs, sidecar tampering, cache exclusion, arbitrary metadata, profile reruns, native Face workbook measures, Text Valence, formula injection, missing optional dependencies, and Windows junctions through the HTTP/launcher/backend/child path.
- The final repository suite, strict browser harness, compilation, Node syntax, CLI help/readiness, setup verification, protected OpenSMILE identity, hygiene scan, and exact-diff security review must pass.
