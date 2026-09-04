# Command-line workflows and automation

`python -m application.cli` runs Procurement, Face, Audio, Text, and Analysis through the same request builders and processing engines as the desktop application. A versioned JSON job describes the work; the foreground process writes a separate evidence directory and returns a machine-readable result. The desktop application and the existing module commands remain available.

This guide describes the interface and reproducible commands. Actual acceptance evidence, including the tested model/runtime and remaining limits, belongs in [REAL_CLI_ACCEPTANCE.md](../application/tests/REAL_CLI_ACCEPTANCE.md). A valid job or a green readiness check does not establish model accuracy or paper readiness.

## Start here

Install the repository using the [main installation instructions](../README.md#installation). Run commands from the repository root, using its installed Python explicitly. The examples below use PowerShell and assume the repository has a `.venv` created by setup:

```powershell
$python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $python -m application.cli --help
& $python -m application.cli settings
& $python -m application.cli doctor --component procurement
```

Copy the example jobs into your study's job directory, then replace `C:/Research/TrinityStudy` with your actual local paths. These are templates, not bundled research data. Use absolute paths or keep related files beside the job. Inputs must exist before validation; processing models must be ready before a real run.

```powershell
New-Item -ItemType Directory -Force 'C:\Research\TrinityStudy\jobs' | Out-Null
Copy-Item '.\docs\examples\cli\01-full-local.json' 'C:\Research\TrinityStudy\jobs\full.json'
# Edit full.json to point at your media before continuing.
$job = 'C:\Research\TrinityStudy\jobs\full.json'
$run = 'C:\Research\TrinityStudy\runs\full-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& $python -m application.cli validate --job $job --run-dir $run
if ($LASTEXITCODE -ne 0) { throw 'Job validation failed.' }
& $python -m application.cli run --job $job --run-dir $run --timeout 7200
if ($LASTEXITCODE -ne 0) { throw "Workflow failed. Inspect $run" }
```

The run directory **must not exist**, including as an empty directory. `validate` does not create it, so the same planned path can subsequently be passed to `run`. By default each stage writes to `RUN/outputs/STEP_ID`; a single-stage job uses `main` as its step ID. A catalog Procurement run may create a named child directory: use the returned `output_root` or an artifact reference for downstream stages.

## Commands and their contracts

| Command | Purpose and result |
| --- | --- |
| `run --job FILE --run-dir NEW` | Validate, then execute sequentially in the foreground. |
| `run --job FILE --run-dir NEW --dry-run` | Build a plan without creating the evidence directory or launching a processing pipeline. |
| `validate --job FILE --run-dir NEW` | The same planning operation as `run --dry-run`. |
| `run ... --timeout SECONDS` | Override the job's overall execution deadline. Positive finite seconds. |
| `schema` | Print the JSON Schema, including `x-stage-options`, defaults, and `x-native-options`. |
| `schema --stage face` | Print one stage's ordinary option schema. Use the full schema for `native_options` and references. |
| `inspect source SOURCE [--no-enrich]` | Scan a local input, catalog/DOCX, or supported YouTube URL and report selectable sources/groups. |
| `inspect catalog RUN_FOLDER` | Validate and inspect an existing catalog Procurement output. |
| `inspect analysis-speakers --modality NAME METHOD PATH` | Discover speaker identifiers from Analysis inputs; repeat the modality argument. |
| `inspect analysis-profile --modality NAME METHOD PATH [--source-manifest PATH]` | Discover the associated source manifest, its current SHA-256, metadata fields, and source/speaker IDs. |
| `doctor [--component COMPONENT] [--device DEVICE] [--text-stage STAGE]` | Check installed runtime readiness. Components: `all` (default), `procurement`, `audio`, `face`, `text`, `clean-speaker`. Text stages are repeatable. |
| `settings` | Report resource defaults and whether supported credential environment variables are present. Does not modify desktop settings. |
| `status --run-dir RUN` | Read progress or terminal state, including stale-run detection. |
| `cancel --run-dir RUN` | Request cancellation of a live run. Poll status for actual completion. |

Except for `--help`, commands write one UTF-8 JSON result to stdout. Diagnostics and live child output go to stderr. Save or parse stdout separately:

```powershell
$resultText = & $python -m application.cli run --job $job --run-dir $run 2> 'C:\Research\TrinityStudy\workflow-stderr.log'
$exitCode = $LASTEXITCODE
$result = $resultText | ConvertFrom-Json
$result | ConvertTo-Json -Depth 100 | Set-Content -Encoding utf8 'C:\Research\TrinityStudy\last-result.json'
if ($exitCode -ne 0) { throw "Workflow returned $exitCode with state $($result.state)." }
```

PowerShell creates redirected files in its own current-directory context. Their parent directories must exist. The CLI's internal JSON files are UTF-8; shell redirection encoding depends on your PowerShell version.

## What the CLI covers

| Desktop workflow/control | Automation equivalent |
| --- | --- |
| Source picker, scan, select groups or catalog rows | `inspect source`; `selected_speakers` or `selected_ids` in Procurement; processing `selected_source_ids`. |
| Full, 10% sampling, Focus, Clean Speaker | `procurement` with `mode` `full`, `standard`, `manual`, or `clean-speaker-beta`. |
| Focus video player and interval editor | Supply a validated Focus segment manifest. The CLI does not provide an interactive video editor. |
| Face, Audio, Text processing and their controls | Corresponding ordinary stage options, using desktop defaults; advanced native options below. |
| Text stage selection and restart | `native_options.from_stage`/`to_stage`, retaining verified upstream outputs in an explicit Text output root. |
| Video/Audio/Text Analysis, imported results, combined workbook | `analysis.modalities`, workbook/statistics controls, speaker groups or an Analysis profile. |
| Profile metadata sorting, filtering and groups | `native_options.profile_options` for automatic manifest binding, or a fully bound `analysis_profile`. |
| Resource settings | Per-job `resources`; these do not rewrite saved desktop preferences. |
| Run log, progress, stop | stderr plus per-step logs, `status`, `cancel`, Ctrl+C, and deadlines. |
| Browser previews, thumbnails, opening folders/downloads | Read output paths and open files in the desktop or operating system. No CLI preview UI. |
| Credential entry | Existing credential environment/store; the CLI does not prompt for or print secret values. |
| Advanced module-specific flags | Thirteen fixed `native.*` routes, or invoke the existing module CLI directly. |
| Scheduling | A scheduler invokes the foreground `run` command; there is no built-in scheduler/daemon. |

## Job format, references, and paths

A one-stage job:

```json
{
  "schema_version": 1,
  "stage": "face",
  "options": {
    "source_path": "../media",
    "sample_fps": 5.0,
    "device": "cpu"
  }
}
```

A sequence instead uses `steps`, each containing `id`, `stage`, `options`, optional `native_options`, and optional `timeout_seconds`. See [11-catalog-to-combined.json](examples/cli/11-catalog-to-combined.json). The job may contain `resources` and an overall `timeout_seconds` in either form. Do not combine `steps` with top-level `stage`, `options`, or `native_options`.

The schema version is the integer `1`. Keys are case sensitive, ordinary option names are snake_case, and resource names are camelCase. Booleans and numbers must have their actual JSON types: `false` is not `"false"`, and `1` is not accepted where a boolean is required. Write integer controls as `1` or `8`, not `1.0` or `8.0`: JSON Schema treats mathematically integral numbers as integers, but the runtime additionally requires integer JSON syntax for these fields. Unknown fields, duplicate keys, non-finite numbers, known secret field names, files over 1 MiB, and nesting beyond 40 levels are rejected. Jobs contain 1–100 steps. IDs start with a letter, contain only letters, digits, underscores and hyphens, and are at most 64 characters; IDs must also be unique ignoring case.

An artifact reference occupies the **entire value** of a path field:

```json
{"from_step": "procure", "output": "output_root"}
```

It resolves to an earlier successful step's actual output directory. References are exact-case, cannot refer forward, and cannot select arbitrary filenames. There is no `${...}` string interpolation, environment-variable substitution, parallel graph execution, or implicit dependency discovery. Native `args` also accept a reference object as an entire argument, for example immediately after `--source`. Other arguments remain literal strings; references cannot be concatenated with filenames or embedded in a string.

Path rules:

1. Shell arguments `--job`, `--run-dir`, and `inspect` paths resolve from the shell's current directory.
2. Relative paths inside a job, including native argument paths, paths embedded in native profile JSON arguments, custom extractor paths, and `file:` dictionary paths, resolve from the **job file's directory**, not the repository or run directory. Use `/` or doubled `\\` in JSON Windows paths. Native `--` retains its normal argument-delimiter meaning, and a positional path that happens to match a subcommand name is still resolved in its actual parser position.
3. A separate Analysis profile file's manifest path resolves from that profile file's directory. An inline profile uses the job directory.
4. A complete native Text config's internal paths resolve from that config file's directory. The CLI records its digest and normalizes a private copy for execution. Ordinary Text `native_options.config` accepts only `language_policy`.
5. For Focus manifests, use exact source identities from the scan and absolute local media paths, as the provided manifest example does. Intervals are seconds in the original source and must be within its duration.
6. Local inputs/outputs retain the existing engine rules: no UNC/device paths or linked/reparse aliases, no unsafe input/output overlap, and no bypass of catalog/provenance checks. Path guards inspect the supplied lexical path before link or `..` normalization, so adding parent-directory components cannot conceal an unsafe alias. Catalog files outside their allowed root require the applicable explicit native permission option.
7. Native auxiliary outputs are checked as well as the primary output. They must not overwrite the job, configuration, inputs, evidence files, or earlier steps' outputs. Outputs inside the current evidence directory belong under `outputs/STEP_ID/`; safe, explicit external output roots are allowed. Do not place a native log, output DOCX, download directory, or other auxiliary output alongside `status.json` or `submitted.json`.

Planning reads inputs and may probe media. It suppresses optional YouTube metadata enrichment; it is not a promise that every possible underlying inspection is offline. Steps that need earlier outputs appear as `deferred` and are validated fully only when their upstream outputs exist. A dry run neither proves those deferred stages will succeed nor tests model inference.

## Example jobs

Every linked job is strict JSON. Replace study paths and identifiers, preserve helper files beside the jobs, and run `validate` before execution. Defaults not explicitly overridden are listed in the parameter reference below.

| Example | Intended use |
| --- | --- |
| [01-full-local.json](examples/cli/01-full-local.json) | Full local media Procurement. |
| [02-sampling-local.json](examples/cli/02-sampling-local.json) | Local 10% sampling with a 30-second clip cap. |
| [03-focus-local.json](examples/cli/03-focus-local.json) and [focus-segments.json](examples/cli/focus-segments.json) | Two selected intervals from one local video. |
| [04-clean-speaker.json](examples/cli/04-clean-speaker.json) | Clean Speaker with explicit model, timing, and resource controls. |
| [05-face.json](examples/cli/05-face.json) | Native Face processing on CPU. |
| [06-audio-emotions.json](examples/cli/06-audio-emotions.json) | Acoustic features and categorical/dimensional emotion models. |
| [07-audio-acoustic.json](examples/cli/07-audio-acoustic.json) | OpenSMILE-only Audio with longer windows. |
| [08-text.json](examples/cli/08-text.json) | Complete Whisper → language selection → preparation → RockSteady → postprocessing. |
| [09-text-resume.json](examples/cli/09-text-resume.json) | Resume the last two Text stages in an existing verified Text output root. |
| [10-imported-analysis.json](examples/cli/10-imported-analysis.json) | Combine existing Video/Audio/Text Analysis reports using explicit speaker groups. |
| [11-catalog-to-combined.json](examples/cli/11-catalog-to-combined.json) | Catalog Procurement → Face → Audio → Text → combined Analysis, grouped by catalog Country metadata. |
| [12-metadata-analysis.json](examples/cli/12-metadata-analysis.json) | Sort, filter, and group associated processed inputs with a freshly bound profile. |
| [13-text-language-policy.json](examples/cli/13-text-language-policy.json) and [text-language-policy.json](examples/cli/text-language-policy.json) | Country-specific language selection in the ordinary Text stage. |
| [14-native-text.json](examples/cli/14-native-text.json) and [native-text-config.json](examples/cli/native-text-config.json) | Full native Text configuration with fixed native module invocation. |
| [15-native-imotions.json](examples/cli/15-native-imotions.json) | Expert iMotions Analysis flags in a managed run. |
| [16-catalog-selected.json](examples/cli/16-catalog-selected.json) | Explicit catalog SourceID selection with fresh digest binding. |
| [17-analysis-only.json](examples/cli/17-analysis-only.json) | Produce modality reports without a combined workbook or grouping requirement. |
| [18-native-docx-sampling.json](examples/cli/18-native-docx-sampling.json) | Existing DOCX sampler with explicit output destinations. |

### Procurement: local, catalog, Focus, and Clean Speaker

`full` retains complete selected media; `standard` samples a fraction (`0.10` means 10%, not 10). `max_segment_seconds` controls the cap for sampling. `manual` is the desktop's Focus mode. Its manifest records exact source identity and intervals; the CLI scans again, validates ranges, and records/copies a normalized manifest with its SHA-256. Do not hand-edit a stale digest to force acceptance.

`inspect source` supplies the current selectable identifiers. For a folder, use `selected_speakers` to choose discovered groups. For a CSV/DOCX catalog, use `selected_ids` with SourceIDs such as `source-0001`. Omit the selection to select all discovered catalog entries; an explicitly empty catalog selection is rejected. A provided `catalog_sha256` must match the current scan; otherwise the CLI binds the current digest automatically. Editing a catalog between inspection and running changes the authorized input, so pin its digest when an exact reviewed catalog is required.

```powershell
& $python -m application.cli inspect source 'C:\Research\TrinityStudy\sources.csv' --no-enrich
& $python -m application.cli inspect source 'C:\Research\TrinityStudy\media' --no-enrich
& $python -m application.cli inspect catalog 'C:\Research\TrinityStudy\procurement\catalog-run'
```

Use the catalog format described in the [README](../README.md); Country-based examples require an actual `Country` metadata column. The CLI does not invent missing metadata or speaker identity. A supported YouTube URL can be supplied directly to ordinary Procurement; the real run materializes its DOCX source inside the evidence directory. Downloading still depends on the existing downloader, network, credentials/access, and source availability.

Clean Speaker is `clean-speaker-beta`. Run `doctor --component clean-speaker` first. Face identity and active-speaker confidence thresholds, scan and validation rates, output selection, worker/isolation settings, cooldown and resource controls are all exposed. Reference audio and native `reference_face_dir` must contain appropriate inputs for the underlying engine. Sampling mode uses `beta_output_mode: "percentage"`; the default is `"clean"`. A deterministic `beta_random_seed` concerns the optional one-video selection (`beta_random_one`), not a universal seed for every model and sampler. Inspect the clean intervals and coverage before using their results in a study.

### Face, Audio, and Text

Each ordinary processing stage accepts a local file/folder or a validated catalog Procurement output where supported by its engine. With catalog inputs, omit `selected_source_ids` to select the full authorized run, or provide specific IDs and an optional expected `catalog_sha256`. Do not supply catalog selectors on plain files/folders. No provider is silently relabeled: native Face results remain Py-Feat-derived; Analysis detects their provenance separately from iMotions/AFFDEX.

Native Face requires constant-frame-rate timing. Every input receives a streamed timestamp check before inference, including media with complete headers. Nonuniform timing is rejected, and this validation adds a scan per probe. The [Face contract](../processing/face_analysis/README.md) describes timing, the 300-second FFprobe limit, and provenance when preparing a separate converted input.

Audio defaults to 10-second windows and 5-second strides. Emotion-model windows must be at most **15 seconds**, following the categorical model input contract. For longer windows, set `include_emotions: false`; the ordinary interface permits windows/strides from 0.5 to 120 seconds. Missing, unsupported, or deliberately skipped emotion classes remain unavailable values, not measured zeros. Read the output model/provenance fields and [Audio documentation](../processing/audio_analysis/README.md).

Text has five ordered stages: `transcribe`, `select`, `prepare`, `rocksteady`, `postprocess`. Ordinary jobs run all five unless `native_options.from_stage` or `to_stage` changes the range. Set both to the same stage to run that stage only. A later stage requires the earlier manifests and artifacts with matching source/configuration provenance.

For a staged run, first set `to_stage` to `prepare` and choose an explicit `output_root`, such as `C:/Research/TrinityStudy/processed/text`. For the next invocation, use a **new CLI run directory** and the same Text output root, source, dictionaries, category and language choices; set `from_stage` to `rocksteady`. Example 09 does this. `force_rocksteady` explicitly requests regeneration; it is not a way to make stale upstream data valid. There is no general workflow resume command and no reuse of an existing CLI evidence directory.

The default Whisper model is `small`, and the ordinary Text worker setting is one thread. Empty dictionaries select the embedded General Language (English) dictionary. Empty categories mean all dictionary categories; the stable core view is derived from that canonical run. `all_categories: true` also clears filtering and cannot be combined with a nonempty `categories` list. Custom dictionaries use `embedded:RESOURCE` or `file:PATH`; `merge`/`override` determines their combination.

`default_language_variant` is `eng` or `original`. Country language policy is configured through the helper in example 13. The explicit `whisper_language` is a fallback when catalog system language metadata is blank; it does not overwrite recorded catalog language. Translation and dictionary selection affect the scientific interpretation; retain these settings alongside results.

### Analysis, imports, profiles, and combined output

Each `modalities` entry has exactly `name`, `source_method`, and `source_path`. Names are `video`, `audio`, and `text`, each at most once. Use the canonical Video name; legacy `imotions`/`native_face` aliases cannot be combined with it or each other.

| Modality | `run` input | `import` input |
| --- | --- | --- |
| `video` | Raw iMotions exports or verified native Face processing outputs, requiring statistical Analysis. | Existing provider-compatible descriptive Analysis reports. |
| `audio` | Processed Audio outputs containing `audio_analysis.csv`, requiring statistical Analysis. | Existing descriptive Audio Analysis reports. |
| `text` | Not supported here; run the Text processing stage first. | The validated Text postprocessing output family/root. |

Imports are checked against their actual format/provenance; changing `run` to `import` does not convert an arbitrary CSV into a valid report. A combined workbook requires one of three mutually exclusive grouping inputs:

- `speaker_groups`: legacy explicit groups with `group_id`, `name`, and `speaker_ids`. Use IDs from `inspect analysis-speakers` instead of guessing labels.
- `native_options.profile_options`: metadata/group choices only. The CLI discovers the actual associated source manifest and binds its current path/hash after upstream processing. This is the convenient option for a single multi-step job.
- `analysis_profile`: a complete inline profile object or path to a saved profile JSON. Its manifest path/hash is explicit and must match the source association.

`profile_options` allows `automatic_group_field` (default `null`), `sort_fields` (default `[]`), `manual_groups` (default `[]`), and `metadata_filters` (default `{}`). Manual groups use `id`, `name`, and `members`; each member is `{"type":"speaker","id":"..."}` or `{"type":"source","id":"source-0001"}`. Filters map exact metadata field names to nonempty lists of accepted values. Use discovered metadata values and IDs. Grouping by Country is an explicit analysis choice, not a built-in political or demographic classification.

```powershell
$contextText = & $python -m application.cli inspect analysis-profile `
  --modality video run 'C:\Research\TrinityStudy\processed\face' `
  --modality audio run 'C:\Research\TrinityStudy\processed\audio'
if ($LASTEXITCODE -ne 0) { throw 'Analysis source association could not be verified.' }
$context = $contextText | ConvertFrom-Json
$context.metadataFields | Format-Table
$profile = [ordered]@{
  format_version = 1
  source_manifest = @{ path = $context.sourceManifest; sha256 = $context.sourceManifestSha256 }
  sort_fields = @('Country')
  automatic_group_field = 'Country'
  manual_groups = @()
  metadata_filters = @{}
}
$profile | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 'C:\Research\TrinityStudy\jobs\analysis-profile.json'
```

Then set `options.analysis_profile` to `"analysis-profile.json"`, removing `speaker_groups` and `native_options.profile_options`. This command writes a profile bound to the inspected inputs; it does not run Analysis. Full profiles require all six fields shown. If your inputs have no associated source manifest, use valid legacy speaker groups rather than fabricating one.

`write_combined_workbook: false` supports modality Analysis without groups. Workbook controls include probability sheets, construct comparison, confidence level, headline weighting, and reference values. `reference_overrides` uses canonical sheet/metric keys such as `Video|Joy`; match exact generated metric names. Provider-specific removed Video sheet names are rejected. The calculation contracts and limitations are described in [CALCULATIONS.md](../analysis/CALCULATIONS.md).

## Readiness, credentials, and resource controls

```powershell
& $python -m application.cli doctor --component face --device cpu
& $python -m application.cli doctor --component audio
& $python -m application.cli doctor --component text --text-stage rocksteady --text-stage postprocess
& $python -m application.cli doctor --component clean-speaker
```

`doctor` checks the existing local runtime; it neither installs packages nor downloads model weights. It returns exit 3 if the requested component is not ready. `all` requires all five component checks to pass. Procurement reports FFmpeg/FFprobe readiness and a separate downloader-availability field. Audio checks the full runtime including emotion dependencies, even if your job will be acoustic-only. Text checks the requested stages using the default Text configuration. The unified `--device` option currently applies to **Face readiness only**. For a custom Text config or dictionary, use the native Text `--check` with the actual options as well.

Package/tool presence, cached model files, and a successful Java check are bounded readiness evidence. They do not prove CUDA/MPS support on another machine, actual model inference on your media, successful external downloads, or scientific validity. Perform a small representative processing run, inspect artifacts, and then run the study workflow.

Credentials come from the existing process environment and local credential store, and the launcher supplies only the credential environment needed by the selected engine. Supported environment discovery includes `YOUTUBE_API_KEY`, `HF_TOKEN`, `HUGGINGFACE_TOKEN`, and `HUGGING_FACE_HUB_TOKEN`. Provision them through your existing local secret mechanism or scheduler account; do not put values in job JSON, command arguments, committed scripts, or output paths. `settings` reports only whether supported environment values are present; this does not test their validity or establish whether the separate local store is configured. Job files reject known secret keys, and native argument handling rejects secret-bearing flags, including separate-value and `--key=value` forms, before persisting the job. Private Clean Speaker child-entry flags are also rejected. Store only nonsecret Text configuration in config JSON. The CLI does not mutate the desktop's saved settings or prompt for browser credentials.

Resource overrides use the desktop's names, types, and validation bounds. Omitted values take these defaults:

| Resource key | Default | Accepted values / meaning |
| --- | --- | --- |
| `resourceLimitsEnabled` | `true` | Boolean enabling managed limits. |
| `maxCpuPercent` | `90.0` | 10–100; CPU pressure threshold. |
| `maxCpuCores` | `0` | Integer 0–256; 0 leaves affinity unconstrained. |
| `maxGpuPercent` | `95.0` | 10–100; GPU pressure threshold where monitoring is available. |
| `ramLimitMode` | `"percent"` | `percent` or `gb`. |
| `maxRamPercent` | `90.0` | 10–95; used in percent mode. |
| `maxRamGb` | `16.0` | 1–1024; used in GB mode. |
| `nativeThreads` | `1` | Integer 1–256; native library thread environment. |
| `resourcePollSeconds` | `2.0` | 0.5–30 seconds. |

Limits apply to the managed child through the existing launcher controls, not to unrelated processes. They are operating controls, not a guarantee of a fixed peak memory/CPU footprint or completion time. Clean Speaker also exposes its own `beta_*` resource/worker settings below; record both sets when tuning performance.

## Logs, status, cancellation, and deadlines

```text
RUN/
  submitted.json            submitted job
  effective.json            resolved plan and stage details
  status.json               live/final run and step states
  result.json               final result, if normal finalization occurred
  logs/STEP_ID.log          child stdout and stderr
  steps/STEP_ID/            copied/normalized auxiliary configuration
  outputs/STEP_ID/          default stage output root
  cancel.request.json      present if cancellation was requested
```

The engines write their own manifests/provenance beneath output roots. Preserve those together with run evidence. `submitted.json` retains the submitted job, while `effective.json`, status and final results record an effective `--timeout` override. `submitted.json` and logs can contain study paths and identifiers; review them before sharing. A crash can leave no final `result.json`.

From another terminal:

```powershell
$python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$run = 'C:\Research\TrinityStudy\runs\YOUR-ACTIVE-RUN'
& $python -m application.cli status --run-dir $run
& $python -m application.cli cancel --run-dir $run
& $python -m application.cli status --run-dir $run
```

`cancel_requested` acknowledges a request; wait for a terminal state before starting a replacement run against the same engine output. Ctrl+C in the foreground also cancels. The runner terminates its owned child tree. On Windows, it creates the child suspended and requires assignment to an owned Job Object before allowing engine work. If that ownership cannot be established, the run fails with exit 3; it does not fall back to an unowned process. Read the error, resolve the host restriction that prevented Job Object ownership, and use a new run directory for a retry. A `stale` status means the recorded runner identity is no longer live; it is an informational projection, not a successfully completed or automatically resumed run. Inspect its files and output consistency before resuming an engine stage in a new evidence directory.

The overall deadline starts after initial nonmutating job planning and creation of the exclusive run directory. Active-run stage building/scanning counts against that deadline, but an in-process scan cannot be interrupted mid-call; expiration is checked before launching the next child. A per-step `timeout_seconds` bounds that step's child execution. Where both apply, the shorter remaining budget wins. `--timeout` overrides the job-level value, not individual step limits. Omitted or JSON `null` deadlines mean no configured timeout at that level. The first failure, cancellation, or timeout stops subsequent steps, which remain pending.

| Exit code | Meaning |
| --- | --- |
| `0` | Successful command/run. For `status`, this means the status was read; inspect its `state`. A cancellation request also returns 0 before the run stops. |
| `2` | Invalid job/arguments, unusable input/provenance, or other validation failure. |
| `3` | Execution failure, or a requested doctor component is not ready. |
| `130` | The run was cancelled. |
| `124` | The run reached a configured timeout. |

The original engine return code is retained per step; the automation CLI maps a nonzero child failure to 3. Inspect `state`, step records and logs as well as the process code. A scheduler must not treat `status` returning 0 as proof that the workflow passed.

## Scheduled and scripted runs

The CLI stays in the foreground. Configure your scheduler to run one script, wait for its exit, and avoid overlapping executions of a study. Use absolute interpreter/job/run paths and the repository root as the working directory. Set up model caches, noninteractive credentials and write permissions for the **scheduler's account**, which may differ from your interactive account.

Save the following as `C:\Research\TrinityStudy\run-study.ps1`, replacing the repository and job paths. This script can be used by Windows Task Scheduler's “Start a program” action with program `powershell.exe` and arguments `-NoProfile -File "C:\Research\TrinityStudy\run-study.ps1"`. Select “Do not start a new instance” for overlap behavior. Registering a task is separate from the CLI; no scheduled task is created by these examples.

```powershell
$ErrorActionPreference = 'Stop'
$repo = 'C:\Research\TCD_Multimodal_Emotion_Analysis_Tool'
$python = Join-Path $repo '.venv\Scripts\python.exe'
$job = 'C:\Research\TrinityStudy\jobs\study.json'
$evidenceRoot = 'C:\Research\TrinityStudy\runs'
New-Item -ItemType Directory -Force $evidenceRoot | Out-Null
$tag = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N')
$run = Join-Path $evidenceRoot $tag
Set-Location -LiteralPath $repo
& $python -m application.cli run --job $job --run-dir $run --timeout 43200 `
  1> (Join-Path $evidenceRoot "$tag-result.json") `
  2> (Join-Path $evidenceRoot "$tag-stderr.log")
$code = $LASTEXITCODE
exit $code
```

A failed job is not automatically retried. After reviewing the cause and provenance, choose a new run directory for any retry. External schedulers may impose an additional deadline; abrupt host shutdown/forced scheduler termination can leave a stale run rather than a normal CLI cancellation result.

## Advanced native routes and retained module CLIs

Ordinary stages provide typed fields, current scans and artifact references. A `native.*` stage gives the listed existing module an `args` array. It accepts only `args` and optional `output_root`, with no `native_options`. The CLI validates arguments against the installed module parser, uses its fixed module allowlist, and launches without a shell. Arguments must explicitly choose the same output directory as the effective `output_root`; module output defaults are not sufficient. If the JSON field is omitted, that means `RUN/outputs/STEP_ID`, and the explicit native output argument must resolve to that exact path. The examples provide both values to make their agreement visible. Each option/value is its own JSON string, except for an entire-argument artifact reference as described above. Use `schema` for the route list and direct module `--help` for that module's complete flags/defaults. The managed native routes reject unbounded passthrough flags `--sample-arg`, `--full-video-arg`, and `--extractor-arg`; use the ordinary workflow controls or an explicitly supported native flag. The direct legacy module parsers may expose additional flags that the managed runner intentionally rejects.

| Native stage | Existing module | Explicit output flag |
| --- | --- | --- |
| `native.local` | `application.local_videos` | `--output-root` |
| `native.focus` | `application.manual_segments` | `--output-root` |
| `native.catalog` | `procurement.catalog_runner` | `--run-root` |
| `native.clean-speaker` | `procurement.procurement_beta.cli` | `--output-root` |
| `native.pipeline` | `procurement.run_pipeline` | `--output-root` |
| `native.docx-sampling` | `procurement.video_sampling.run_docx_extractions` | `--speaker-output-root` (also explicitly choose the output DOCX) |
| `native.audio` | `processing.audio_analysis.audio_pipeline` | `--output` |
| `native.face` | `processing.face_analysis` | `--output-root` |
| `native.text` | `processing.text_analysis` | `--output-root` |
| `native.analysis` | `analysis.workflow` | `--output-root` |
| `native.analysis-audio` | `analysis.audio` | `--output-root` |
| `native.analysis-face` | `analysis.native_face` | `--output-root` |
| `native.analysis-imotions` | `analysis.imotions` | `--output-root` |

Native options retain engine-specific defaults and validation, which can differ from desktop defaults. For example, the direct Text configuration defaults to four threads, while ordinary Text defaults to one. Explicit `--output-root` on native Text relocates all its stage outputs under that root, taking precedence over individual output paths in its config. Complete native Text configuration accepts the fields of `TextProcessingConfig`; example 14 specifies every field, and the source contract is in [pipeline.py](../processing/text_analysis/pipeline.py). Ordinary Text's supplementary config accepts only `language_policy`, to avoid silently overriding its typed controls.

The unified runner is not a general arbitrary-command executor. Other existing tools can still be run directly from the repository root. Their stdout/exit codes are their own contracts, rather than the unified JSON/exit-code contract. The following are concrete individual Text stage equivalents for advanced users; replace the paths with outputs from the preceding stage and retain its manifests.

```powershell
# Full native Text pipeline, or any single stage by setting both stage flags.
& $python -m processing.text_analysis 'C:\Research\TrinityStudy\media' `
  --output-root 'C:\Research\TrinityStudy\processed\text' `
  --from-stage transcribe --to-stage transcribe --whisper-model small --whisper-device cpu

# Language selection only, using the same Text workspace and input.
& $python -m processing.text_analysis 'C:\Research\TrinityStudy\media' `
  --output-root 'C:\Research\TrinityStudy\processed\text' --from-stage select --to-stage select

# Standalone bilingual transcription.
& $python -m processing.text_analysis.transcribe.transcribe 'C:\Research\TrinityStudy\media' `
  --task bilingual --model small --device cpu `
  --output-dir 'C:\Research\TrinityStudy\standalone\transcripts' --skip-existing

# Prepare selected Whisper JSON as RockSteady text segments.
& $python -m processing.text_analysis.prepare_input.whisper_to_rocksteady `
  'C:\Research\TrinityStudy\processed\text\selected_transcripts' `
  --output 'C:\Research\TrinityStudy\standalone\prepared' --lang en `
  --inventory 'C:\Research\TrinityStudy\processed\text\selected_transcripts\selection_manifest.json'

# Direct RockSteady adapter; total values are the native Text postprocessor's input contract.
& $python -m processing.text_analysis.rocksteady_adapter `
  'C:\Research\TrinityStudy\standalone\prepared' `
  --output-root 'C:\Research\TrinityStudy\standalone\rocksteady' `
  --dictionary 'embedded:affectDictionaries/General Language (En)(2011-07-05).dict.xml' `
  --all-categories --value-type total --threads 1

# Single-variant postprocessing from an existing validated RockSteady output.
& $python -m analysis.text_pipeline.postprocess `
  'C:\Research\TrinityStudy\processed\text\rocksteady\core' `
  --output-root 'C:\Research\TrinityStudy\standalone\postprocessed' `
  --whisper-root 'C:\Research\TrinityStudy\processed\text\selected_transcripts' `
  --prepare-root 'C:\Research\TrinityStudy\processed\text\prepared_segments' `
  --text-lang en --segment-alignment error --segment-samples none --no-graphs
```

The full Text pipeline is the appropriate interface when you need its complete manifest/lineage chain, paired selected/extra outputs and validated cache reuse. Standalone tools are useful for diagnosis and explicit intermediate work; they do not automatically create every artifact expected by a later full pipeline stage. The direct RockSteady adapter additionally supports `--config`, `--inventory`, `--batch-manifest`, `--category`, `--dictionary-combination`, `--timeout`, `--force`, `--check` and `--dry-run`. Read its parser before relying on a lower-level default. `postprocess analyse-pair SELECTED EXTRA` handles paired inputs; `--segment-alignment reconcile` is an explicit adjustment that must be recorded rather than silently applied.

Retained direct commands include the existing DOCX pipeline, catalog runner, Audio wrapper, Face, and statistical Analysis:

```powershell
& $python -m procurement.run_pipeline 'C:\Research\TrinityStudy\sources.docx' --output-root 'C:\Research\TrinityStudy\legacy-procurement'
& $python processing\audio_analysis\run_audio_analysis.py doctor
& $python -m processing.face_analysis --help
& $python -m processing.text_analysis --help
& $python -m analysis.imotions --help
& $python -m analysis.native_face --help
& $python -m analysis.audio --help
& $python -m analysis.workflow --help
```

## Troubleshooting

| Symptom | Check / next action |
| --- | --- |
| `Run directory must be new` | Choose a new evidence directory. Resume Text through an explicit engine output root instead. |
| Unknown field or invalid type | Use `schema`, exact snake_case option names, camelCase resources, and real JSON booleans/numbers. |
| Plan shows `deferred` | The step depends on an earlier output. Its full source/provenance checks run after that output exists. |
| Catalog digest/SourceID mismatch | Inspect the current catalog/run, confirm the reviewed selection, and correct the job. Do not bypass the digest check. |
| Profile association or metadata error | Run `inspect analysis-profile`; use the associated manifest and real field values. Preserve input sidecars. |
| Native output-directory mismatch | Explicitly pass the module's output flag and make it resolve to exactly `options.output_root`. |
| Native auxiliary output rejected | Put it beneath the current step's `outputs/STEP_ID` directory or a safe explicit external root, without overlapping inputs, configuration, evidence or prior outputs. |
| Windows child ownership could not be established | Read the ownership error and resolve the host restriction. The CLI does not run an unowned child; retry with a new evidence directory after correction. |
| Native passthrough/private/credential flag rejected | Use the ordinary typed controls or supported native arguments, and provide credentials through the existing environment/store. |
| Missing model/tool/runtime | Use the component doctor and installation guide, provision required artifacts, then test representative media. |
| Audio fails with a long emotion window | Use at most 15 seconds with emotions, or explicitly disable emotion models for longer acoustic windows. |
| Text cache/lineage rejection | Use the same source/configuration and valid upstream manifests, or regenerate from the earliest affected stage. |
| Text custom config rejected | Ordinary supplementary config is language-policy-only; use typed options or `native.text` for complete config. |
| A run stopped or appears stale | Read `status`, per-step logs, and engine manifests. Distinguish failure, timeout, cancellation and abrupt process loss. |
| Scheduled job works interactively only | Check the scheduler's account, absolute interpreter/cwd, model cache, credentials, permissions and overlap settings. |

## Complete ordinary parameter reference

The following tables enumerate the ordinary JSON options and their defaults from the current request/schema contract. `source_path` is required for processing/Procurement; `modalities` is required for Analysis. `output_root` is optional because the runner supplies `RUN/outputs/STEP_ID`. Native routes still require an explicit native output argument matching that effective path. Type tables describe JSON types; runtime validation additionally checks integer syntax, choices, bounds, formats and provenance described above and in the engine documentation. Use `schema` from the checkout being run when upgrading, rather than assuming this version's defaults are unchanged.

```powershell
& $python -m application.cli schema | Set-Content -Encoding utf8 'C:\Research\TrinityStudy\job-schema-v1.json'
& $python -m application.cli schema --stage procurement
$schema = (& $python -m application.cli schema) | ConvertFrom-Json
$schema.'x-native-options' | ConvertTo-Json -Depth 30
```

<!-- BEGIN GENERATED PARAMETER TABLES -->
### `procurement` options

| Field | JSON type | Default | Meaning / bounds |
| --- | --- | --- | --- |
| `mode` | string | `"standard"` | Procurement: standard/full/manual/clean-speaker-beta. Audio: inferred batch/single unless specified. |
| `source_path` | string | `required` | Input path; required. Catalog/URL support depends on the stage. |
| `output_root` | string | `runner supplies` | Default supplied by runner: RUN/outputs/STEP_ID. |
| `segment_manifest` | string or null | `null` | Focus manifest path; required in manual mode. |
| `segment_manifest_sha256` | string | `""` | Optional expected Focus digest; CLI computes current digest. |
| `segment_expected_source` | string | `""` | Optional expected Focus source identity; freshly checked. |
| `selected_ids` | array of string or null | `null` | Catalog SourceIDs; omitted/null selects discovered entries. |
| `selected_speakers` | array of string or null | `null` | Discovered local/DOCX speaker groups where supported. |
| `catalog_sha256` | string | `""` | Empty means freshly bound for a catalog; supplied digest must match. |
| `max_segment_seconds` | integer | `30` | Sampling cap: integer 1–3600 seconds. |
| `percentage` | number | `0.1` | Sampling fraction: greater than 0, at most 1. |
| `beta_output_mode` | string | `"clean"` | clean or percentage. |
| `beta_min_clean_seconds` | number | `10.0` | Positive minimum accepted clean duration, seconds. |
| `beta_gap_seconds` | number | `0.5` | Gap threshold: 0–60 seconds. |
| `beta_identity_stills` | integer | `20` | Identity still count: integer 1–200. |
| `beta_scan_fps` | number | `1.0` | Coarse scan rate: 0.1–10 fps. |
| `beta_validation_fps` | number | `4.0` | Validation rate: 0.1–10 fps. |
| `beta_face_confidence` | number | `0.65` | Face confidence: greater than 0, at most 1. |
| `beta_speaker_confidence` | number | `0.65` | Active-speaker confidence: greater than 0, at most 1. |
| `beta_worker_count` | integer | `1` | Worker count: integer 1–64. |
| `beta_device` | string | `"auto"` | auto/cpu/cuda. |
| `beta_keep_debug` | boolean | `false` | Keep Clean Speaker debugging artifacts. |
| `beta_resource_guard_percent` | number | `15.0` | Required resource headroom: 0–95 percent. |
| `beta_resource_poll_seconds` | number | `15.0` | Resource polling: 0.5–300 seconds. |
| `beta_resource_guard_timeout_seconds` | number | `900.0` | Wait timeout: 0–86400 seconds; 0 permits indefinite waiting. |
| `beta_parallel_detector_streams` | boolean | `false` | Allow parallel detector streams. |
| `beta_reference_audio` | string or null | `null` | Optional reference audio path. |
| `beta_max_download_height` | integer | `720` | 0–4320 pixels; 0 requests best available. |
| `beta_only_video_ids` | array of string or null | `null` | Optional downloader video-ID allowlist. |
| `beta_random_one` | boolean | `false` | Choose one video from the eligible set. |
| `beta_random_seed` | string | `""` | Seed for random-one video selection. |
| `beta_isolated_video_processes` | boolean | `true` | Use separate processes for individual videos. |
| `beta_skip_first_videos` | integer | `0` | Skip count: integer 0–10000. |
| `beta_skip_completed_outputs` | boolean | `true` | Reuse valid completed Clean Speaker outputs. |
| `beta_video_cooldown_seconds` | number | `60.0` | Cooldown between videos: 0–3600 seconds. |
| `beta_max_affinity_cores` | integer | `2` | Affinity cap: integer 0–256; 0 unconstrained. |
| `beta_native_threads` | integer | `1` | Native threads: integer 1–256. |
| `beta_cpu_throttle_high_percent` | number | `95.0` | CPU high threshold; 1 ≤ low ≤ high ≤ 100. |
| `beta_cpu_throttle_low_percent` | number | `90.0` | CPU low threshold; 1 ≤ low ≤ high ≤ 100. |
| `beta_ram_throttle_high_percent` | number | `95.0` | RAM high threshold; 1 ≤ low ≤ high ≤ 100. |
| `beta_ram_throttle_low_percent` | number | `90.0` | RAM low threshold; 1 ≤ low ≤ high ≤ 100. |

### `face` options

| Field | JSON type | Default | Meaning / bounds |
| --- | --- | --- | --- |
| `source_path` | string | `required` | Input path; required. Catalog/URL support depends on the stage. |
| `output_root` | string | `runner supplies` | Default supplied by runner: RUN/outputs/STEP_ID. |
| `sample_fps` | number | `5.0` | Face sampling: greater than 0, at most 120 fps. |
| `confidence_threshold` | number | `0.9` | Face detection threshold: greater than 0, at most 1. |
| `batch_size` | integer | `8` | Face inference batch: integer 1–1024. |
| `device` | string | `"auto"` | Face: auto/cpu/cuda/mps. Audio: auto/cpu/cuda. |
| `recursive` | boolean | `true` | Search subdirectories for Face inputs. |
| `overwrite` | boolean | `false` | Explicitly regenerate existing Face output where permitted. |
| `debug` | boolean | `false` | Enable engine diagnostic detail. |
| `selected_source_ids` | array of string | `[]` | Omit to select all authorized catalog sources; explicit catalog IDs only. |
| `catalog_sha256` | string | `""` | Empty means freshly bound for a catalog; supplied digest must match. |

### `audio` options

| Field | JSON type | Default | Meaning / bounds |
| --- | --- | --- | --- |
| `mode` | string | `inferred` | Procurement: standard/full/manual/clean-speaker-beta. Audio: inferred batch/single unless specified. |
| `source_path` | string | `required` | Input path; required. Catalog/URL support depends on the stage. |
| `output_root` | string | `runner supplies` | Default supplied by runner: RUN/outputs/STEP_ID. |
| `window_seconds` | number | `10.0` | 0.5–120 seconds; emotion models impose a 15-second maximum. |
| `stride_seconds` | number | `5.0` | Window advance: 0.5–120 seconds. |
| `opensmile_feature_set` | string | `"egemaps"` | egemaps, compare, or compare16. |
| `include_emotions` | boolean | `true` | Run categorical/dimensional models in addition to acoustic extraction. |
| `device` | string | `"auto"` | Face: auto/cpu/cuda/mps. Audio: auto/cpu/cuda. |
| `keep_temp_audio` | boolean | `false` | Preserve intermediate converted audio. |
| `debug` | boolean | `false` | Enable engine diagnostic detail. |
| `stop_on_error` | boolean | `false` | Stop batch Audio after the first failed file. |
| `selected_source_ids` | array of string | `[]` | Omit to select all authorized catalog sources; explicit catalog IDs only. |
| `catalog_sha256` | string | `""` | Empty means freshly bound for a catalog; supplied digest must match. |

### `text` options

| Field | JSON type | Default | Meaning / bounds |
| --- | --- | --- | --- |
| `source_path` | string | `required` | Input path; required. Catalog/URL support depends on the stage. |
| `output_root` | string | `runner supplies` | Default supplied by runner: RUN/outputs/STEP_ID. |
| `whisper_model` | string | `"small"` | tiny/base/small/medium/large/large-v2/large-v3. |
| `whisper_device` | string | `"auto"` | auto/cpu/cuda. |
| `whisper_language` | string | `""` | Blank allows detection; explicit fallback yields to catalog system language. |
| `default_language_variant` | string | `"eng"` | eng or original. |
| `dictionaries` | array of string | `[]` | embedded:RESOURCE or file:PATH entries; empty uses embedded General Language. |
| `dictionary_combination` | string | `"merge"` | merge or override. |
| `categories` | array of string | `[]` | Requested dictionary categories; empty means all, core view still derived. |
| `all_categories` | boolean | `false` | Select every dictionary category; mutually exclusive with nonempty categories. |
| `threads` | integer | `1` | Ordinary Text workers: integer 1–256. |
| `force_rocksteady` | boolean | `false` | Request regeneration of RockSteady artifacts. |
| `write_graphs` | boolean | `true` | Generate plots in addition to tabular outputs. |
| `debug` | boolean | `false` | Enable engine diagnostic detail. |
| `selected_source_ids` | array of string | `[]` | Omit to select all authorized catalog sources; explicit catalog IDs only. |
| `catalog_sha256` | string | `""` | Empty means freshly bound for a catalog; supplied digest must match. |

### `analysis` options

| Field | JSON type | Default | Meaning / bounds |
| --- | --- | --- | --- |
| `output_root` | string | `runner supplies` | Default supplied by runner: RUN/outputs/STEP_ID. |
| `modalities` | array of object | `required` | Required array of name/source_method/source_path objects; see Analysis section. |
| `speaker_groups` | array of object | `[]` | Legacy group_id/name/speaker_ids objects; exclusive with profile choices. |
| `analysis_profile` | object or string or null | `null` | Full profile object or profile JSON path; null when unused. |
| `write_combined_workbook` | boolean | `true` | Generate combined workbook; requires valid groups or a profile. |
| `include_construct_comparison` | boolean | `true` | Include construct comparison output when combining. |
| `include_probability_sheets` | boolean | `true` | Include probability/inference sheets when combining. |
| `confidence_level` | number | `0.95` | Confidence probability, strictly between 0 and 1. |
| `headline_policy` | string | `"weighted"` | weighted or equal. |
| `default_reference` | number | `0.0` | Finite fallback reference value for inference. |
| `reference_overrides` | object | `{}` | Finite reference values keyed by canonical sheet/metric. |
| `write_graphs` | boolean | `true` | Generate plots in addition to tabular outputs. |
| `include_logscale` | boolean | `false` | Include logarithmic histogram plots. |
| `include_landmarks` | boolean | `false` | Include applicable iMotions landmark fields. |
| `include_timing` | boolean | `false` | Include applicable iMotions timing fields. |
| `exclude_geometry` | boolean | `false` | Exclude applicable iMotions geometry fields. |

### Supplementary `native_options`

These are extra fields on an ordinary stage, not replacements for its `options`. Omit unused fields; no automatic native override is applied.

| Stage | Field | Type / behavior |
| --- | --- | --- |
| `procurement` | `allow_external_local_paths` | Boolean, passed only when true; applicable catalog native route must support it. |
| `procurement` | `reference_face_dir` | Path to reference face images for Clean Speaker. |
| `procurement` | `run_final_output_validation` | Boolean, passed only when true; Clean Speaker native validation option. |
| `face` | `run_id` | Optional caller-supplied string identifier. |
| `audio` | None | An empty object is allowed; unknown fields are rejected. |
| `text` | `from_stage`, `to_stage` | One of transcribe/select/prepare/rocksteady/postprocess; defaults transcribe/postprocess in the native engine. |
| `text` | `config` | JSON path containing only language_policy; config paths relative to the job. |
| `text` | `run_id` | Optional caller-supplied string identifier. |
| `analysis` | `profile_options` | Strict metadata choices object, auto-bound to the discovered manifest; see Analysis section. |

Supplementary options are also validated against the selected underlying module parser. A Procurement option that belongs to Clean Speaker or catalog mode is rejected when the selected mode routes to a different engine.

<!-- END GENERATED PARAMETER TABLES -->
