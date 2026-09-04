# Real launcher browser acceptance

This opt-in suite uses the production launcher HTTP server on an ephemeral
loopback port, Chromium/Edge controlled by Playwright, and actual procurement,
audio, and Analysis subprocesses. It does not mock API routes or business
functions. It is separate from the fast `analysis_ui_browser_harness.js`, which
isolates UI contracts with mocked responses.

Run from the repository root after installing its runtime dependencies. Provide
the installed Playwright package directory and browser executable:

```powershell
.\.venv\Scripts\python.exe application/tests/real_launcher_browser_e2e.py `
  --output C:\temp\mea-browser-acceptance-NEW-RUN `
  --playwright C:\path\to\node_modules\playwright `
  --browser 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' `
  --node 'C:\Program Files\nodejs\node.exe'
```

The output directory must be new or empty. The suite generates a 12-second
test-pattern video with a tone, an invalid MP4 for failure testing, and clearly
labelled fabricated statistics with source metadata. `--video` can instead copy
an existing 12-second tone video. FFprobe checks supplied fixtures for a duration
within 12 ± 0.2 seconds and both video/audio streams before any test state or
pipeline is created. FFmpeg/FFprobe and OpenSMILE must be available;
no model download is requested.

The suite redirects only the EULA/settings path resolvers and uses an isolated
credential-store root. It does not launch the desktop single-instance wrapper,
read user credentials into the browser, or stop another launcher. Fingerprints
verify the original settings, backup, EULA, and stored credential files remain
unchanged. All child processes and the server belong to this invocation.

Acceptance checks cover:

- Local-file scan and Full procurement with playable video/audio streams and
  the expected duration.
- Browser preview and Focus selection of 1–3 and 6–8 seconds, joined with a
  one-second gap; decoded samples verify that the gap is black and silent.
- OpenSMILE eGeMAPS processing with emotion models disabled; acoustic values
  must be finite and emotion columns must remain blank.
- A real decoder failure, a subsequent start that restores running controls,
  and stopping that live child through the UI.
- Imported synthetic Audio descriptive statistics grouped by Country through
  the actual Analysis workflow; source titles/means, grouping profile, workbook
  structure, formula references, and absence of stored Excel errors are checked.
- Completed/failed/stopped titles, hidden terminal spinners, disabled terminal
  Stop buttons, and a fully filled completion progress bar.
- Zero browser page errors, successful HTTP requests, expected child exit
  statuses, and unchanged input fixtures.

`acceptance.json`, `browser-evidence.json`, launcher/browser logs, screenshots,
and output media/workbooks are retained in the output directory. Intentional
decoder failure and cancellation appear in the logs and are successful tests.
The ephemeral bootstrap-token file is removed at shutdown.

This validates launcher integration and artifact contracts, not the scientific
accuracy of emotion models. The statistics are synthetic, not inference results.
Workbook formulas are inspected without recalculating them in Excel. Native
Face/Text terminal presentation also has regression assertions in the existing
UI harness; this suite does not run those models or the external iMotions app.
