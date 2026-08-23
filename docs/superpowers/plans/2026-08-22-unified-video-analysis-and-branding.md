# Unified Video Analysis and Branding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Analysis-facing iMotions/Py-Feat split with one provider-detecting Video workflow, restore the compact Trinity shield/title treatment, use semantic subtitles, remove project-owned U+2014 em dashes, and retain complete CLI access.

**Architecture:** Introduce a small canonical Video boundary in `analysis/video.py` and `analysis/video_contract.py`. It detects exactly one supported provider before writes, delegates parsing to the existing provider modules, normalizes both results into one Video metric union, and carries provider identity only as provenance. The workflow, backend, and desktop UI consume that boundary; old provider-specific workflow arguments remain one-release aliases and lower-level provider CLIs remain intact.

**Tech Stack:** Python 3.12, `argparse`, `csv`, `dataclasses`, `pathlib`, `openpyxl`, stdlib `unittest`, HTML/CSS/vanilla JavaScript, Node UI harnesses, Playwright browser harness where available.

**Spec:** `docs/superpowers/specs/2026-08-22-unified-video-analysis-and-branding.md`

## Global Constraints

- Use test-driven development for every production behavior: add one focused failing test, run it and observe the expected failure, implement the minimum change, then rerun it green.
- Do not push, create/update a pull request, or touch the remote.
- Keep the final work committed locally. Include this plan with the implementation commit so the current two-commit sequence receives one final implementation commit.
- Do not alter the retained Jiaming-derived Text security findings or the separate explicit-language defect.
- Do not rewrite bundled or vendored third-party trees, especially `processing/audio_analysis/opensmile-3.0-win-x64/**`.
- Analysis must never mutate the selected provider source tree, manifests, or sidecars.
- Detection must complete before archiving, model work, report generation, or workbook publication.
- Missing provider measures stay blank (`None`/empty cell), never numeric zero.
- Py-Feat `Arousal` and iMotions `Engagement`/`Adaptive Engagement` remain scientifically distinct.

---

## Task 1: Define the canonical Video contract and fail-closed provider detection

**Files:**

- Create: `analysis/video_contract.py`
- Create: `analysis/video.py`
- Create: `analysis/tests/test_video.py`
- Read/reuse: `analysis/imotions.py`
- Read/reuse: `analysis/native_face.py`
- Read/reuse: `processing/face_analysis/outputs.py`

- [ ] **Step 1: Add failing metric-contract tests**

Add `VideoContractTests` in `analysis/tests/test_video.py` asserting exact, ordered tuples:

```python
VIDEO_COMMON_METRICS = (
    "Anger", "Disgust", "Fear", "Joy", "Sadness", "Surprise",
    "Neutral", "Valence",
)
VIDEO_IMOTIONS_ONLY_METRICS = (
    "Contempt", "Confusion", "Sentimentality", "Adaptive Valence",
    "Engagement", "Adaptive Engagement",
)
VIDEO_PYFEAT_ONLY_METRICS = ("Arousal",)
```

Assert that `VIDEO_METRICS` is the stable union, `VIDEO_NORMALIZATION_VERSION` is non-empty, and provider availability explicitly marks unavailable metrics rather than substituting values.

- [ ] **Step 2: Run the metric-contract test and observe RED**

Run:

```powershell
python -m unittest analysis.tests.test_video.VideoContractTests -v
```

Expected: import failure because `analysis.video_contract` does not exist.

- [ ] **Step 3: Implement the minimum immutable contract**

Create `analysis/video_contract.py` with:

```python
VideoProvider = Literal["imotions_affdex", "pyfeat_native_face"]
VIDEO_NORMALIZATION_VERSION = "1"

def available_video_metrics(provider: VideoProvider) -> frozenset[str]: ...
def video_measure_guide_rows(provider: VideoProvider) -> tuple[dict[str, str], ...]: ...
```

Each Measure Guide row must include canonical measure, provider availability, source channel, output scale, and the rule that unsupported values remain blank.

- [ ] **Step 4: Run the metric-contract test and observe GREEN**

Run the Step 2 command and confirm all contract assertions pass.

- [ ] **Step 5: Add failing detection tests for both providers and fail-closed cases**

Using temporary fixture trees, add these tests:

- `test_detects_verified_pyfeat_run`
- `test_detects_imotions_csv_headers_and_rows`
- `test_rejects_source_with_no_provider_evidence`
- `test_rejects_source_with_both_provider_signatures`
- `test_incomplete_pyfeat_signature_fails_as_pyfeat_without_imotions_fallback`
- `test_tampered_pyfeat_binding_fails_before_output_directory_exists`
- `test_imported_manifest_provider_conflict_is_rejected`
- `test_legacy_imotions_report_shape_returns_warning_evidence`

Capture a digest/listing of each fixture tree before detection and prove it is byte-identical afterward.

- [ ] **Step 6: Run the detection tests and observe RED**

Run:

```powershell
python -m unittest analysis.tests.test_video.VideoDetectionTests -v
```

Expected: import/attribute failures for the new detector.

- [ ] **Step 7: Implement one read-only detector**

Create in `analysis/video.py`:

```python
@dataclass(frozen=True)
class DetectedVideoSource:
    provider: VideoProvider
    source_path: Path
    source_method: Literal["run", "import"]
    evidence: tuple[str, ...]
    warnings: tuple[str, ...] = ()

def detect_video_source(
    source_path: Path,
    source_method: Literal["run", "import"],
) -> DetectedVideoSource: ...
```

Reuse provider validation/parsing helpers where possible. Treat any native Face signature (`face_core.csv`, bound Face run/video manifests, or native provider metadata) as a Py-Feat candidate and validate it completely; do not fall through to iMotions when that validation fails. Detect iMotions from accepted raw headers/data or authoritative imported column-manifest metadata. Reject zero or two resolved providers with actionable messages.

- [ ] **Step 8: Run detection tests and existing provider suites GREEN**

Run:

```powershell
python -m unittest analysis.tests.test_video.VideoDetectionTests analysis.tests.test_imotions analysis.tests.test_native_analysis -v
```

---

## Task 2: Normalize both providers into one canonical Video result

**Files:**

- Modify: `analysis/video.py`
- Modify: `analysis/video_contract.py`
- Modify: `analysis/native_face.py`
- Modify: `analysis/imotions.py`
- Modify: `analysis/tests/test_video.py`
- Modify as needed: `analysis/tests/test_imotions.py`
- Modify as needed: `analysis/tests/test_native_analysis.py`

- [ ] **Step 1: Add failing Py-Feat normalization tests**

Create parameterized/subtest fixtures for 1, 7, and 14 sources and assert:

- `Happy -> Joy`, `Sad -> Sadness`.
- common probabilities scale `0..1` to `0..100`.
- Valence and Arousal scale `-1..1` to `-100..100`.
- Py-Feat `Arousal` is populated.
- Contempt, Confusion, Sentimentality, Adaptive Valence, Engagement, and Adaptive Engagement are blank.
- Source IDs retain exact natural ordering and there is no source-count cap.

- [ ] **Step 2: Run the Py-Feat normalization tests and observe RED**

Run the new test class/methods only. Expected: missing canonical result API and/or wrong metric shape.

- [ ] **Step 3: Implement the canonical result adapter for Py-Feat**

Expose a provider-neutral result shape from `analysis/video.py`, for example:

```python
@dataclass(frozen=True)
class CanonicalVideoResult:
    provider: VideoProvider
    source_ids: tuple[str, ...]
    rows: tuple[dict[str, float | None], ...]
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]
    normalization_version: str

def load_canonical_video(detected: DetectedVideoSource) -> CanonicalVideoResult: ...
```

Adapt the existing native Face parser rather than duplicating manifest validation. Materialize every union metric key with `None` for unsupported channels.

- [ ] **Step 4: Run Py-Feat normalization tests GREEN**

Also rerun existing native Face tests to prove the expert lower-level output remains compatible.

- [ ] **Step 5: Add failing iMotions normalization tests**

For 1, 7, and 14 sources assert:

- common names/scales match canonical Video.
- Engagement and Adaptive Engagement remain populated with those exact names.
- Arousal remains blank unless a supported iMotions Arousal channel is present.
- missing values stay blank, never zero.
- source order is exact and unrestricted.

- [ ] **Step 6: Run iMotions normalization tests and observe RED**

Run the new methods only and record the mismatch with the canonical result API.

- [ ] **Step 7: Implement the iMotions adapter**

Delegate accepted-header and legacy-report parsing to `analysis/imotions.py`; normalize its rows into the same `CanonicalVideoResult`. Preserve original field/channel names in provenance. Reject contradictory imported provider metadata.

- [ ] **Step 8: Run the complete canonical adapter suite GREEN**

Run:

```powershell
python -m unittest analysis.tests.test_video analysis.tests.test_imotions analysis.tests.test_native_analysis -v
```

---

## Task 3: Write one Video workbook and provider-aware provenance

**Files:**

- Modify: `analysis/combined_summary.py`
- Modify: `analysis/video.py`
- Modify: `analysis/tests/test_combined_summary.py`
- Modify: `analysis/tests/test_profile_workbook.py`
- Modify: `analysis/tests/test_profile_metadata.py`
- Modify: `analysis/tests/test_video.py`

- [ ] **Step 1: Add failing one-sheet workbook matrix tests**

For both providers and source counts 1, 7, and 14, generate a combined workbook and assert:

- exactly one quantitative worksheet named `Video` and no new `Native Face` worksheet.
- the Video header uses the complete canonical metric union in stable order.
- unsupported provider metrics produce blank cells, including downstream formulas/charts where data is unavailable.
- Source IDs preserve exact order.
- profile/group/filter formulas continue to expand dynamically.

- [ ] **Step 2: Run the workbook matrix tests and observe RED**

Run the new workbook test class only. Expected: separate `Video`/`Native Face` behavior or absent provider-specific union columns.

- [ ] **Step 3: Refactor the workbook writer around canonical Video**

Replace the Analysis-facing `NATIVE_FACE_METRICS`/`native_face` sheet split with `VIDEO_METRICS` and the canonical Video result. Keep legacy `Native Face` sheets readable only in import/migration paths. Ensure blank columns remain represented in the table/Measure Guide without creating numeric zeroes or misleading histograms.

- [ ] **Step 4: Add failing provenance and Measure Guide tests**

Assert new outputs record:

- requested modality `video`
- resolved provider
- detection evidence and warnings
- normalization contract version
- canonical availability
- original provider/channel names

Assert source manifests/sidecars remain byte-identical.

- [ ] **Step 5: Run provenance tests and observe RED**

Run the new methods only; expect missing metadata/guide fields.

- [ ] **Step 6: Implement provenance and Measure Guide rows**

Thread `DetectedVideoSource`/`CanonicalVideoResult` metadata into column manifests, combined manifests, and Measure Guide output. Return an actionable migration error for overrides targeting removed provider-specific sheet names.

- [ ] **Step 7: Run workbook/profile/provenance tests GREEN**

Run:

```powershell
python -m unittest analysis.tests.test_combined_summary analysis.tests.test_profile_workbook analysis.tests.test_profile_metadata analysis.tests.test_video -v
```

---

## Task 4: Add the canonical workflow CLI while preserving expert and legacy entrypoints

**Files:**

- Modify: `analysis/workflow.py`
- Modify: `analysis/tests/test_workflow.py`
- Modify: `analysis/tests/test_workflow_security.py`
- Modify: `analysis/README.md`
- Modify: `analysis/outputs.md`
- Modify: root `README.md` if it documents Analysis CLI examples

- [ ] **Step 1: Add failing canonical CLI parsing tests**

Assert `python -m analysis.workflow --help` and parser-level calls expose:

```text
--video-source PATH
--video-method run|import
```

Add tests for:

- canonical Video run/import requests
- auto-detection of both supported providers
- no-provider and both-provider failure before output writes
- old `--imotions-*` and `--native_face-*` aliases mapping to one Video request
- duplicate combinations (canonical plus alias, or both provider aliases) failing clearly
- alias method without source and conflicting alias methods failing clearly

- [ ] **Step 2: Run the CLI parsing tests and observe RED**

Run the newly added workflow methods only; expect unrecognized canonical flags.

- [ ] **Step 3: Implement canonical workflow argument resolution**

Change Analysis-facing modality handling to `video | audio | text`. Parse canonical and legacy arguments into one internal Video request before `_run_modality`. Call `detect_video_source()` once, then the provider adapter. Keep lower-level modules executable and do not remove their CLIs.

- [ ] **Step 4: Add failing workflow manifest/immutability tests**

Assert provider detection metadata is written, output modality is `video`, source trees remain byte-identical, and failures leave no archive/report/workbook artifacts.

- [ ] **Step 5: Run the workflow tests and observe RED**

Expected: old provider-specific modality names/provenance or premature output writes.

- [ ] **Step 6: Implement the stable orchestration boundary**

Resolve Video before creating/archive-moving output paths. Maintain one-release aliases with a deprecation warning in CLI output/manifest. Preserve existing audio/text behavior exactly.

- [ ] **Step 7: Document every supported CLI layer**

Document and test these exact commands:

```text
python -m processing.face_analysis
python -m processing.text_analysis
python processing/audio_analysis/run_audio_analysis.py
python -m analysis.imotions
python -m analysis.native_face
python -m analysis.audio
python -m analysis.workflow
```

Explain that `analysis.workflow` is the stable automated orchestration API, while provider-level entrypoints are explicit lower-level expert tools.

- [ ] **Step 8: Run workflow, CLI, and security regressions GREEN**

Run:

```powershell
python -m unittest analysis.tests.test_workflow analysis.tests.test_workflow_security -v
```

Then run each listed command with `--help` (or its documented non-mutating help equivalent) and confirm exit code 0.

---

## Task 5: Make the backend and HTTP boundary canonical Video consumers

**Files:**

- Modify: `application/backend.py`
- Modify: `application/launcher.py` only if request validation requires it
- Modify: `application/tests/test_backend.py`
- Modify: `application/tests/test_launcher_progress.py`
- Modify: `application/tests/test_launcher_http_security.py`
- Modify: `application/tests/test_native_processing_ui.py`

- [ ] **Step 1: Add failing backend request/command tests**

Assert the backend accepts one request object named `video` with method/source, detects provider read-only, and emits canonical workflow flags:

```text
--video-source <path> --video-method <run|import>
```

Legacy request keys may be accepted as aliases but must normalize to `video`; more than one Video source must fail. Assert iMotions-only options fail for detected Py-Feat with an actionable provider-specific message.

- [ ] **Step 2: Run focused backend tests and observe RED**

Run only the new methods and confirm current commands use `--imotions-*`/`--native_face-*` or expose separate modalities.

- [ ] **Step 3: Implement backend normalization and discovery**

Use `analysis.video.detect_video_source` for shared validation. Return provider and evidence as status metadata after validation. Build only canonical Video CLI arguments for new requests. Retain legacy aliases at the request boundary for one release.

- [ ] **Step 4: Add failing Native Face handoff test**

Assert completed Face Processing output populates the canonical Video Analysis source, never a separate Native Face Analysis card or payload.

- [ ] **Step 5: Run the handoff test and observe RED**

Expected: old `native_face` Analysis target or missing handoff control.

- [ ] **Step 6: Implement the canonical handoff**

Keep Face Processing separate, but map its completed artifact root to `analysis.video.source` and allow detection to report `pyfeat_native_face`.

- [ ] **Step 7: Run backend and HTTP suites GREEN**

Run:

```powershell
python -m unittest application.tests.test_backend application.tests.test_launcher_progress application.tests.test_launcher_http_security application.tests.test_native_processing_ui -v
```

---

## Task 6: Replace the two Analysis cards with one auto-detecting Video card

**Files:**

- Modify: `application/static/index.html`
- Modify: `application/static/app.js`
- Modify: `application/static/styles.css`
- Modify: `application/tests/analysis_ui_logic_harness.js`
- Modify: `application/tests/analysis_ui_browser_harness.js`
- Modify: `application/tests/test_release_ui_contract.py`
- Modify: `application/tests/test_native_processing_ui.py`

- [ ] **Step 1: Add failing static DOM/logic tests**

Assert Analysis renders exactly three cards (`Video`, `Audio`, `Text`), one Video enable control, one run/import selector, and one Video path input. Assert separate visible iMotions and Native Face cards/fields are absent. Assert the payload uses only canonical `video`.

- [ ] **Step 2: Run Node/Python UI contract tests and observe RED**

Run:

```powershell
node application/tests/analysis_ui_logic_harness.js
python -m unittest application.tests.test_release_ui_contract application.tests.test_native_processing_ui -v
```

Expected: old two-card/provider-specific markup or payload assertions fail.

- [ ] **Step 3: Implement the single Video card and state model**

Collapse provider-specific Analysis state into:

```javascript
analysis: {
  video: { enabled: false, method: "import", source: "", provider: null },
  audio: { ... },
  text: { ... }
}
```

Display provider only after backend validation as status/provenance. Keep advanced iMotions controls hidden/disabled until detection reports iMotions, and have the backend validate them again.

- [ ] **Step 4: Add failing invalid-link containment regression**

Use an intentionally long malformed source URL/path and a long log/status string. Assert the input, top-left log/status element, modal/card, and page stay within the viewport at desktop and narrow widths (`scrollWidth <= clientWidth` where appropriate). Assert text wraps or truncates without obscuring controls.

- [ ] **Step 5: Run the containment tests and observe RED**

Run the browser harness (or static CSS contract fallback if Playwright is unavailable) and capture the expected overflow failure.

- [ ] **Step 6: Fix wrapping/min-width behavior**

Apply `min-width: 0`, safe `overflow-wrap: anywhere`, constrained status/log blocks, and input sizing to the smallest owning flex/grid containers. Preserve keyboard focus and readable validation messages.

- [ ] **Step 7: Add and satisfy provider-status/handoff tests**

Assert an iMotions path shows iMotions status, a native Face handoff shows Py-Feat status, and neither provider becomes a selectable modality.

- [ ] **Step 8: Run UI logic and browser suites GREEN**

Run both Node harnesses and the related Python application tests.

---

## Task 7: Restore compact Trinity branding, semantic subtitles, and ASCII punctuation

**Files:**

- Modify: `application/static/index.html`
- Modify: `application/static/styles.css`
- Modify: `application/static/app.js`
- Modify: project-owned tracked text files reported by the U+2014 audit
- Modify: matching tests and snapshots
- Do not modify: `processing/audio_analysis/opensmile-3.0-win-x64/**`

- [ ] **Step 1: Add failing branding and subtitle contract tests**

Assert:

- header renders `trinity-shield.png` beside the tool title.
- `trinity-main-logo.jpg` is not rendered.
- header uses a compact side-by-side flex/grid layout at desktop and narrow widths.
- Procurement, Processing, Analysis, and Face Processing headings contain only the title.
- explanations live in semantic subtitle elements (`small`, `.stage-subtitle`, or equivalent), never a title string separated by punctuation.

- [ ] **Step 2: Run branding tests and observe RED**

Run focused static/browser contract tests. Expected: current full horizontal JPEG and/or combined heading copy fail.

- [ ] **Step 3: Implement shield/title branding and subtitles**

Use the existing transparent `application/static/trinity-shield.png`; do not generate or recolor a new logo. Keep the shield compact, naturally proportioned, and aligned beside the title without an opaque background rectangle. Convert stage descriptions to separate subtitle nodes and move Py-Feat explanation beneath the Face Processing heading.

- [ ] **Step 4: Add failing U+2014 repository audit test**

Add a bounded test that enumerates tracked project-owned text while excluding bundled/vendored third-party roots, then fails with precise paths/lines for every U+2014 occurrence. It must not target mathematical minus U+2212 or ordinary hyphens.

- [ ] **Step 5: Run the punctuation audit and observe RED**

Run the new test and retain the list of project-owned files it reports.

- [ ] **Step 6: Replace only project-owned U+2014 characters**

Use `apply_patch` for each reported source/doc/test file. Update expectations to ASCII `-`. Do not alter bundled OpenSMILE docs/config/binaries and do not change behavior in retained Jiaming-derived security-sensitive Text code beyond literal UI/CLI/documentation punctuation where required.

- [ ] **Step 7: Run branding, punctuation, and responsive gates GREEN**

Run focused Python/Node/browser tests, followed by:

```powershell
$emDash = [char]0x2014
git grep -n $emDash -- . ':!processing/audio_analysis/opensmile-3.0-win-x64/**'
```

Expected: no project-owned matches.

---

## Task 8: Full verification, independent review, cleanup, and final local commit

**Files:**

- Modify as required by verified failures only
- Inspect: all files in `git diff --name-only`
- Preserve: user-owned/unrelated changes and all third-party trees

- [ ] **Step 1: Run focused Analysis tests from a fresh command**

```powershell
python -m unittest discover -s analysis/tests -p 'test_*.py' -v
```

- [ ] **Step 2: Run focused application tests**

```powershell
python -m unittest discover -s application/tests -p 'test_*.py' -v
node application/tests/analysis_ui_logic_harness.js
node application/tests/catalog_ui_logic_harness.js
node application/tests/analysis_ui_browser_harness.js
```

If the real browser harness has an established optional-environment skip, record that exact result and run its static/logic fallback; do not misreport it as browser execution.

- [ ] **Step 3: Run native processing and CLI regressions**

```powershell
python -m unittest discover -s processing/face_analysis/tests -p 'test_*.py' -v
python -m unittest discover -s processing/text_analysis/tests -p 'test_*.py' -v
python -m unittest discover -s processing/audio_analysis/tests -p 'test_*.py' -v
python -m unittest discover -s processing/tests -p 'test_*.py' -v
```

Run any known resource-sensitive/suite-order tests separately if the inherited suite documents that requirement; report the distinction accurately.

- [ ] **Step 4: Run the full repository test command documented by the project**

Read the current README/CI configuration for the authoritative command, run it fresh, and retain pass/fail/skip counts. Fix only regressions in scope.

- [ ] **Step 5: Verify source immutability and third-party preservation**

Compare fixture/input digests from before and after all Analysis runs. Confirm `git diff -- processing/audio_analysis/opensmile-3.0-win-x64` is empty. Confirm no new root-level temp files, `.bat`, `.ps1`, reports, caches, screenshots, or generated output are tracked/untracked.

- [ ] **Step 6: Audit the final diff**

Run:

```powershell
git diff --check
git status --short
git diff --stat
git diff --name-status
```

Inspect every changed file. Verify there are no unfinished implementation markers, no mixed `native_face`/`imotions` Analysis modality leaks, no U+2014 in project-owned files, and no accidental fixes to retained Jiaming-derived findings.

- [ ] **Step 7: Request two-stage independent review**

First ask a reviewer to check exact compliance with the approved specification. After addressing any finding, ask a separate reviewer to inspect code quality, fail-closed behavior, missing-value semantics, compatibility, and test evidence. Rerun affected tests after every change.

- [ ] **Step 8: Create the final local commit without pushing**

Stage only intended files and commit once with:

```text
feat: unify video analysis and restore Trinity branding
```

Then verify:

```powershell
git status --short --branch
git log -3 --oneline
```

Expected: clean working tree; the three latest task commits are local; no push performed.

## Plan Self-Review Checklist

- [ ] Every specification section maps to at least one task/test above.
- [ ] Every production behavior begins with an observed failing test.
- [ ] Provider labels/scales are truthful: Arousal is not Engagement.
- [ ] Unsupported measures are blank in data, formulas, charts, and exports.
- [ ] Exactly one new Video sheet/card/request exists.
- [ ] Provider identity remains in status, manifests, and Measure Guide.
- [ ] Legacy workflow aliases and lower-level CLIs remain usable.
- [ ] Detection and contradiction failures occur before any write/archive.
- [ ] Trinity uses the existing transparent shield beside the title.
- [ ] Invalid links/log text cannot overflow desktop or narrow layouts.
- [ ] Project-owned U+2014 reaches zero without rewriting bundled third-party files.
- [ ] Retained Jiaming-derived findings remain untouched.
- [ ] No push or pull-request interaction occurs.
