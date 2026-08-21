# Native Face and Text PR 3 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selectively integrate the native Face and Text workflows from PR 3 into the clean destination repository with immutable catalog provenance, reusable Analysis profiles, and no old private history.

**Architecture:** Port the model-facing engines as neutral, optional packages, then connect them through one shared catalog job contract into the current launcher and Analysis workflow. Native Face stays a named provider with its own scientific scale contract; native Text stays SourceID-grained until Analysis profiles choose filters and groups.

**Tech Stack:** Python 3.12, Py-Feat 2.1.1, pandas/PyArrow, OpenAI Whisper, external RockSteady 0.4/Java 21, openpyxl, vanilla JavaScript, pywebview, pytest/unittest, Microsoft Edge WebView2.

**Spec:** `docs/superpowers/specs/2026-08-20-native-face-text-pr3-integration.md`

## Global Constraints

- Port only from PR head `e6e886255b55b76137fdc40ca8734e971cd420b8`; do not merge/cherry-pick its 41-commit legacy graph.
- Keep destination baseline `8dc927bb429026af1398c6544ac6e18d5f85ff76` and every resulting commit local/unpushed.
- Preserve Trinity assets, the invalid-link overflow fix, application security controls, Audio behavior, profile customization, and OpenSMILE byte identity.
- Do not import generated output, real-study fixtures, weights, compiled Java, the RockSteady JAR, political examples, unrelated tools, or the PR's old application files wholesale.
- Only Speaker controls processing folders; every other CSV/DOCX field stays arbitrary metadata.
- Optional native dependencies must fail as honest readiness gates, not break module import or the existing app.
- Use canonical `Positive Sentiment`/`Negative Sentiment`; retain legacy aliases. Include native Text Valence and all native Face emotions/valence/arousal in the final workbook.
- Use test-first changes for every adaptation and regression fix. Preserve authorship with `PR-Source` and `Co-authored-by` trailers.

---

### Task 1: Port neutral native engines and their verified output contracts

**Files:**
- Create: `processing/io_utils.py`
- Create: `processing/ffmpeg_runtime.py`
- Create/modify: `processing/face_analysis/*.py`, `processing/face_analysis/tests/*.py`, `processing/face_analysis/README.md`
- Create/modify: `processing/text_analysis/*.py`, `processing/text_analysis/prepare_input/*.py`, `processing/text_analysis/transcribe/*.py`, `processing/text_analysis/rocksteady_adapter/*.py`, corresponding tests and neutral READMEs/examples
- Create: `analysis/text_pipeline/*.py`, with PR `postprocessing/text.py` placed at `analysis/text_pipeline/postprocess.py`
- Create/modify: relocated text-postprocessing tests under `analysis/tests/`
- Modify: `spreadsheet_safety.py`, `requirements.txt`, `scripts/setup.ps1`, `scripts/verify_setup.ps1`, `.gitignore`, `THIRD_PARTY_NOTICES.md`

**Interfaces:**
- Consumes: exact source files at PR head; existing `spreadsheet_safety.neutralize_spreadsheet_value`; existing trusted-tool resolution and credential-free child environment.
- Produces: import-safe `processing.face_analysis` and `processing.text_analysis` CLIs; verified per-video native Face artifacts; SourceID-capable native Text artifacts; `analysis.text_pipeline.postprocess` without collision with legacy `analysis.text`.

- [ ] **Step 1: Write failing import, naming, and spreadsheet-boundary tests**

  Add tests proving both CLIs import and show help without optional ML packages, owner/env/Java namespaces use `multimodal-emotion-analysis`, no fixed `POLIT` category or `political_proportion` exists, and hostile CSV/XLSX values are neutralized while signed numbers remain numeric.

- [ ] **Step 2: Run the focused tests and record RED**

  Run the new tests plus `processing/tests/test_io_utils.py`; expected failures are missing modules and the PR's old namespace/default/output behavior.

- [ ] **Step 3: Mechanically port only the audited source/test paths**

  Copy the final PR implementations listed in the specification. Rename `postprocessing` imports/defaults to `analysis`, `preprocessing` to `procurement`, and Java package `com.feelingpolitical.rocksteady` to `ie.tcd.multimodal.rocksteady`. Do not copy the PR application files or excluded tools.

- [ ] **Step 4: Make optional dependencies lazy and output writers safe**

  Import Py-Feat, PyArrow, Whisper, and Java/RockSteady only inside readiness or execution paths. Route all CSV rows/dynamic headers and XLSX literal values through `neutralize_spreadsheet_value`; keep intended formula cells and strict numeric literals unchanged.

- [ ] **Step 5: Neutralize category and ownership contracts**

  Replace project-specific owners with stable `multimodal-emotion-analysis-*` markers. Make all dictionary categories dynamic; the standard view may include generic sentiment/activation/strength categories but may not require or special-case Political.

- [ ] **Step 6: Reconcile dependencies and notices**

  Add exact native dependency versions exercised by the PR while retaining one Python 3.12 environment. Setup must leave Face/Text honestly not-ready if weights/JAR are absent. Document Py-Feat/checkpoints, Whisper, Torch/TorchCodec, PyArrow, FFmpeg, JDK, and external RockSteady boundaries without asserting redistribution rights.

- [ ] **Step 7: Run engine suites and commit**

  Run every ported face/text/postprocessing/shared-I/O test, both CLI help/readiness paths, setup verification, compilation, and `pip check` when available. Commit with subject `feat: port native face and text engines from PR 3` plus exact PR source and Jiaming Liu co-author trailers.

---

### Task 2: Bind native processing to catalogs, reusable Analysis profiles, and the current UI

**Files:**
- Create: `processing/catalog_context.py`
- Modify: native Face/Text pipeline, manifest, output, CLI, and tests from Task 1
- Create: `analysis/native_face.py`
- Modify: `analysis/text_results.py`, `analysis/combined_summary.py`, `analysis/workflow.py`, `analysis/metadata.py`, relevant tests/docs
- Modify manually: `application/backend.py`, `application/launcher.py`, `application/static/index.html`, `application/static/app.js`, `application/static/styles.css`, application tests/browser harness
- Modify: `README.md`, `docs/RESEARCH_METHODS.md`, `docs/RELEASE_READINESS.md`, modality READMEs, `analysis/outputs.md`, `analysis/CALCULATIONS.md`

**Interfaces:**
- Consumes: Task 1 CLIs/artifacts; `processing.audio_analysis.audio_pipeline.source_context` bounded sidecar functions; procurement manifest `output_mapping`; current `AnalysisProfile` and source metadata contracts.
- Produces: `CatalogProcessingJob(source_id, speaker, speaker_display, media_path, relative_output, source_context, catalog_sha256, user_metadata, system_metadata)`; native Face/Text run roots carrying exact sidecars; profile-aware native readers; launcher endpoints and nested Face/Text screens.

- [ ] **Step 1: Write failing catalog-discovery tests**

  Cover pooled and named speakers, arbitrary Country/Language/Gender metadata, repeated links with distinct SourceIDs, selected subsets, canonical output only, cache/raw exclusion, and rejection of missing/duplicate/tampered/stale contexts or catalog digests.

- [ ] **Step 2: Implement the shared catalog job adapter**

  Reuse the existing bounded sidecar snapshot/validation. Discover catalog inputs exclusively from selected manifest rows and `source_context.json`; use legacy recursive discovery only when no sidecar pair exists. Publish the exact source sidecar pair at each native run root.

- [ ] **Step 3: Bind Face and Text artifacts to SourceID**

  Put SourceID, raw/display speaker, catalog digest, arbitrary metadata, content identity, and output mapping into every native per-video/run manifest and readable index. Text language precedence is row `system_metadata.youtube_language`, explicit user selection, then blank; researcher `Language` remains ordinary metadata.

- [ ] **Step 4: Write failing native Analysis tests**

  Cover primary-face-only aggregation, seven Py-Feat emotions, blank unsupported metrics, exact scale conversions, provider separation, native arousal/valence, SourceID-grained Text aggregation, canonical sentiment headers, Text Valence formula/range, metadata filters/sorts/groups, and repeated profile runs without processing-output mutation.

- [ ] **Step 5: Implement native Analysis readers and workbook sections**

  Add a `Py-Feat / Native Face` provider and source-grained Text reader. Extend Measure Guide and final workbook sections without blending providers. Rename the legacy five-slot constant to an explicit minimum-layout compatibility value and ensure native sources use actual profile counts.

- [ ] **Step 6: Write failing backend/launcher/UI tests**

  Cover Face run/check/model-preparation and Text run/options endpoints; file/folder and catalog selection; selected SourceID/digest authorization; lexical Windows junction handoff; progress/stop/open-output; honest missing-dependency gates; current security headers; Trinity logo; invalid-link containment; and desktop/narrow screen behavior.

- [ ] **Step 7: Manually integrate the PR controls into the current application**

  Enable the existing Face/Text Processing tiles and add focused nested screens. Preserve current app structure and use DOM `textContent`; never paste the PR's old application files over the destination. Keep native Face provider wording distinct from iMotions/AFFDEX and allow native Text outputs to proceed into Analysis.

- [ ] **Step 8: Update researcher documentation**

  Document input/output trees, SourceID/metadata semantics, model/provider differences, ranges/formulas, readiness/install steps, external RockSteady requirement, profile reruns, and limitations. Credit PR 3/Jiaming Liu and retain the existing project attribution.

- [ ] **Step 9: Run full verification and exact-diff review**

  Run the entire repository suite with an external basetemp, real Edge desktop/narrow harness, compilation, Node syntax, CLI help/readiness, setup verification, `git diff --check`, secret/political/path/output scans, protected OpenSMILE hash checks, and an exact-diff security scan/review. Resolve all Critical/Important findings.

- [ ] **Step 10: Commit locally and leave unpushed**

  Commit with subject `feat: connect native processing to source manifests and Analysis` plus exact PR source and co-author trailers. Verify a clean/ignored-clean workspace, exact commit count/history, and no destination remote refs or push activity.
