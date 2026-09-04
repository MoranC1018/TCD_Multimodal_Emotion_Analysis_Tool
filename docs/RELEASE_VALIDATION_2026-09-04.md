# Release validation — 4 September 2026

**Software regression and tested Windows CPU workflows pass. The official
research-paper release is not approved.** Independent manuscript reconciliation
found unresolved dataset lineage, historical execution provenance, protocol,
numerical and editorial issues. A green software suite cannot close those gates.

The starting feature branch had already merged through PR #4. Validation moved
to main at `ada3bf87e602a4787613fcad36075b8e3bd99bdc`, then to the local branch
`codex/release-readiness-20260904`. This work did not push, merge, tag or publish.
Private manuscripts, emails, research files and detailed review evidence remain
outside this sanitized repository.

## Executed acceptance

| Gate | Observed result |
| --- | --- |
| Fresh supported Windows installation | Python 3.12.1 CPU environment created by `scripts/setup.ps1`; shared FFmpeg 8.1.2 installed; exact tracked RockSteady LFS object and offline Py-Feat weights validated. Subsequently applied the tested security dependency updates below. |
| Final dependencies | 22/22 direct pins match; `pip check` reports no broken requirements. Exact installed inventory is in `validation/windows-cpu-2026-09-04.txt`. |
| Complete regression suite | **1,162 passed, 321 subtests passed, 13 skipped**, 154.39 seconds. Covers application, procurement, processing, analysis and tools. Strict browser mode was enabled and the browser test executed. |
| Installer contracts | `scripts/verify_setup.ps1` passed argument, discovery, recovery, PATH, WinGet and RockSteady integrity checks. Its intentional mocked errors are expected tests. |
| Live browser and real subprocesses | Six runs passed acceptance: Full, Focus, OpenSMILE, grouped Analysis, deliberate invalid-media failure, live-child cancellation. Twelve HTTP POSTs succeeded; no browser page errors. Original configuration, credentials, EULA and input fixtures remained unchanged. |
| Media artifacts | Full output has playable video/audio; Focus contains both selected intervals and a decoded black/silent gap. OpenSMILE-only run has three windows and 264 finite acoustic values, with emotion outputs blank. |
| Real model processing | Py-Feat: 15 sampled frames with faces. Audio: two windows through SUPERB four-class fallback plus audEERING dimensions and eGeMAPS. Whisper small: three transcript segments; native RockSteady: 34 analysed terms. No inference calls were mocked. |
| Full catalog workflow | Actual local catalog procurement, separate Face/Audio/Text pipelines, and a Country-profile workbook complete with identical source sidecars. Nineteen headline cells were checked against raw outputs/construct summaries; formulas and unsupported blanks were checked. |
| Cache/recovery | Real Face re-run skips the validated output. Windows reader locks reproduced WinError 5 before the repair; JSON/CSV retry tests verify recovery and preservation of the previous complete file on persistent failure. |
| Clean Speaker | Offline synthetic fixture: one processed, zero failed/unusable, three voice windows and one approximately 14.39-second selected segment. This exercised the locally available face/voice backend, not the gated PyAnnote fallback. |
| Live downloader | Updated yt-dlp retrieved public metadata and 11 formats without account cookies. The older downloader test-video URL returned unavailable; this was an external fixture failure. No study video was downloaded by this check. |
| Scale | 5,000-file scan: 4.09 s; 5,000-row DOCX scan: 11.50 s and 128.01 MiB peak traced Python memory. Representative Focus request capacity: 6,177 segments below the 2 MiB limit. |
| Source payload | Tracked text scan found no high-confidence secret patterns. Project/OpenSMILE/component notices remain present. This bounded scan does not establish absence of all secrets or binary vulnerabilities. |

The 13 skipped cases require Windows symbolic-link privileges unavailable in
this session. Real junction boundary tests executed. Supported CPU execution was
tested; this run does not certify CUDA, other operating systems, iMotions GUI
operation, model accuracy, arbitrary external adapters, or Excel formula
recalculation. Synthetic inputs establish software behavior, not scientific
measurement validity. The study uses imported iMotions/AFFDEX and historical
four-class Audio; native Py-Feat is a separate provider. The preferred nine-class
Audio backend was unavailable and its fallback was explicitly recorded.

## Defects repaired

| ID | Priority | Trigger, resulting behavior and evidence |
| --- | --- | --- |
| SW-01 | P1 | Raw Audio valence outside nominal 0..1 previously escaped scaling. All finite raw values now use `(v * 200) - 100`; an adapter regression covers undershoot, ordinary values and overshoot. |
| SW-02 | P1 | Explicit Whisper language completed transcription but failed manifest validation. Validation now binds the requested language and rejects a different one; actual English pipeline and en/fr/default regressions pass. |
| SW-03 | P1 | Catalog-bound pipelines copied identical provenance into separate folders, which Analysis rejected by path identity. Both validated sidecars must now match byte-for-byte, with the expected manifest SHA-256; altered/incomplete pairs and aliases still fail. Actual three-modality profile import passes. |
| SW-04 | P2 | Per-recording two-decimal statistics biased weighted workbook values. Descriptive CSVs retain float precision; a real report-to-workbook regression changes an incorrect displayed 1.33 to 1.34. Presentation remains two decimals. |
| SW-05 | P2 | Face resume compared JSON arrays with live tuples and recomputed valid outputs. Cache comparison uses the same JSON representation and still invalidates changed SourceIDs. |
| SW-06 | P2 | A brief Windows reader lock could fail atomic JSON/CSV publication. Bounded replacement retries preserve atomicity and propagate persistent/non-retryable errors without losing the old file. |
| SW-07 | P2 | Windows launcher treated negative native exit codes as success. It now accepts only exit code zero. A missing-DLL regression verifies fallback to a healthy interpreter; venv test fixtures use the base interpreter correctly. |
| SW-08 | P2 | Completed/failed/stopped browser runs retained running text, spinner and Stop state. All run screens now reflect terminal status and restore running state on retry; real browser regressions cover success, failure and cancellation. |

## Dependency advisory gate

Updated yt-dlp from 2026.6.9 to **2026.7.4** and Transformers from 4.46.3 to
**4.53.3** (tokenizers 0.21.4). Isolated real Face and Audio inference passed
before adopting Transformers; both exported data tables were identical to the
baseline on the comparison fixture. Final regression and readiness tests passed
after installation. The yt-dlp fix is documented in its
[upstream advisory](https://github.com/yt-dlp/yt-dlp/security/advisories/GHSA-6v4j-43gg-vj32).

The refreshed advisory scan still reports **16 records across three packages**.
Independent reachability review is retained privately; package version matches
are not proof of an exploitable application path. The optional PyAnnote-to-
Lightning checkpoint chain needs transitive checkpoint provenance review or a
validated upstream fix before certifying that fallback. No compromised model or
exploit was observed. This release does not claim an all-clear vulnerability scan.

## Paper reconciliation gate

The independent reviewer checked the latest manuscript supplied on 4 September,
the exact emailed workbooks, 60 Face exports, 60 Audio recordings and their
acoustic outputs, and 60 Text segment files. Archived workbooks reproduce
528 numeric and 231 formula cells each; all 81 checked manuscript Table 4 cells
match those historical workbooks, including their old errors.

Corrected Audio reports were regenerated for all 60 recordings. Independent
raw calculations agree with all 420 recording means and 84 Audio speaker means
per workbook to within 2.85e-14. These corrections do not establish valid source
lineage. Candidate workbooks retain archived Face/Text and are provisional.

Publication remains blocked by six cross-modal timeline/source discrepancies,
explicitly unverified historical Text execution, unresolved recording identities,
unfinished manuscript sections, and a historical tail-window protocol differing
from current behavior on 31 recordings. Authors must also incorporate corrected
numbers, explain nominal scales/weighting/missingness, and repair diagrams and
layout. Private review records contain exact evidence, owners and acceptance
requirements. Original research files and the manuscript were preserved.

## Repeat the software checks

Use a clean supported setup and an empty evidence directory outside the repo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -TorchRuntime cpu -TextMode Require
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:MEAP_STRICT_BROWSER_TESTS = '1'
$env:MEAP_TEST_NODE = 'C:\Program Files\nodejs\node.exe'
$env:MEAP_TEST_PLAYWRIGHT = 'C:\path\to\node_modules\playwright'
$env:MEAP_TEST_BROWSER_EXECUTABLE = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
.\.venv\Scripts\python.exe -m pytest application procurement processing analysis tools -q -ra --junitxml=C:\evidence\regression.xml --basetemp=C:\evidence\pytest-temp
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_setup.ps1
```

Run the separate real integration suite using
[Real launcher browser acceptance](../application/tests/REAL_BROWSER_ACCEPTANCE.md).
It includes artifact checks and retains logs/screenshots. The package inventory
is evidence of this run, not a replacement for the installer or a portable
cross-platform lockfile. Raw logs, model hashes, private manuscript analysis and
all intermediate failed/repaired probes are retained outside the public tree.
