# CLI release validation: 5 September 2026

The executable code reviewed here is commit
`9eba2c377686c39dd28805684a5d35c5d3fb27d8`, including the software and installation
repairs in [PR #5](https://github.com/MoranC1018/TCD_Multimodal_Emotion_Analysis_Tool/pull/5).
The CLI adds automation around the existing engines and command builders. It
preserves the GUI, source/provenance checks and scientific calculations. The
[CLI guide](CLI.md) documents all 97 ordinary fields, 13 fixed native routes,
18 job templates, explicit artifact references, resource controls and terminal
results. No runtime dependency was added.

## Executed regression and review

| Check | Recorded result |
| --- | --- |
| Full integrated suite | 1,397 passed, 327 subtests passed, 15 skipped, 181.80 seconds. Strict browser mode was enabled. |
| Production GUI acceptance | All six real-browser/subprocess scenarios passed after the CLI helper changes, with decoded media, grouped workbook, failure/cancellation and input/configuration preservation checks. |
| Public JSON Schema | All 18 job examples pass an actual Draft 2020-12 validator. Review compared 278 schema/runtime cases and corrected null-deadline and default-output mismatches. |
| Independent native-adapter review | All 21 rechecks pass, including literal arguments, paths, credential rejection and protected output boundaries. A separate actual NTFS hardlink check preserves the job and rejects execution before writes. |
| Independent process review | All ten real-child/public-command probes pass: Windows ownership, failed-parent descendants, cancellation, timeout, late reader errors, effective deadlines and lexical junction rejection. |
| Audio sample equivalence | 92 canonical cases and four fallback formats match actual FFmpeg. Source/output aliases are rejected with input hashes unchanged. |
| Final documentation checks | All 22 PowerShell blocks in the five final changed documents parse, 69 local file links resolve, and the repository punctuation contract passes. These checks do not execute every documented integration on every platform. |

Fourteen skipped full-suite tests need Windows symbolic-link privileges that
were unavailable. One case exercises POSIX-style negative native exit encoding
and is inapplicable to this Windows run. Real Windows junction, hardlink and
owned-descendant checks executed. Focused review counts overlap the full suite
and must not be added to its total. GitHub reported no PR check results when
PR #5 was inspected; the evidence above was executed locally on the stated
Windows CPU host.

JSON Schema treats mathematically integral numbers such as `1.0` as integers.
The CLI deliberately requires integer JSON syntax for integer fields, so callers
must emit `1`, not `1.0`. Runtime validation remains authoritative for engine
ranges, provenance and file state; a structural schema pass is not execution.

## Defects corrected during CLI review

These were found and repaired before publishing the CLI PR. The separate
[software register](RELEASE_REVIEW_2026-09-04.md) covers the 23 earlier repairs.

| ID | Priority | Reproduced defect and verified correction |
| --- | --- | --- |
| CLI-01 | P1 | Native credential arguments could be copied into run evidence. Credential flags now fail validation; the existing scoped environment/store path remains available. |
| CLI-02 | P1 | Auxiliary native outputs could target the job, an input, run evidence or an earlier step. Every declared output now receives overlap checks, including existing same-file/hardlink aliases. |
| CLI-03 | P2 | Internal Clean Speaker worker flags bypassed the public output contract. Those internal controls are rejected at the automation boundary. |
| CLI-04 | P2 | Native path rewriting misread subcommand-named folders and argument terminators. Mapping now follows the selected parser and preserves literal positional arguments. |
| CLI-05 | P2 | Embedded Analysis profile and custom DOCX extractor paths used the engine working directory. Validated paths now resolve against the submitted job directory. |
| CLI-06 | P2 | Early path normalization removed a junction before the path guard inspected it. Lexical path validation now precedes normalization. |
| CLI-07 | P2 | A Windows fallback could leave descendants alive after the parent exited. The runner now creates the child suspended, requires an owned kill Job Object and only then starts engine work. Ownership failure terminates the suspended child and fails the run. |
| CLI-08 | P2 | A late output-reader error could still return completed. Final reader state now participates in terminal success/failure. |
| CLI-09 | P2 | A command-line timeout override was absent from effective evidence. Effective, status and result records now retain the actual deadline. |
| CLI-10 | P2 | Schema rejected runtime-supported null deadlines and omitted native output roots. Exported schema now represents those defaults. |
| PCM-01 | P2 | The fast path differed from FFmpeg for positive durations rounding below one sample. Those inputs retain the original FFmpeg path. |
| PCM-02 | P1 | A direct helper call could replace its own source, including through a hardlink. Same-file outputs are rejected before writing. |

Regression sources are [automation tests](../application/tests/test_automation_review_fixes.py),
[stage mapping tests](../application/tests/test_automation_stages.py),
[runner tests](../application/tests/test_automation_runner.py),
[configuration tests](../application/tests/test_automation_config.py) and
[real PCM comparisons](../processing/audio_analysis/tests/test_audio_pcm_windows.py).

## Public CLI and model acceptance

The final all-phase public-command run passed **15 of 15 cases**, with exit code
zero. The Git commit and all **231 Python source hashes** matched before and after
the run. No model calls or engine execution were mocked. The harness exercised
Full/Focus/standard sampling, acoustic processing, source/catalog inspection,
schema/validation, Unicode/copied jobs, grouped imported Analysis, real corrupt
media, live FFmpeg cancellation, timeout and preservation, followed by:

- Catalog procurement through native Face, Audio, Whisper/RockSteady and
  Country-profile Analysis using explicit output references.
- Fifteen sampled Face frames with detected faces and independently verified
  checkpoint hashes; two Audio windows through the actual SUPERB four-class
  fallback, audEERING dimensions and OpenSMILE; 34 analysed Text terms with
  verified Whisper checkpoint and explicit English provenance.
- Nineteen representative workbook cells checked against raw modality outputs,
  with maximum absolute discrepancy `8.4e-12`, and source-sidecar equality,
  catalog/profile hash binding, formula structure and unsupported blank fields.
- Clean Speaker: one processed, zero failed or unusable, with a decoded
  14.4-second selected output.

The source fixture, five protected desktop configuration/credential/EULA files
and generated input fixtures remained unchanged. This synthetic speaking-face
fixture validates operation and numerical transformations, not recognition
accuracy or a real participant study.

The final job explicitly enforced a 94% system RAM limit and four CPU/native
threads. Before it started, the host had 23.914 GiB total and 4.085 GiB available
(82.9% used). An earlier diagnostic run with the normal 90% limit correctly
paused/stopped Audio after sustained memory pressure; it is preserved as a
resource-boundary outcome, not counted as a successful final workflow.

Evidence is `cli_e2e/final-001/acceptance.json`, its source snapshots and per-call
logs beneath the private evidence directory. Text's aggregate pipeline ledger
uses the native engine's shared repository workspace, separate from requested
stage output roots. It was archived byte-identically with original path/run ID
and SHA-256 in `text-aggregate-manifest-evidence.json`. The [CLI guide](CLI.md)
explains that location, unique IDs and same-checkout Text serialization.

## Reproduction and limits

Use [installation and validation](INSTALLATION_VALIDATION.md), the
[real CLI acceptance harness](../application/tests/REAL_CLI_ACCEPTANCE.md) and the
[real browser harness](../application/tests/REAL_BROWSER_ACCEPTANCE.md).
The parent workspace's private `.codex_tmp/release_followup_20260904` directory
contains full-suite log/XML (`cli-full-01`), browser evidence (`cli-browser-01`),
independent adapter/process/schema reports and the separate public CLI runs.
Private media, manuscripts, email contents and detailed study evidence are not
part of the public repository.

[Audio performance](AUDIO_PERFORMANCE.md) records the final public benchmark on
the same unchanged code: median 29.06 seconds with FFmpeg window export versus
27.92 seconds with PCM, a **3.9% observed reduction**. Each of the four ABBA trials
produced 11 model and 11 acoustic rows, exactly equal across variants. Offline
cached models, four affinity cores/native threads and a 94% RAM guard were used;
the 61 resource samples stayed below the RAM limit, with no pauses logged.
The 7.65-second initial model load is excluded. Evidence is retained under
`final-audio-benchmark`, including the public `results/benchmark.json`, source
hashes, environment and independent CSV comparisons.

Earlier comparisons measured 9.3% for the implemented fast path and 11.8% for the
prototype under different execution conditions. These one-host, one-fixture
timings do not establish a general speedup or scientific accuracy. Face and
Text performance were outside this assessment; Face's new timing validation
intentionally adds scan time to reject misleading timestamps.

Native Face requires uniform frame timing. CUDA, the preferred nine-class Audio
backend, gated PyAnnote inference, other operating systems, arbitrary external
adapters and Excel recalculation remain outside the demonstrated acceptance.
The existing optional-checkpoint dependency advisory gate also remains open.
See [initial release validation](RELEASE_VALIDATION_2026-09-04.md) for these
boundaries and the separate manuscript/data reconciliation requirements.
A tested CLI does not resolve historical study lineage or approve publication.
