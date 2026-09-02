# Ranked Construct Comparison Implementation Plan

> Execute in this task. Keep raw source artifacts immutable and validate both
> final 60-record grouping runs independently.

**Goal:** Restore the compact grouped comparison boxes, add ranked per-modality
minimum and maximum columns, scale combined-workbook Text values by 100, and
generate complete country- and ideology-grouped outputs for the same 60
political-speaker recordings.

**Architecture:** The change remains inside the current combined-workbook
postprocessor. Source handlers continue to emit their canonical scales. The
Text sheet applies the requested display/postprocessing factor, construct rows
declare the exactly-once measure taxonomy, source boxes stay formula-linked,
and Min/Max strings are computed from the same numeric speaker cells.

**Stack:** Python 3.12, `openpyxl`, existing analysis workflow CLI, existing
Audio/Video/Text processors, Excel-compatible formula recalculation, and
`@oai/artifact-tool` for final workbook inspection/rendering.

---

## Task 1: Encode the expected comparison contract in tests

**Files:**

- Modify: `analysis/tests/test_combined_summary.py`
- Modify if integration expectations require it: `analysis/tests/test_workflow.py`
- Modify if profile expectations require it: `analysis/tests/test_profile_workbook.py`

1. Replace row-per-measure assertions with grouped-box assertions for the seven
   ordered construct rows, including separate Sentiment and Valence rows.
2. Assert table starts at `A`, `I`, and `Q` for a three-speaker group.
3. Assert each panel suffix is `[blank, Min, Max, blank]` and that the final
   speaker also receives the suffix.
4. Build a deterministic fixture whose Face, Audio, and Text candidates have
   different extrema; assert exact Min and Max multiline ranking strings.
5. Assert all 15 canonical Video measures, all 12 Audio measures, and all six
   Text constructs occur exactly once in the classification contract.
6. Assert imported Text values `0.20` and `-0.25` are written as `20.0` and
   `-25.0` in the combined workbook while source objects remain unchanged.
7. Run the focused tests and confirm they fail for the intended missing
   behavior before implementation.

## Task 2: Implement Text scaling and grouped construct boxes

**Files:**

- Modify: `analysis/combined_summary.py`
- Modify: `analysis/CALCULATIONS.md`
- Modify: `analysis/outputs.md`
- Modify: `analysis/README.md`

1. Add one named Text postprocessing scale constant (`100.0`).
2. Apply it only when values are written to the combined `Text sentiment`
   sheet; do not mutate parsed `TextConstructSummary` objects or source CSVs.
3. Replace `_COMPARISON_ROWS` with the grouped construct mapping described in
   the approved design.
4. Add helpers that resolve speaker-level numeric values and build multiline
   formula-linked modality boxes.
5. Add helpers that choose the per-modality min/max candidate and rank the
   resulting Face, Audio, and Text candidates descending with deterministic
   tie-breaking.
6. Lay out each speaker as four source columns plus four suffix columns:
   blank, Min, Max, blank.
7. Update explanatory sheet copy and the Measure Guide to document `x100`,
   signed-value preservation, and the extrema contract.
8. Run focused tests to green.

## Task 3: Run regression verification

**Files:**

- Verify: `analysis/tests/test_combined_summary.py`
- Verify: `analysis/tests/test_workflow.py`
- Verify: `analysis/tests/test_profile_workbook.py`
- Verify: full repository suite appropriate to the changed postprocessor

1. Run the focused combined-summary tests.
2. Run workflow and profile-workbook tests that import Text or create
   `Construct Comparison`.
3. Run the full test suite.
4. Inspect the git diff for unrelated or accidental changes.

## Task 4: Complete preferred nine-class Audio outputs safely

**Inputs:**

- Existing completed preferred-model outputs under the prior political-speaker
  run root.
- Canonical 60 Audio inputs from the guarded multimodal dataset.

1. Inventory already-complete preferred-model outputs and validate each before
   reuse.
2. Stage or select only missing recordings so the completed outputs are not
   reprocessed.
3. Run one Audio model process with high but bounded CPU/RAM use; do not run
   concurrent large-model workers.
4. Emit progress counts and rolling ETA from completed-record timing.
5. Reconcile the finished import root to exactly 60 unique recordings and all
   nine categorical columns.

## Task 5: Run country-grouped full postprocessing

1. Create a new dated output root; never overwrite the previous run.
2. Process/import all 60 iMotions, preferred Audio, and Text artifacts using the
   current algorithm and country group definition.
3. Generate the combined workbook and associated manifests/reports.
4. Reconcile 12 speakers x 5 recordings and all three modalities.
5. Recalculate and save the workbook using an Excel-compatible engine.
6. Inspect formulas, render the comparison sheet, and verify four country
   sections with three speakers each.

## Task 6: Run ideology-grouped full postprocessing

1. Use the same validated 60 source artifacts and current algorithm.
2. Run with the ideology group definition only after the country run passes.
3. Reconcile Left, Centre, and Right sections with four speakers each.
4. Recalculate, inspect, render, and validate the workbook independently.

## Task 7: Final audit and handoff

1. Confirm exact counts and paths for 60 iMotions, 60 Audio, and 60 Text source
   outputs.
2. Confirm each final workbook contains visible Face/Audio/Text boxes plus Min
   and Max for every speaker.
3. Search final formulas for `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, and
   `#N/A`.
4. Report output paths, validation evidence, residual limitations, and any
   unavailable upstream classes without calling provisional data complete.
