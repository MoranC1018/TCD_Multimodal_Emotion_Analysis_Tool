# Real CLI acceptance

`real_cli_e2e.py` is an opt-in acceptance harness. Pytest does not collect it.
It invokes the public `python -m application.cli` interface in real subprocesses,
then reads and decodes the resulting artifacts. It does not replace CLI routes,
command builders, process execution, FFmpeg, OpenSMILE or analysis calculations.

Use the installed project Python environment. Each run requires a **new** output
directory; the harness refuses existing evidence directories.

```powershell
& .\.venv\Scripts\python.exe application/tests/real_cli_e2e.py `
  --phase nonmodel --output C:\ResearchValidation\cli-nonmodel-001

& .\.venv\Scripts\python.exe application/tests/real_cli_e2e.py `
  --phase models --output C:\ResearchValidation\cli-models-001 `
  --model-video C:\ResearchFixtures\face-and-speech-15s.mp4
```

Run from the checkout being assessed. A Python environment in another checkout
can be supplied by its absolute executable path; the harness and its subprocesses
use the checkout containing this script. `--phase all` combines both phases and
requires `--model-video`.
Jobs retain the normal 90% system RAM guard. If a measured host resource budget
requires a different limit, `--max-ram-percent` accepts the same 10–95% range as
the application and records the explicit value in each job and acceptance report.
The guard remains active; it may pause and stop inference under sustained load.

## Coverage

The non-model phase generates a 12-second tone/video fixture and clearly labelled
fabricated imported Audio statistics. It checks:

- Public schema, stage schema, settings, source inspection and procurement doctor.
- Dry-run and validation commands that create no run or engine outputs.
- Full procurement followed by OpenSMILE through an explicit output reference;
  real decoded durations, three exact 6-second/3-second-stride windows, 88 finite
  acoustic features and deliberately absent emotion-model values.
- Focus selection with source intervals 1–3 and 6–8 seconds, including a decoded
  black/silent one-second gap and a five-second stitched output.
- Standard 50% sampling into a six-second result.
- Catalog procurement and subsequent sealed-catalog inspection.
- Unknown options, wrong types and invalid ranges rejected before run creation.
- Corrupt-media failure in the real Audio child, a nonzero public exit code and
  no execution/output from the next workflow step.
- A copied job directory containing spaces and Unicode, with paths resolved
  relative to the copy rather than the current working directory or original.
- Imported Audio analysis grouped by Country, source/title ordering, exact
  fabricated means, probability sheets and expected formula references.
- Public status/cancel while a real FFmpeg descendant is alive, exit code 130,
  terminal cancelled state and no surviving observed owned descendant.
- Whole-workflow timeout and exit code 124.
- Input, desktop settings, stored-credential file and EULA-file preservation.

The model phase requires an existing 15-second fixture with both a visible face
and audible speech. The fixture must produce at least 12 detected face samples
at 1 fps and nonempty lexical activation counts. It runs:

1. Catalog Full → native Face → Audio with emotion models → Whisper/RockSteady →
   grouped profile Analysis, as one public JSON workflow with artifact references.
2. Independent source-sidecar equality, 15 Face observations, two 10-second Audio
   windows, acoustic schema and SourceID checks.
3. Raw Audio affine scaling, raw native Face means, integer Text count ratios and
   representative workbook cell comparisons; Country profile and source hash
   binding are checked against the produced catalog.
4. Clean Speaker using the supplied fixture, checking a successful usable result,
   face/voice interval artifacts and at least ten seconds of decoded output.

Model evidence records the actual Audio model and pinned revision, checks its
supported probability columns, and requires unsupported fallback classes to stay
blank. A four-class fallback pass does not validate the preferred nine-class
model. Face checkpoint hashes are independently read from the recorded files;
Whisper checkpoint, runtime and explicit English decoding provenance are checked.

The harness enables offline Hugging Face/Transformers behavior and four native
CPU threads per job. It does not install or prepare models. Before Whisper can
run, it verifies the existing cached `small.pt` against Whisper's registry hash,
because Whisper's own downloader does not honor `HF_HUB_OFFLINE`. Native doctor
commands must report ready. Use the normal explicit setup/model preparation
workflow before running this phase.

## Evidence and interpretation

The output directory contains `acceptance.json`, submitted JSON jobs, per-call
commands/stdout/stderr, CLI run directories with effective settings/status/logs,
generated fixtures and analytical artifacts. Each case records passed/failed,
duration and either artifact evidence or a traceback. The harness exits 1 if any
requested case fails. A non-model pass does **not** imply that models were tested.
`source-start.json` and `source-finish.json` record the Git base and Python source
hashes. Compare these when other work may have changed the checkout during a run;
rerun affected acceptance cases after the final changes.

Workbook formulas are inspected for expected references and stored error cells;
the harness does not claim Excel recalculation. These are synthetic operational
checks, not model-accuracy validation, publication approval, installation success
on other machines, or proof that every native option has been exercised.

## Recorded runs

Acceptance evidence is kept outside the repository. Record the tested commit,
runtime, selected phase and final result in the release report after the run.
Earlier failed attempts remain preserved; correcting a harness assumption or a
production defect requires a new output directory and a fresh relevant run.

During Windows integration on 5 September 2026, the normal 90% RAM guard paused
Audio at 91.8% and stopped it after 30 seconds, correctly preserving fail-stop
behavior. The host subsequently had 23.914 GiB total and 3.803 GiB available.
The planned final acceptance budget is explicitly 94%, retaining approximately
1.43 GiB reserve at the threshold, with enforcement and four CPU/native threads.
Whisper registry inspection runs in a short-lived preflight process so the
harness does not retain Torch in memory during child inference.
