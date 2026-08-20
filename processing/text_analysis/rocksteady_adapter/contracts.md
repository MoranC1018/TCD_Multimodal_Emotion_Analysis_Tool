# RockSteady Adapter Contracts

## Input and output

The integrated pipeline supplies an authoritative inventory and uses:

```text
<Speaker>/<Video>/<Video>__segment_NNNNNN.txt
```

The legacy `<Country>/<Speaker>/<Video>/...` identity remains accepted. Segment
numbers must be unique and contiguous from 1. Inventory-backed batch output
mirrors the complete identity and writes `<Speaker>/<Video>.csv` or the legacy
three-level equivalent. A direct Video input writes the exact `.csv` path
supplied to `--output`; standalone discovery without an inventory retains the
legacy canonical three-level contract.

When `--inventory` is supplied, every input video must also have a valid
`.prepare_manifest.json`. The adapter verifies the exact identity set, selected
Whisper source hash, segment mapping, per-video manifest hash, and recomputed
segment-content digest before Java starts.

Every segment produces exactly one row. The CSV starts with
`Title,Date of First Article,Articles,Terms,URL`; `Title` equals the segment
filename stem. Category fields must be finite numeric values and order must
match the input. Non-empty Total or Percentage input may not silently produce
zero Terms.

## Runtime and configuration precedence

1. Explicit CLI flags.
2. Ignored `config.local.json` values.
3. `MULTIMODAL_EMOTION_ROCKSTEADY_HOME`.
4. `<repository>/external/RockSteady`.

Configuration covers the runtime and JAR, dictionaries and combination, Java,
heap limits, timeout, analyser, value type, categories, and threads. RockSteady
0.4 makes only the Simple analyser safe to select.

## Dictionaries and categories

The default is only embedded General Language English. `merge` unions category
membership; `override` gives later dictionaries precedence for matching terms.
Dictionary order, source, path, and content/JAR fingerprint participate in
resume identity. Category matching is case-insensitive and rejects unknown or
ambiguous names; output order is deterministic and alphabetical.

## Completion, resume, and failures

For every video the adapter writes a `.partial` CSV, validates schema, count,
identity, ordering, and numeric values, atomically replaces the final CSV, then
writes `_manifests/<Country>/<Speaker>/<Video>.csv.manifest.json`. Resume
requires both a valid CSV and an
exact matching fingerprint. Failures retain earlier valid output, do not stop
unrelated videos, and make the command exit non-zero. Batch roots are exact
atomic snapshots: no failed/partial snapshot becomes visible. The output root
receives `_manifests/rocksteady_run_manifest.json` summarising the batch and
recording the adapter source, JAR, dictionaries and settings. A failed or
interrupted attempt is preserved outside disposable staging in the owned hidden
sibling `.<output-name>.rocksteady-run-history/`. Legacy
`<Video>.csv.manifest.json` files beside CSVs remain readable for resume.

Dry-run is a read-only preflight: it requires the real JAR and Java runtime,
loads and combines the configured dictionaries through the Java bridge,
validates requested categories against the combined dictionary, validates all
segment inputs, and reports derived CSV paths. It writes no CSV or manifest.
Global configuration failures abort before video processing. Per-video failures
print a concise root cause and manifest location while retaining the full error
in the manifest.

## Compatibility requirement

The bridge uses RockSteady's own dictionary, analyser, bucket, table-model, and
CSV-output classes. Tests cover deterministic repeat runs and a real Java smoke
run when the licensed runtime exists. Current text postprocessing requires
Total values.
