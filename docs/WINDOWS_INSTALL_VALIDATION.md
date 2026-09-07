# Isolated Windows installation validation

The `Windows installation and acceptance` workflow tests a new checkout and
project environment on GitHub-hosted Windows Server 2022 and 2025. These runners
contain development tools and run as administrators. This is fresh-environment
installation evidence on the recorded server images, not proof of an untouched
Windows 11 desktop installation or normal-user/UAC behaviour.

Use the separate [Windows Sandbox procedure](WINDOWS_SANDBOX_TESTING.md) for a
disposable desktop check. The existing [installation guide](INSTALLATION_VALIDATION.md)
describes the supported user-facing installation.

## What each hosted job executes

1. Check out the candidate without a project `.venv`, a restored pip/model cache
   or pre-materialized RockSteady LFS bytes. Record OS, image revision, tools,
   administrator state, memory, disk and source commit.
2. Select Python 3.12.10 and Node 22 from the hosted tools. Record/bootstrap
   WinGet separately using verified public Microsoft release artifacts. Prepare
   Playwright 1.62.1 and the hosted Edge browser for testing.
3. Invoke the actual public `scripts/setup.ps1 -TorchRuntime cpu -TextMode Require`.
   It installs pinned dependencies, exact shared FFmpeg, Face checkpoints and
   the tracked RockSteady runtime, and validates Face/Text readiness.
4. Rerun the same installer in that environment. The first installation and this
   rerun have separate logs and exit statuses. The rerun is not a second machine.
5. Run `pip check`, record all installed versions, compare every direct requirement,
   run installer contracts, and call the public CLI component doctor.
6. Run the existing non-model public CLI acceptance, the full regression suite
   with strict browser mode, the installation harness/configuration checks and
   all six production browser acceptance scenarios.
7. Compare every tracked source file before/after. Normal files use raw SHA-256;
   Git LFS files use their clean-filter Git identity so exact pointer hydration
   is allowed. A changed LFS payload changes that identity. Setup additionally
   verifies the expected RockSteady size and SHA-256. The identity check supplies
   its LFS filter configuration per command, without changing saved Git settings.

The common harness is [test_windows_install.ps1](../scripts/test_windows_install.ps1).
It refuses an existing `.venv` and requires a new evidence directory outside the
checkout. Existing evidence is never reused. Hosted execution requires both
`GITHUB_ACTIONS=true` and `RUNNER_ENVIRONMENT=github-hosted`; persistent self-hosted
runners are rejected. These checks prevent accidental use on an ordinary host;
they are not a security boundary against someone deliberately changing the script
or environment.

## Run and read the evidence

The workflow runs on pull requests to `main` and pushes to `main`. A manual
`workflow_dispatch` becomes available after the workflow exists on the default
branch. Both matrix jobs run even if the other fails. Each has a 100-minute limit.
No project dependency or model cache is restored between jobs.

Open **Actions > Windows installation and acceptance**, select the execution,
then download each `windows-install-<image>-<run>-<attempt>` artifact. The final
upload step runs after success or failure; GitHub cancellation/infrastructure
loss can still prevent artifact delivery. Retention is 30 days, so archive an
accepted release's evidence before it expires. GitHub's **Set up job > Runner
Image > Included Software** link identifies the exact hosted image inventory.

The artifact contains:

- `hosted-os.json`, `hosted-disks.json`, `hosted-image.json` and
  `pre-bootstrap-tools.json`: image baseline before prerequisite selection.
- `bootstrap-evidence/`: actual WinGet baseline, pinned download hashes,
  installation status and logs.
- `validation/baseline.json`, `summary.json`, `source-finish.json` and
  `direct-pins.json`: source/runtime identity and the final bounded outcome.
- `validation/*.command.json` and corresponding logs: exact commands, exit codes,
  elapsed times and failures. A running record without completion is incomplete.
- CLI/browser acceptance JSON, synthetic outputs, browser screenshots and JUnit
  reports. Large package downloads, model caches and pytest scratch files are
  outside the uploaded evidence or explicitly excluded.

A failed setup prevents later application checks in that job. Diagnose the
earliest failed stage before drawing conclusions about stages that never ran.
Retain the failed attempt and use a new run after correcting its cause. Do not
silently replace failed evidence with a successful rerun.

## Interpretation

Face checkpoint preparation and native decode/import readiness are part of setup.
The additional CLI/browser acceptance here performs real media and acoustic
processing, but not Audio emotion-model inference or Whisper transcription.
Component doctors establish their documented runtime readiness, not successful
inference for every optional model. The separate
[model acceptance harness](../application/tests/REAL_CLI_ACCEPTANCE.md) records
the additional fixture/cache requirements for those checks.

These results do not establish CUDA support, the preferred nine-class Audio
backend, gated model access, emotion recognition accuracy, Excel recalculation,
all user installations or paper-publication approval. Record any skipped tests.
Two hosted images and installer reruns do not establish a population installation
error rate. A green workflow means only that its named gates passed for its
recorded source, dependencies, image and fixtures.

Primary platform references: [GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners),
[runner variables](https://docs.github.com/en/actions/reference/workflows-and-actions/variables),
and [Windows Sandbox and WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/#install-winget-on-windows-sandbox).
