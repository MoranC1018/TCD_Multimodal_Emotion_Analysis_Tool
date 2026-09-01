# RockSteady Adapter

This adapter runs RockSteady 0.4 headlessly for the multimodal emotion tool. It accepts
one prepared Video directory or a prepared batch and writes validated CSV
output without desktop GUI automation. The integrated Text pipeline supplies
an authoritative inventory whose identities may be the current
`<Speaker>/<Video>` form or the legacy `<Country>/<Speaker>/<Video>` form.

## Runtime setup

RockSteady is third-party, separately licensed software and is not covered by
the repository's root MIT License. The project-authorized application JAR is
versioned with Git LFS at:

```text
external/RockSteady/
  rocksteady-desktop-application-0.4#2018-05-16.jar
```

During setup, a missing JAR or LFS pointer triggers a pull limited to this exact
path. The resulting bytes must match the approved 67,417,737-byte artifact and
SHA-256 `02ddb9b418952df4b109fa8ca1e6a59000115af2d4b81aca29d555e28a448534`.
If automatic materialization is unavailable, install Git LFS and run
`git lfs pull` manually. Alternatively set `MULTIMODAL_EMOTION_ROCKSTEADY_HOME`
or create the ignored `config.local.json` beside this README. A JDK with both
`java` and `javac` on `PATH` is required; the Java bridge compiles automatically
when its source or application JAR changes. Compilation is content-addressed,
atomic, and held under a shared build lock, so concurrent Text jobs cannot
corrupt `build/classes`.

## Run

```powershell
# Batch
python -m processing.text_analysis.rocksteady_adapter INPUT_ROOT `
  --output OUTPUT_ROOT

# One Video directory
python -m processing.text_analysis.rocksteady_adapter VIDEO_DIRECTORY `
  --output result.csv

# One Video directory with canonical output derived automatically
python -m processing.text_analysis.rocksteady_adapter VIDEO_DIRECTORY `
  --output-root processing/text_analysis/output/current/rocksteady/all
```

The standalone adapter remains available for specialist use. The primary
complete Text command is `python -m processing.text_analysis`; neither command
is connected to the desktop frontend yet.

With `--inventory`, the output tree mirrors each authoritative `Speaker/Video`
or legacy `Country/Speaker/Video` identity. For standalone inputs without an
inventory, `--output-root` retains the legacy canonical three-level discovery.
The legacy `--output` remains available for an exact single CSV path and as a
batch output root.

Use `--dry-run` to validate discovery, the licensed runtime, dictionary loading,
dictionary merging, and every requested category without analysing the text or
writing CSV/manifest files. It prints each derived output path. Use `--force`
to ignore a matching completed manifest, and `--help` for every option.

For setup/readiness checks that do not require an input or output path:

```powershell
python -m processing.text_analysis.rocksteady_adapter --check --all-categories
```

`--all-categories` explicitly ignores a category filter in `config.local.json`;
the automated Text pipeline uses it for the default dynamic General Language
contract.

## Customisation

Defaults are the working Simple analyser, Total counts, and only RockSteady's
embedded General Language English dictionary:

```text
embedded:affectDictionaries/General Language (En)(2011-07-05).dict.xml
```

Repeat `--dictionary` to add dictionaries. Embedded resources use
`embedded:RESOURCE`; external dictionaries use `file:PATH`. The default
`--dictionary-combination merge` preserves categories from every dictionary;
`override` lets later dictionaries replace matching terms.

Repeat `--category` to select a subset. If omitted, every category is exported
in deterministic alphabetical order. `--value-type` supports `total`,
`percentage`, and `z_score`; current `analysis.text_pipeline.postprocess` expects `total`.

The bundled Stanford POS analyser is not exposed: RockSteady 0.4's method
returns an empty token list. Selecting it would silently create zero-valued
analysis, so the adapter deliberately accepts only `simple`.

## Safety and reproducibility

Each video is written to `<Video>.csv.partial`, validated, and atomically
promoted. Its manifest fingerprints inputs, dictionaries, the JAR, bridge
source, settings, and the promoted CSV content hash. Validation rejects
non-finite values, fractional Total counts, reordered/missing categories and
source-row mismatches. Manifests live in a mirrored `_manifests/` directory
below the output set root, keeping CSV delivery directories clean. Legacy
manifests beside CSV files are still accepted for resume compatibility, but
new runs write only to `_manifests/`. Matching valid results resume safely; one
failed video does not prevent remaining videos from being attempted. The batch
manifest is also stored below `_manifests/` and does not store machine-specific
absolute paths. Its top level records `adapter_source_sha256` alongside the JAR,
dictionary and settings identities, allowing the parent Text pipeline to reject
a result produced by different adapter code.

Batch output roots are published as exact atomic snapshots. If any video fails,
the previous visible snapshot remains unchanged and the failed manifest is
copied first to the hidden sibling
`.<output-name>.rocksteady-run-history/`. This history also survives Ctrl-C;
partial CSVs and the disposable staging tree are removed before the interrupt
returns to the shell.

Configuration errors fail before video analysis. Per-video failures print a
concise actionable reason and the manifest path directly in the terminal; the
manifest retains the complete RockSteady diagnostic output.

See [contracts.md](contracts.md) and [config.example.json](config.example.json).
