# Software release review: 4 September 2026

This review continues the [initial September validation](RELEASE_VALIDATION_2026-09-04.md).
The first review PR contains the original eight repairs and additional
verified defects, regression tests and corrected installation documentation.
The CLI and Audio performance change are reviewed separately. A passing test
suite is bounded evidence, not a guarantee that no defects remain.

## Installation facts

The [installation guide](INSTALLATION_VALIDATION.md) identifies the exact tested
Windows CPU path, prerequisites, installer options, recovery and readiness limits.
The recorded setup scenario used one established Windows host: an intentionally
disabled missing-FFmpeg installation first failed, then a rerun installed the
required shared runtime and passed. This is neither a clean-machine population
study nor an estimate of installation error rate. Python/JDK were already present;
CUDA, other operating systems and other machines need their own acceptance.

## Complete repaired-defect register

Priorities describe the demonstrated impact within the affected workflow.
Software maintainers own these repairs; researchers own the decision to regenerate
or reinterpret previously produced study artifacts. Original research outputs were
preserved. Tests live beside their respective production modules.

| ID | Priority | Demonstrated defect and corrected behavior |
| --- | --- | --- |
| SW-01 | P1 | Raw Audio valence outside nominal 0..1 escaped scaling. Every finite raw value now uses the same affine conversion. |
| SW-02 | P1 | Explicit Whisper language completed transcription then failed provenance validation. Requested language is now bound consistently. |
| SW-03 | P1 | Identical sealed source sidecars copied into different modality folders were rejected. Verified byte-identical pairs are accepted; altered/incomplete pairs remain invalid. |
| SW-04 | P2 | Rounding per-recording statistics biased weighted reports. Calculations retain full precision; display rounding remains separate. |
| SW-05 | P2 | Face cache compared live tuples with JSON lists and unnecessarily reran valid inference. Cache keys now use the same representation. |
| SW-06 | P2 | Brief Windows reader locks failed atomic publication. Bounded retries preserve the old complete file and still report persistent failure. |
| SW-07 | P2 | The Windows launcher accepted negative native exit codes. Only zero is successful. |
| SW-08 | P2 | Terminal browser runs retained running indicators. Completed, failed and stopped states now update all controls. |
| SW-09 | P1 | Single-file Audio could succeed with unavailable requested model layers. Required layer availability is checked before replacing outputs; explicit acoustic-only runs remain supported. |
| SW-10 | P1 | Invalid Audio rerun settings removed valid prior outputs before failing. Workload/model preflight now precedes output changes. |
| SW-11 | P1 | A smaller Audio rerun left stale recordings discoverable by Analysis/full-stack export. Current validated batch membership is authoritative, including nested batches; incomplete/corrupt runs fail closed. Preserved historical files are not silently included. |
| SW-12 | P1 | Categorical inference truncated windows longer than 15 seconds while reporting their full duration. Emotion-enabled windows above the model's supported limit are rejected before processing. Acoustic-only windows may be longer. |
| SW-13 | P1 | Substring filtering discarded legitimate speakers such as Temple Grandin and Rawlings. Temporary-run detection now uses the structural run directory, not speaker names. |
| SW-14 | P1 | A blank interior source header shifted statistics onto another source identity. Missing labels and unlabelled values are rejected rather than reassociated. |
| SW-15 | P2 | A successful report-only Analysis run prevented the next run from archiving its result. Archive validation now respects whether the prior request generated a workbook. |
| SW-16 | P2 | Local catalog snapshots replaced original filename-derived titles with internal source IDs. Isolated snapshots retain the original basename and original metadata meaning. |
| SW-17 | P1 | Fractional counts and negative standard deviations entered inference. Counts are validated as exact nonnegative decimal integers and SDs as finite/nonnegative. |
| SW-18 | P1 | A partial-source profile relabelled an unchanged full-speaker Text aggregate as filtered data. Unreconstructable partial selections now fail; native per-source Text remains filterable. |
| SW-19 | P1 | Resumed Text could publish a different SourceID cohort from its current configuration. The current cohort, catalog and each source binding must match the cached transcription before publication. |
| SW-20 | P2 | A non-object cached Whisper JSON value crashed retry planning and left a running manifest. Invalid cached passes now regenerate, and failed regeneration records failure. |
| SW-21 | P1 | Face used a longer audio/container duration to infer nonexistent video observations. Video-only duration and evidenced frame count now determine sampling; a 2-second video with 4-second audio correctly yields 10 samples and full coverage when all sampled faces are present. |
| SW-22 | P1 | The launcher removed every standard username variable from its child environment. Windows PyTorch then attempted to import the Unix-only `pwd` module and Face failed despite readiness passing in the parent environment. The shared GUI/CLI child policy now preserves the four standard identity variables while still excluding credentials. |
| SW-23 | P1 | Complete video headers bypassed cadence validation. A real variable-frame-rate MP4 labelled frame 48 as 2.5344 seconds instead of its decoded 1.92-second position. Every Face input now receives a streamed timestamp check; nonuniform timing is rejected before inference or publication, including when average FPS, duration and frame count are present. |

Exact regression locations for the new repairs:

- [Audio integrity](../processing/audio_analysis/tests/test_release_integrity.py)
  and [GUI Audio limit](../application/tests/test_audio_window_limit.py).
- [Combined statistics](../analysis/tests/test_combined_summary.py),
  [profile grouping](../analysis/tests/test_profile_workbook.py),
  [workflow archives](../analysis/tests/test_workflow.py) and
  [catalog snapshots](../procurement/tests/test_catalog_runner.py).
- [Text cohort/cache](../processing/text_analysis/tests/test_resume_catalog_and_cache.py)
  and [Face timing](../processing/face_analysis/tests/test_video_timing.py).
- [Actual child environment and credential isolation](../application/tests/test_child_process_environment.py).

The 15-second categorical input limit comes from the
[model author's input contract](https://huggingface.co/tiantiaf/whisper-large-v3-msp-podcast-emotion).
The fallback shares the public model-window limit so changing backend availability
does not silently change the requested protocol. Existing 10-second study windows
are unaffected by this rejection rule.

## Executed checks

At code commit `057cdb12c118dcff79d1077e42d44689227d1e00`, the full suite passed
1,252 tests and 327 subtests in 167.74 seconds. Thirteen tests were skipped because
the Windows account cannot create symbolic links; the real junction checks ran.
Strict browser testing was enabled. These checks completed on 5 September 2026
in Europe/Dublin, following the review started on 4 September.

The separate real-browser acceptance passed all six scenarios: Full procurement,
Focus procurement, acoustic-only Audio, Country-grouped Analysis, invalid media
failure and cancellation of a live process. It used the production HTTP server
and actual subprocesses, decoded media to check duration/black frames/silent gaps,
and checked workbook contents. Inputs and saved configuration remained unchanged.
These browser fixtures do not exercise neural model inference.

`scripts/verify_setup.ps1` passed its installer contract checks, and
`python -m pip check` reported no broken requirements. This is not a new
clean-machine installation trial. The [installation guide](INSTALLATION_VALIDATION.md)
separates earlier installation observations from these checks.

Independent focused reviews reproduced failures first, then tested the repairs
with synthetic inputs and real FFmpeg/OpenSMILE where applicable. A cross-review
ran 70 focused tests against other reviewers' changes. Focused counts are not
added to the full-suite count. The machine-local evidence directory is
`.codex_tmp/release_followup_20260904` in the parent workspace; full-suite logs and
JUnit XML are `pr1-full-03.log` and `pr1-full-03.xml`, browser evidence is
`pr1-browser-02/acceptance.json`, and setup/package checks are
`pr1-verify-setup.log` and `pr1-pip-check.log`.

## Known validation boundaries

- Face sampling uses frame-index/FPS timing and requires a uniform cadence.
  Every probe reads the header and performs a streamed frame-timestamp scan,
  potentially twice for a new processing run, with a 300-second limit per
  FFprobe call. Nonuniform or unavailable timing is rejected, including complete
  headers. This validation adds scan time; variable-frame-rate inference is not
  supported. See the [Face contract](../processing/face_analysis/README.md).
- Invalid Audio preflight preserves prior results. Unexpected failures after
  valid single-run preflight do not provide transactional restoration of all old
  files. Managed batch state prevents importing incomplete batch results. An
  explicitly selected historical per-video folder remains a deliberate legacy
  import, outside its ancestor batch's selected scope.
- Runtime readiness does not prove every optional model can load. The tested
  categorical backend is the four-class SUPERB fallback. Unsupported categories
  remain missing; nine-class inference and the gated PyAnnote path are unverified.
- The previous advisory disposition remains applicable; this change does not
  claim a clean vulnerability scan. The optional checkpoint chain still needs
  the separate provenance review described in the initial validation report.
- Synthetic software acceptance does not measure classifier/transcription
  accuracy, human coding agreement or study validity. Excel formulas are checked
  structurally, without claiming Excel recalculation.

The manuscript/data issues identified in the initial reconciliation remain open.
Software repairs do not establish historical source lineage or authorize paper
publication. Authors must reconcile the changed numbers and protocol, unresolved
cross-modal sources, historical Text provenance and unfinished manuscript content
before making the scientific release decision.
