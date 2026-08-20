# Automated Tests

This folder contains developer-facing unit and contract tests for the audio
pipeline code.

Run them from the `Audio_Analysis` root:

```powershell
python -m unittest discover -s tests
```

These tests use mocks and small fixtures to check path handling, batch
discovery, CSV schema, skip-model behavior, model-output contracts, and
OpenSMILE command construction. They are separate from `qa/`, which runs slower
real-media verification.
