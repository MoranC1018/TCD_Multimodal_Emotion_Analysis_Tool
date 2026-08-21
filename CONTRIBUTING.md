# Contributing — Multimodal Emotion Analysis Tool

Thank you for contributing to this public research-software project. It was
developed by Conor Moran and Jiaming Liu, with academic direction from
Professor Khurshid Ahmad and Dr Tracey Hilton at the School of Computer Science, Trinity College Dublin, the University of Dublin. See `AUTHORS.md` for
the project attribution record.

Generated values are machine outputs, not diagnoses or direct evidence of a
person's internal state. Contributions must keep interpretation and action as
the researcher's responsibility.

## Set Up A Development Checkout

Clone the repository using its current public URL, enter the checkout, and
create a repository-local Python environment:

```powershell
git clone <repository-url>
cd <repository-directory>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Install FFmpeg separately and place `ffmpeg` and `ffprobe` on `PATH`. The
supported Windows OpenSMILE 3.0.0 distribution is already bundled under
`processing/audio_analysis/opensmile-3.0-win-x64/`; its audEERING Research
License is separate from the project's MIT License.

For optional CUDA acceleration, follow the current PyTorch installation
selector and install matching `torch` and `torchaudio` builds before the
remaining requirements.

## Repository Layout

```text
application/       desktop launcher, local API, and interface
procurement/     source review, sampling, and Clean Speaker procurement
processing/        audio execution plus face/text import tooling
analysis/    source feeders and shared statistical reporting
docs/              research methods and release evidence
tools/             bounded audits and maintenance utilities
```

The package directory names `procurement` and `analysis` are part of
the current public interface. Do not rename them in an unrelated change.

## Contribution Workflow

1. Create a focused branch from the current maintained branch.
2. Keep source, documentation, and tests aligned with the behaviour changed.
3. Add regression coverage for executable behaviour, not brittle exact prose.
4. Run the narrowest relevant tests, then the root suite when the change can
   affect multiple stages.
5. Inspect `git diff` and stage only the intended paths.
6. Open a review request that states the user-visible change, validation run,
   remaining limits, and any data or licensing implications.

Useful baseline checks from the repository root are:

```powershell
python -m pytest -q
node --check application\static\app.js
python -m compileall -q application procurement processing analysis tools
```

Real-media validation must use data the contributor is permitted to process.
Do not commit validation media or generated reports.

## Data, Credentials, And Third Parties

Never commit API keys, access tokens, browser cookies, participant data,
downloaded media, model weights, caches, logs, or generated analysis outputs.
Use synthetic or properly authorised fixtures and remove personal information
from issue reports and screenshots.

The root MIT License covers only project-authored material. Preserve the
complete OpenSMILE `LICENSE` and `licenses/` tree, and review
`THIRD_PARTY_NOTICES.md` before changing or packaging dependencies. External
text-analysis software, downloaded models, FFmpeg builds, and other tools are
not made redistributable by this repository.

## Research And Release Boundaries

- Face and Text processing are optional local pipelines and must report missing
  model or runtime dependencies before creating outputs.
- Clean Speaker remains experimental and must fail closed when model-backed
  evidence is unavailable.
- Model outputs require study-specific validation and human review.
- Copyright, consent, ethics approval, privacy, secure retention, model terms,
  and interpretation remain the researcher's responsibility.
- Institutional affiliation does not imply endorsement of a contribution or
  its findings.
