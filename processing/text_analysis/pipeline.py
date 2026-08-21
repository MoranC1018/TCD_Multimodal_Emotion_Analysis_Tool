"""One-command, provenance-bound orchestration for Text processing."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import time
import uuid
import warnings
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from analysis.text_pipeline.batch import analyse_text_segment_pair
from analysis.text_pipeline.ownership import (
    BATCH_MANIFEST_FILE,
    PAIR_KIND,
    assert_publishable_output,
)
from procurement.external_tools import credential_free_media_environment
from processing.io_utils import atomic_write_json, exclusive_process_lock, lexical_absolute_path
from processing.catalog_context import discover_catalog_jobs, publish_catalog_run_context

from .contracts import TEXT_SCHEMA_VERSION, file_sha256, inventory_digest
from .derived_views import DERIVED_MANIFEST, derive_category_view
from .filesystem import (
    assert_replaceable_stage_target,
    assert_safe_output_target,
    create_stage_directory,
    discard_stage_directory,
)
from .prepare_input.integrity import validate_prepare_batch_artifacts
from .manifest_validation import (
    DERIVED,
    POSTPROCESSING_PAIR,
    POSTPROCESSING_VARIANT,
    PREPARE,
    ROCKSTEADY,
    SELECTION,
    TRANSCRIPTION,
    ManifestContract,
    read_completed_manifest as _strict_read_completed_manifest,
    validate_derived_settings,
    validate_prepare_settings,
    validate_selection_settings,
    validate_transcription_settings,
)
from .selection import DEFAULT_LANGUAGE_POLICY, SELECTION_MANIFEST, build_selected_whisper_tree
from .rocksteady_adapter.runner import (
    ADAPTER_ROOT,
    check_runtime,
    load_settings as load_rocksteady_settings,
    resolve_rocksteady_home,
    validate_rocksteady_batch_manifest,
)
from .rocksteady_transaction import rocksteady_pair_transaction
from .transcribe.integrity import validate_transcription_artifact_set
from .transcribe.provenance import collect_whisper_execution_identity


CORE_CATEGORIES = ("Active", "Negativ", "Passive", "Positiv", "Strong", "Weak")
# Optional example for the integrated dictionary. The default pipeline does not
# use this list: General Language exports every category dynamically.
EXTRA_CATEGORIES = (
    "Active", "Affil", "Commodity", "Econ@", "Economics", "Energy", "Finance",
    "Hostile", "Milit", "Negativ", "Passive", "Positiv", "Power", "Risk",
    "Strong", "Weak",
)
STAGES = ("transcribe", "select", "prepare", "rocksteady", "postprocess")
WHISPER_MODELS = ("tiny", "base", "small", "medium", "large", "large-v2", "large-v3")
MANIFEST_CONTRACTS: dict[str, ManifestContract] = {
    "transcription": TRANSCRIPTION,
    "language selection": SELECTION,
    "prepare": PREPARE,
    "RockSteady": ROCKSTEADY,
    "derived view": DERIVED,
    "paired postprocessing": POSTPROCESSING_PAIR,
    "selected postprocessing": POSTPROCESSING_VARIANT,
    "extra postprocessing": POSTPROCESSING_VARIANT,
}


@dataclass(frozen=True)
class TextProcessingConfig:
    input_path: str = "Videos"
    whisper_root: str = "processing/text_analysis/output/current/transcripts"
    selected_whisper_root: str = "processing/text_analysis/output/current/selected_transcripts"
    prepared_root: str = "processing/text_analysis/output/current/prepared_segments"
    selected_csv_root: str = "processing/text_analysis/output/current/rocksteady/core"
    extra_csv_root: str = "processing/text_analysis/output/current/rocksteady/all"
    postprocessing_root: str = "analysis/output/text/text_output"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    threads: int = 4
    dictionaries: tuple[str, ...] = (
        "embedded:affectDictionaries/General Language (En)(2011-07-05).dict.xml",
    )
    categories: tuple[str, ...] = ()
    dictionary_combination: str = "merge"
    overwrite_rocksteady: bool = False
    write_graphs: bool = True
    default_language_variant: str = "eng"
    whisper_language: str = ""
    source_ids: tuple[str, ...] = ()
    catalog_sha256: str = ""
    language_policy: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_LANGUAGE_POLICY))

    def validate(self) -> "TextProcessingConfig":
        if not isinstance(self.whisper_model, str) or self.whisper_model not in WHISPER_MODELS:
            raise ValueError(f"whisper_model must be one of: {', '.join(WHISPER_MODELS)}")
        if not isinstance(self.whisper_device, str) or self.whisper_device not in {"auto", "cpu", "cuda"}:
            raise ValueError("whisper_device must be auto, cpu, or cuda")
        if not isinstance(self.threads, int) or isinstance(self.threads, bool) or self.threads < 1:
            raise ValueError("threads must be at least 1")
        if not isinstance(self.dictionary_combination, str) or self.dictionary_combination not in {"merge", "override"}:
            raise ValueError("dictionary_combination must be merge or override")
        if not isinstance(self.overwrite_rocksteady, bool):
            raise ValueError("overwrite_rocksteady must be a boolean")
        if not isinstance(self.write_graphs, bool):
            raise ValueError("write_graphs must be a boolean")
        if isinstance(self.dictionaries, (str, bytes)) or not isinstance(self.dictionaries, Sequence):
            raise ValueError("dictionaries must be a JSON array or Python sequence")
        if not self.dictionaries or any(not isinstance(item, str) or not item.strip() for item in self.dictionaries):
            raise ValueError("at least one RockSteady dictionary is required")
        if isinstance(self.categories, (str, bytes)) or not isinstance(self.categories, Sequence):
            raise ValueError("categories must be a JSON array or Python sequence")
        if any(not isinstance(item, str) or not item.strip() for item in self.categories):
            raise ValueError("categories must contain non-empty strings")
        if len({item.casefold() for item in self.categories}) != len(self.categories):
            raise ValueError("categories must not contain case-insensitive duplicates")
        if not isinstance(self.default_language_variant, str) or self.default_language_variant not in {"original", "eng"}:
            raise ValueError("default_language_variant must be original or eng")
        if not isinstance(self.whisper_language, str):
            raise ValueError("whisper_language must be text")
        if any(re.fullmatch(r"source-\d{4,6}", source_id) is None for source_id in self.source_ids):
            raise ValueError("source_ids must contain catalog SourceID values")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        if self.catalog_sha256 and re.fullmatch(r"[0-9a-fA-F]{64}", self.catalog_sha256) is None:
            raise ValueError("catalog_sha256 must be a SHA-256 value")
        if not isinstance(self.language_policy, Mapping):
            raise ValueError("language_policy must be an object mapping countries to variants")
        if any(not isinstance(country, str) or not country.strip() for country in self.language_policy):
            raise ValueError("language_policy country names must be non-empty strings")
        if any(
            not isinstance(variant, str) or variant not in {"original", "eng"}
            for variant in self.language_policy.values()
        ):
            raise ValueError("language_policy values must be original or eng")
        path_fields = (
            self.input_path, self.whisper_root, self.selected_whisper_root, self.prepared_root,
            self.selected_csv_root, self.extra_csv_root, self.postprocessing_root,
        )
        if any(not isinstance(value, str) or not value.strip() for value in path_fields):
            raise ValueError("text input and output paths must be non-empty strings")
        return self


@dataclass(frozen=True)
class TextProcessingResult:
    run_id: str
    manifest: Path
    completed_stages: tuple[str, ...]
    artifacts: dict[str, object]
    inventory: dict[str, object]
    selected_output: Path | None = None
    extra_output: Path | None = None


def _effective_rocksteady_categories(categories: Sequence[str]) -> tuple[str, ...]:
    """Keep the stable core view available while honoring custom filters.

    An empty request means all dictionary categories.  For an explicit request,
    the six stable output categories are added mechanically so the selected
    view can always be derived from the same canonical RockSteady run.
    """

    if not categories:
        return ()
    result = list(CORE_CATEGORIES)
    seen = {name.casefold() for name in result}
    for category in categories:
        if category.casefold() not in seen:
            result.append(category)
            seen.add(category.casefold())
    return tuple(result)


def load_text_processing_config(
    config_path: Path | None = None,
    *,
    input_path: str | None = None,
    overrides: Mapping[str, object] | None = None,
) -> TextProcessingConfig:
    """Load one validated config for the Text CLI or another explicit caller."""

    values = TextProcessingConfig().__dict__.copy()
    if config_path is not None:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Text pipeline config must be a JSON object")
        unknown = set(loaded) - set(values)
        if unknown:
            raise ValueError(f"Unknown text config keys: {', '.join(sorted(unknown))}")
        values.update(loaded)
    if input_path is not None:
        values["input_path"] = input_path
    if overrides:
        unknown = set(overrides) - set(values)
        if unknown:
            raise ValueError(f"Unknown text config overrides: {', '.join(sorted(unknown))}")
        values.update({key: value for key, value in overrides.items() if value is not None})
    for key in ("dictionaries", "categories", "source_ids"):
        if isinstance(values.get(key), list):
            values[key] = tuple(values[key])
    return TextProcessingConfig(**values).validate()


def check_text_processing_readiness(
    config: TextProcessingConfig,
    *,
    stages: Sequence[str] = STAGES,
    rocksteady_home: Path | None = None,
    adapter_config_path: Path | None = None,
) -> dict[str, object]:
    """Validate every external runtime needed by the requested stage range."""

    settings = config.validate()
    requested_stages = tuple(stages)
    unknown = [stage for stage in requested_stages if stage not in STAGES]
    if unknown:
        raise ValueError(f"Unknown Text readiness stages: {', '.join(unknown)}")
    readiness: dict[str, object] = {
        "status": "ready",
        "stages": list(requested_stages),
    }
    if "transcribe" in requested_stages:
        try:
            whisper_identity = collect_whisper_execution_identity(settings.whisper_model)
        except Exception as exc:
            raise RuntimeError(
                "Whisper preflight failed: "
                f"{type(exc).__name__}: {exc}. Install the matched OpenAI Whisper, "
                "PyTorch, and FFmpeg stack with scripts/setup.ps1, then rerun the "
                "same Text command."
            ) from exc
        readiness["whisper"] = whisper_identity

    if "rocksteady" not in requested_stages:
        return readiness

    local_config = adapter_config_path
    if local_config is None:
        candidate = ADAPTER_ROOT / "config.local.json"
        local_config = candidate if candidate.is_file() else None
    effective_categories = _effective_rocksteady_categories(settings.categories)
    arguments = SimpleNamespace(
        dictionary=list(settings.dictionaries),
        dictionary_combination=settings.dictionary_combination,
        analyser="simple",
        value_type="total",
        category=list(effective_categories) or None,
        all_categories=not effective_categories,
        threads=settings.threads,
        timeout=None,
    )
    adapter_settings = load_rocksteady_settings(local_config, arguments)
    home = resolve_rocksteady_home(rocksteady_home, local_config)
    try:
        categories, application_jar, classes = check_runtime(home, adapter_settings)
    except Exception as exc:
        raise RuntimeError(
            "RockSteady preflight failed: "
            f"{exc}. Run `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`, "
            "then rerun the same Text command."
        ) from exc
    readiness.update({
        "rocksteady_home": str(home),
        "application_jar": str(application_jar),
        "adapter_classes": str(classes),
        "categories": list(categories),
        "category_count": len(categories),
    })
    return readiness


def run_text_pipeline(
    config: TextProcessingConfig,
    *,
    from_stage: str = "transcribe",
    to_stage: str = "postprocess",
    repo_root: Path | None = None,
    run_id: str | None = None,
) -> TextProcessingResult:
    """Serialize complete Text runs because their canonical stage roots are shared."""

    settings = config.validate()
    if from_stage not in STAGES or to_stage not in STAGES:
        raise ValueError(f"Stages must be one of: {', '.join(STAGES)}")
    start_index, stop_index = STAGES.index(from_stage), STAGES.index(to_stage)
    if start_index > stop_index:
        raise ValueError("from_stage must not come after to_stage")
    requested_stages = STAGES[start_index : stop_index + 1]
    root = (repo_root or Path.cwd()).resolve()
    paths = _pipeline_paths(settings, root)
    catalog_discovery = discover_catalog_jobs(
        paths["input"],
        selected_source_ids=settings.source_ids or None,
        expected_catalog_sha256=settings.catalog_sha256,
    )
    if catalog_discovery is not None:
        settings = replace(
            settings,
            source_ids=tuple(job.source_id for job in catalog_discovery.jobs),
            catalog_sha256=catalog_discovery.catalog_sha256,
        )
        paths = _pipeline_paths(settings, root)
    _validate_pipeline_paths(paths)
    _preflight_stage_targets(paths, requested_stages)
    check_text_processing_readiness(settings, stages=requested_stages)
    lock_path = root / "processing" / "text_analysis" / "output" / ".pipeline.run.lock"
    with exclusive_process_lock(lock_path, purpose="running the Text processing pipeline"):
        return _run_text_pipeline_locked(
            settings,
            from_stage=from_stage,
            to_stage=to_stage,
            repo_root=root,
            run_id=run_id,
            catalog_discovery=catalog_discovery,
        )


def _run_text_pipeline_locked(
    config: TextProcessingConfig,
    *,
    from_stage: str,
    to_stage: str,
    repo_root: Path,
    run_id: str | None,
    catalog_discovery=None,
) -> TextProcessingResult:
    """Run a bounded stage range without mixing artifacts from other inventories."""

    settings = config.validate()
    if from_stage not in STAGES or to_stage not in STAGES:
        raise ValueError(f"Stages must be one of: {', '.join(STAGES)}")
    start_index, stop_index = STAGES.index(from_stage), STAGES.index(to_stage)
    if start_index > stop_index:
        raise ValueError("from_stage must not come after to_stage")
    root = repo_root.resolve()
    paths = _pipeline_paths(settings, root)
    _validate_pipeline_paths(paths)
    _preflight_stage_targets(paths, STAGES[start_index : stop_index + 1])
    current_run_id = _validated_run_id(run_id)
    manifest_root = root / "processing" / "text_analysis" / "output"
    manifest_path = manifest_root / "runs" / current_run_id / "pipeline_manifest.json"
    latest_manifest_path = manifest_root / "pipeline_manifest.json"
    manifest_targets = (manifest_path, latest_manifest_path)
    started = datetime.now(timezone.utc)
    stage_records: list[dict[str, object]] = []
    artifacts: dict[str, object] = {}
    inventory_items: list[dict[str, object]] = []
    if catalog_discovery is not None:
        publish_catalog_run_context(paths["whisper"].parent, catalog_discovery)
    _write_manifest(
        manifest_targets, settings, current_run_id, started, stage_records,
        inventory_items, artifacts, "running",
    )
    active_record: dict[str, object] | None = None
    try:
        # Bind a resumed run to every completed upstream inventory before mutation.
        if start_index:
            if start_index >= STAGES.index("postprocess"):
                # Recovery must precede even the first read: a hard process or
                # power loss can stop between the two filesystem renames.
                with rocksteady_pair_transaction(
                    paths["extra_csv"],
                    paths["selected_csv"],
                    purpose="recovering the RockSteady all/core pair before resume",
                ):
                    inventory_items, upstream_artifacts = _load_upstream_inventory(
                        settings, paths, start_index
                    )
            else:
                inventory_items, upstream_artifacts = _load_upstream_inventory(
                    settings, paths, start_index
                )
            artifacts.update(upstream_artifacts)
            _write_manifest(
                manifest_targets, settings, current_run_id, started, stage_records,
                inventory_items, artifacts, "running",
            )

        for stage in STAGES[start_index : stop_index + 1]:
            stage_number = STAGES.index(stage) + 1
            print(f"Text stage {stage_number}/{len(STAGES)}: {stage}", flush=True)
            stage_started = datetime.now(timezone.utc)
            before = time.monotonic()
            active_record = {
                "stage": stage,
                "status": "running",
                "started_at": stage_started.isoformat(),
                "inputs": _stage_inputs(stage, paths),
                "outputs": _stage_outputs(stage, paths),
            }
            stage_records.append(active_record)
            _write_manifest(
                manifest_targets, settings, current_run_id, started, stage_records,
                inventory_items, artifacts, "running",
            )

            if stage == "transcribe":
                command = _transcribe_command(settings, root, paths["transcription_manifest"])
                active_record["command"] = command
                _run(command, root)
                payload = _read_completed_manifest(paths["transcription_manifest"], "transcription")
                _validate_transcription_manifest(payload, settings, paths)
                inventory_items = _inventory_from_transcription(payload, paths["whisper"])
                _validate_source_provenance(inventory_items)
                artifacts["transcribe"] = {
                    "root": str(paths["whisper"]), "manifest": str(paths["transcription_manifest"])
                }
                active_record["counts"] = payload.get("summary", {})

            elif stage == "select":
                transcribe_payload = _read_completed_manifest(
                    paths["transcription_manifest"], "transcription"
                )
                _validate_transcription_manifest(transcribe_payload, settings, paths)
                identities = _successful_identities(inventory_items)
                count = build_selected_whisper_tree(
                    paths["whisper"], paths["selected_whisper"],
                    language_policy=settings.language_policy,
                    default_variant=settings.default_language_variant,
                    identities=identities,
                    input_path=str(paths["input"]),
                    upstream_inventory_sha256=str(transcribe_payload["inventory_sha256"]),
                )
                selection_payload = _read_completed_manifest(
                    paths["selection_manifest"], "language selection"
                )
                _validate_selection_manifest(selection_payload, settings, paths)
                _require_upstream_digest(
                    selection_payload, str(transcribe_payload["inventory_sha256"]), "selection"
                )
                _merge_selection(inventory_items, selection_payload, paths["selected_whisper"])
                artifacts["select"] = {
                    "root": str(paths["selected_whisper"]), "manifest": str(paths["selection_manifest"])
                }
                active_record["counts"] = {"selected_json_files": count}

            elif stage == "prepare":
                selection_payload = _read_completed_manifest(
                    paths["selection_manifest"], "language selection"
                )
                _validate_selection_manifest(selection_payload, settings, paths)
                command = [
                    sys.executable, "-m",
                    "processing.text_analysis.prepare_input.whisper_to_rocksteady",
                    str(paths["selected_whisper"]), "--output", str(paths["prepared"]),
                    "--lang", "original", "--inventory", str(paths["selection_manifest"]),
                    "--batch-manifest", str(paths["prepare_manifest"]),
                ]
                active_record["command"] = command
                _run(command, root)
                prepare_payload = _read_completed_manifest(paths["prepare_manifest"], "prepare")
                _validate_prepare_manifest(prepare_payload, paths)
                _require_upstream_digest(
                    prepare_payload, str(selection_payload["inventory_sha256"]), "prepare"
                )
                _validate_prepare_artifacts(paths)
                _merge_prepare(inventory_items, prepare_payload, paths["prepared"])
                artifacts["prepare"] = {
                    "root": str(paths["prepared"]), "manifest": str(paths["prepare_manifest"])
                }
                active_record["counts"] = prepare_payload.get("summary", {})

            elif stage == "rocksteady":
                rock_payload, derived = _run_rocksteady_pair_stage(
                    settings,
                    root,
                    paths,
                    current_run_id,
                    inventory_items,
                    active_record,
                )
                artifacts["rocksteady"] = {
                    "extra_root": str(paths["extra_csv"]),
                    "selected_root": str(paths["selected_csv"]),
                    "manifest": str(paths["rocksteady_manifest"]),
                    "derived_manifest": str(paths["derived_manifest"]),
                }
                active_record["counts"] = {
                    **dict(rock_payload.get("summary") or {}),
                    "derived_core_csv_files": derived,
                }

            else:
                active_record["operation"] = "atomic-selected-extra-pair"
                # Hold the same pair lock used by standalone writers for the
                # complete downstream read, and revalidate after acquisition.
                with rocksteady_pair_transaction(
                    paths["extra_csv"],
                    paths["selected_csv"],
                    purpose="reading the RockSteady all/core pair for postprocessing",
                ):
                    inventory_items, refreshed_artifacts = _load_upstream_inventory(
                        settings, paths, STAGES.index("postprocess")
                    )
                    artifacts.update(refreshed_artifacts)
                    pair = analyse_text_segment_pair(
                        paths["selected_csv"],
                        paths["extra_csv"],
                        output_root=paths["post_root"],
                        whisper_root=paths["selected_whisper"],
                        prepare_root=paths["prepared"],
                        write_graphs=settings.write_graphs,
                        text_language="en",
                        run_id=current_run_id,
                        catalog_discovery=catalog_discovery,
                    )
                    pair_payload = _read_completed_manifest(
                        paths["postprocess_pair_manifest"], "paired postprocessing"
                    )
                    _validate_postprocess_pair(pair_payload, current_run_id, paths)
                    selected_payload = _read_completed_manifest(
                        paths["selected_post_manifest"], "selected postprocessing"
                    )
                    extra_payload = _read_completed_manifest(
                        paths["extra_post_manifest"], "extra postprocessing"
                    )
                    if selected_payload.get("run_id") != current_run_id:
                        raise RuntimeError("Selected postprocessing manifest belongs to another run")
                    if extra_payload.get("run_id") != current_run_id:
                        raise RuntimeError("Extra postprocessing manifest belongs to another run")
                    _validate_postprocess_identity_set(inventory_items, selected_payload, "selected")
                    _validate_postprocess_identity_set(inventory_items, extra_payload, "extra")
                    _merge_postprocess(inventory_items, paths)
                artifacts["postprocess"] = {
                    "root": str(pair.output_root),
                    "pair_manifest": str(pair.batch_manifest_path),
                    "selected": str(paths["selected_post"]),
                    "extra": str(paths["extra_post"]),
                    "selected_manifest": str(paths["selected_post_manifest"]),
                    "extra_manifest": str(paths["extra_post_manifest"]),
                }
                active_record["counts"] = {
                    "selected": selected_payload.get("summary", {}),
                    "extra": extra_payload.get("summary", {}),
                }

            active_record["status"] = "completed"
            active_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            active_record["seconds"] = round(time.monotonic() - before, 3)
            active_record = None
            _write_manifest(
                manifest_targets, settings, current_run_id, started, stage_records,
                inventory_items, artifacts, "running",
            )
    except BaseException as exc:
        cancelled = isinstance(exc, KeyboardInterrupt)
        if active_record is not None:
            active_record["status"] = "cancelled" if cancelled else "failed"
            active_record["finished_at"] = datetime.now(timezone.utc).isoformat()
            active_record["error_type"] = type(exc).__name__
            active_record["error_message"] = str(exc) or "Interrupted by user"
        _write_manifest(
            manifest_targets, settings, current_run_id, started, stage_records,
            inventory_items, artifacts, "cancelled" if cancelled else "failed",
        )
        raise

    _write_manifest(
        manifest_targets, settings, current_run_id, started, stage_records,
        inventory_items, artifacts, "completed",
    )
    completed = tuple(
        str(record["stage"]) for record in stage_records if record.get("status") == "completed"
    )
    postprocess_completed = "postprocess" in completed
    inventory = _inventory_payload(inventory_items)
    return TextProcessingResult(
        run_id=current_run_id,
        manifest=manifest_path,
        completed_stages=completed,
        artifacts=artifacts,
        inventory=inventory,
        selected_output=paths["selected_post"] if postprocess_completed else None,
        extra_output=paths["extra_post"] if postprocess_completed else None,
    )


def _pipeline_paths(config: TextProcessingConfig, root: Path) -> dict[str, Path]:
    whisper = _path(root, config.whisper_root)
    selected_whisper = _path(root, config.selected_whisper_root)
    prepared = _path(root, config.prepared_root)
    extra_csv = _path(root, config.extra_csv_root)
    selected_csv = _path(root, config.selected_csv_root)
    post_root = _path(root, config.postprocessing_root)
    return {
        "input": _path(root, config.input_path),
        "whisper": whisper,
        "selected_whisper": selected_whisper,
        "prepared": prepared,
        "extra_csv": extra_csv,
        "selected_csv": selected_csv,
        "selected_post": post_root / "selected",
        "extra_post": post_root / "extra",
        "post_root": post_root,
        "transcription_manifest": whisper / "_manifests" / "transcription_run_manifest.json",
        "selection_manifest": selected_whisper / SELECTION_MANIFEST,
        "prepare_manifest": prepared.parent / "_manifests" / f"{prepared.name}_prepare_run_manifest.json",
        "rocksteady_manifest": extra_csv / "_manifests" / "rocksteady_run_manifest.json",
        "derived_manifest": selected_csv / DERIVED_MANIFEST,
        "selected_post_manifest": post_root / "selected" / "output_manifest.json",
        "extra_post_manifest": post_root / "extra" / "output_manifest.json",
        "postprocess_pair_manifest": post_root / BATCH_MANIFEST_FILE,
    }


def _validate_pipeline_paths(paths: Mapping[str, Path]) -> None:
    if not paths["input"].exists():
        raise FileNotFoundError(f"Text input path does not exist: {paths['input']}")
    assert_safe_output_target(paths["whisper"], paths["input"])
    assert_safe_output_target(
        paths["selected_whisper"], paths["whisper"] / "original", paths["whisper"] / "eng"
    )
    assert_safe_output_target(paths["prepared"], paths["selected_whisper"])
    assert_safe_output_target(paths["extra_csv"], paths["prepared"])
    assert_safe_output_target(paths["selected_csv"], paths["extra_csv"])
    assert_safe_output_target(paths["selected_post"], paths["selected_csv"])
    assert_safe_output_target(paths["extra_post"], paths["extra_csv"])
    destructive = [
        paths[name]
        for name in (
            "selected_whisper",
            "prepared",
            "extra_csv",
            "selected_csv",
            "post_root",
        )
    ]
    for output in destructive:
        assert_safe_output_target(output, paths["input"])
    for index, left in enumerate(destructive):
        for right in destructive[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError(
                    "Text stage output directories must be distinct and non-overlapping: "
                    f"{left} vs {right}"
                )


def _preflight_stage_targets(
    paths: Mapping[str, Path], stages: Sequence[str]
) -> None:
    """Fail before expensive work if a requested snapshot cannot be published."""

    requested = set(stages)
    if "select" in requested:
        assert_replaceable_stage_target(paths["selected_whisper"], "selection")
    if "prepare" in requested:
        assert_replaceable_stage_target(paths["prepared"], "prepare-batch")
    if "rocksteady" in requested:
        assert_replaceable_stage_target(paths["extra_csv"], "rocksteady")
        assert_replaceable_stage_target(paths["selected_csv"], "derived-view")
    if "postprocess" in requested:
        assert_publishable_output(paths["post_root"], scope="pair")


def _stage_inputs(stage: str, paths: Mapping[str, Path]) -> list[str]:
    values = {
        "transcribe": [paths["input"]],
        "select": [paths["whisper"], paths["transcription_manifest"]],
        "prepare": [paths["selected_whisper"], paths["selection_manifest"]],
        "rocksteady": [paths["prepared"], paths["prepare_manifest"]],
        "postprocess": [
            paths["selected_csv"], paths["extra_csv"], paths["selected_whisper"], paths["prepared"]
        ],
    }
    return [str(path) for path in values[stage]]


def _stage_outputs(stage: str, paths: Mapping[str, Path]) -> list[str]:
    values = {
        "transcribe": [paths["whisper"], paths["transcription_manifest"]],
        "select": [paths["selected_whisper"], paths["selection_manifest"]],
        "prepare": [paths["prepared"], paths["prepare_manifest"]],
        "rocksteady": [
            paths["extra_csv"], paths["selected_csv"], paths["rocksteady_manifest"], paths["derived_manifest"]
        ],
        "postprocess": [paths["selected_post"], paths["extra_post"]],
    }
    return [str(path) for path in values[stage]]


def _run_rocksteady_pair_stage(
    settings: TextProcessingConfig,
    root: Path,
    paths: Mapping[str, Path],
    current_run_id: str,
    inventory_items: list[dict[str, object]],
    active_record: dict[str, object],
) -> tuple[dict[str, object], int]:
    """Build, validate, and publish canonical RockSteady all/core together.

    Neither visible root is touched until both candidate snapshots pass their
    complete contracts.  Publication then uses a two-directory journal, so an
    ordinary failure or Ctrl-C restores both previous roots; a hard crash is
    recovered by the next compatible Text writer before it reads either root.
    """

    prepare_payload = _read_completed_manifest(paths["prepare_manifest"], "prepare")
    _validate_prepare_manifest(prepare_payload, paths)
    _validate_prepare_artifacts(paths)
    all_target = paths["extra_csv"]
    core_target = paths["selected_csv"]
    effective_categories = _effective_rocksteady_categories(settings.categories)
    all_staging: Path | None = None
    core_staging: Path | None = None

    with rocksteady_pair_transaction(
        all_target,
        core_target,
        purpose="building and publishing the RockSteady all/core pair",
    ) as transaction:
        try:
            all_staging = create_stage_directory(all_target, "rocksteady")
            core_staging = create_stage_directory(core_target, "derived-view")
            staged_rocksteady_manifest = (
                all_staging / "_manifests" / "rocksteady_run_manifest.json"
            )
            command = _rocksteady_command(
                settings,
                root,
                all_staging,
                effective_categories,
                inventory=paths["prepare_manifest"],
                batch_manifest=staged_rocksteady_manifest,
                run_id=current_run_id,
                cache_root=all_target.parent / f".{all_target.name}.rocksteady-cache",
                failure_history_for=all_target,
            )
            active_record["command"] = command
            _run(command, root)

            rock_payload = _read_validated_rocksteady_manifest(
                staged_rocksteady_manifest
            )
            if rock_payload.get("run_id") != current_run_id:
                raise RuntimeError("RockSteady manifest belongs to another Text run")
            _validate_rocksteady_settings(rock_payload, settings)
            _require_upstream_digest(
                rock_payload,
                str(prepare_payload["inventory_sha256"]),
                "RockSteady",
            )

            # Validate into a copy.  The live inventory must not point at a
            # hidden candidate if derivation or publication later fails.
            candidate_inventory = copy.deepcopy(inventory_items)
            csv_paths = _merge_rocksteady(
                candidate_inventory, rock_payload, all_staging
            )
            derived_count = derive_category_view(
                all_staging,
                core_staging,
                CORE_CATEGORIES,
                source_relative_paths=csv_paths,
                upstream_inventory_sha256=str(rock_payload["inventory_sha256"]),
                manifest_source_root=all_target,
                source_ids={
                    str(item["identity"]): str(item.get("source_id") or "")
                    for item in candidate_inventory
                },
            )
            staged_derived_manifest = core_staging / DERIVED_MANIFEST
            derived_payload = _read_completed_manifest(
                staged_derived_manifest, "derived view"
            )
            _validate_derived_manifest(derived_payload, paths)
            _require_upstream_digest(
                derived_payload,
                str(rock_payload["inventory_sha256"]),
                "derived view",
            )
            _merge_derived(candidate_inventory, derived_payload, core_staging)
            derived_sources = {
                str(record.get("source"))
                for record in derived_payload.get("files", [])
                if isinstance(record, Mapping)
            }
            if derived_sources != set(csv_paths):
                raise RuntimeError(
                    "Derived view is not bound to the current RockSteady CSV set"
                )

            _rebase_inventory_paths(candidate_inventory, all_staging, all_target)
            _rebase_inventory_paths(candidate_inventory, core_staging, core_target)
            transaction.publish(all_staging, core_staging)
            inventory_items[:] = candidate_inventory
            return rock_payload, derived_count
        finally:
            # An incomplete rollback retains its journal and candidates for
            # deterministic recovery.  Otherwise remove only exact, owned
            # candidates while the pair lock is still held.
            if not transaction.journal_path.exists():
                _discard_rocksteady_candidate(
                    all_staging, all_target, "rocksteady"
                )
                _discard_rocksteady_candidate(
                    core_staging, core_target, "derived-view"
                )


def _rebase_inventory_paths(
    value: object, staged_root: Path, visible_root: Path
) -> None:
    """Rewrite only inventory ``path`` fields rooted in one validated candidate."""

    if isinstance(value, list):
        for item in value:
            _rebase_inventory_paths(item, staged_root, visible_root)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key == "path" and isinstance(item, str):
            candidate = Path(item)
            if candidate.is_absolute():
                try:
                    relative = candidate.relative_to(staged_root)
                except ValueError:
                    pass
                else:
                    value[key] = str(visible_root / relative)
        else:
            _rebase_inventory_paths(item, staged_root, visible_root)


def _discard_rocksteady_candidate(
    staging: Path | None, target: Path, stage: str
) -> None:
    if staging is None or not staging.exists():
        return
    try:
        discard_stage_directory(staging, target, stage)
    except (OSError, ValueError) as exc:
        warnings.warn(
            f"Could not clean owned {stage} candidate {staging}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )


def _transcribe_command(
    config: TextProcessingConfig, root: Path, batch_manifest: Path | None = None
) -> list[str]:
    input_path = _path(root, config.input_path)
    command = [
        sys.executable, "-m", "processing.text_analysis.transcribe.transcribe",
        "--task", "bilingual", "--model", config.whisper_model,
        "--output-dir", str(_path(root, config.whisper_root)), "--skip-existing",
    ]
    if (
        input_path.is_dir()
        and (
            input_path.name.casefold() == "downloads"
            or (input_path / "downloads").is_dir()
        )
    ):
        command.extend(("--from-procurement", str(input_path)))
    else:
        command.extend((str(input_path), "--speaker-parent-layout"))
    if batch_manifest is not None:
        command.extend(("--batch-manifest", str(batch_manifest)))
    if config.whisper_device != "auto":
        command.extend(("--device", config.whisper_device))
    if config.whisper_language:
        command.extend(("--language", config.whisper_language))
    if config.catalog_sha256:
        command.extend(("--catalog-root", str(input_path)))
        for source_id in config.source_ids:
            command.extend(("--source-id", source_id))
        command.extend(("--catalog-sha256", config.catalog_sha256))
    return command


def _rocksteady_command(
    config: TextProcessingConfig,
    root: Path,
    output: str | Path,
    categories: Sequence[str],
    *,
    inventory: Path | None = None,
    batch_manifest: Path | None = None,
    run_id: str | None = None,
    cache_root: Path | None = None,
    failure_history_for: Path | None = None,
) -> list[str]:
    command = [
        sys.executable, "-m", "processing.text_analysis.rocksteady_adapter",
        str(_path(root, config.prepared_root)), "--output-root", str(_path(root, output)),
        "--dictionary-combination", config.dictionary_combination,
        "--value-type", "total", "--threads", str(config.threads),
    ]
    for dictionary in config.dictionaries:
        command.extend(("--dictionary", dictionary))
    for category in categories:
        command.extend(("--category", category))
    if not categories:
        command.append("--all-categories")
    if inventory is not None:
        command.extend(("--inventory", str(inventory)))
    if batch_manifest is not None:
        command.extend(("--batch-manifest", str(batch_manifest)))
    if run_id is not None:
        command.extend(("--run-id", run_id))
    if cache_root is not None:
        command.extend(("--cache-root", str(cache_root)))
    if failure_history_for is not None:
        command.extend(("--failure-history-for", str(failure_history_for)))
    if config.overwrite_rocksteady:
        command.append("--force")
    return command


def _postprocess_command(
    config: TextProcessingConfig, root: Path, source: str, variant: str
) -> list[str]:
    command = [
        sys.executable, "-m", "analysis.text_pipeline.postprocess", str(_path(root, source)),
        "--whisper-root", str(_path(root, config.selected_whisper_root)),
        "--prepare-root", str(_path(root, config.prepared_root)),
        "--text-lang", "en", "--output-root",
        str(_path(root, config.postprocessing_root) / variant),
    ]
    if not config.write_graphs:
        command.append("--no-graphs")
    return command


def _run(command: Sequence[str], cwd: Path) -> None:
    process = subprocess.Popen(
        list(command), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        shell=False,
        env=credential_free_media_environment(),
    )
    tail: deque[str] = deque(maxlen=50)
    assert process.stdout is not None
    try:
        for line in process.stdout:
            tail.append(line.rstrip())
            try:
                print(line, end="", flush=True)
            except (BrokenPipeError, OSError):
                sys.stdout = open(os.devnull, "w", encoding="utf-8")
        return_code = process.wait()
    except KeyboardInterrupt:
        _terminate_process_tree(process)
        raise
    if return_code:
        diagnostic = "\n".join(tail)
        raise RuntimeError(
            f"Stage command failed with exit code {return_code}: {' '.join(command)}"
            + (f"\nLast output:\n{diagnostic}" if diagnostic else "")
        )


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Stop one stage subprocess and descendants before releasing Text locks."""

    try:
        import psutil

        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        for child in reversed(descendants):
            child.terminate()
        parent.terminate()
        _gone, alive = psutil.wait_procs([*descendants, parent], timeout=5)
        for item in alive:
            item.kill()
        psutil.wait_procs(alive, timeout=5)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    # Keep the lexical path long enough for output validation to detect an
    # existing symlink or Windows junction/reparse component.  ``abspath``
    # normalises ``..`` without following filesystem aliases.
    return lexical_absolute_path(path if path.is_absolute() else root / path)


def _validated_run_id(value: str | None) -> str:
    run_id = uuid.uuid4().hex if value is None else str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise ValueError(
            "run_id must contain only letters, numbers, dot, underscore or hyphen "
            "and must not exceed 128 characters"
        )
    return run_id


def _read_completed_manifest(path: Path, label: str) -> dict[str, object]:
    try:
        contract = MANIFEST_CONTRACTS[label]
    except KeyError as exc:  # internal programming error, never a user manifest error
        raise RuntimeError(f"No Text manifest contract is registered for {label!r}") from exc
    return _strict_read_completed_manifest(path, label, contract)


def _require_upstream_digest(payload: Mapping[str, object], expected: str, label: str) -> None:
    if payload.get("upstream_inventory_sha256") != expected:
        raise RuntimeError(f"{label} manifest is not bound to the expected upstream inventory")


def _validate_transcription_manifest(
    payload: Mapping[str, object],
    settings: TextProcessingConfig,
    paths: Mapping[str, Path],
) -> None:
    validate_transcription_settings(
        payload,
        input_path=paths["input"],
        output_root=paths["whisper"],
        model=settings.whisper_model,
        requested_device=settings.whisper_device,
    )


def _validate_selection_manifest(
    payload: Mapping[str, object],
    settings: TextProcessingConfig,
    paths: Mapping[str, Path],
) -> None:
    validate_selection_settings(
        payload,
        input_path=paths["input"],
        default_variant=settings.default_language_variant,
        language_policy=settings.language_policy,
    )


def _validate_prepare_manifest(
    payload: Mapping[str, object], paths: Mapping[str, Path]
) -> None:
    validate_prepare_settings(
        payload,
        input_root=paths["selected_whisper"],
        output_root=paths["prepared"],
    )


def _validate_derived_manifest(
    payload: Mapping[str, object], paths: Mapping[str, Path]
) -> None:
    validate_derived_settings(
        payload,
        source_root=paths["extra_csv"],
        categories=CORE_CATEGORIES,
    )


def _validate_prepare_artifacts(paths: Mapping[str, Path]) -> None:
    """Verify every prepared segment byte against both upstream inventories."""

    try:
        validate_prepare_batch_artifacts(
            paths["prepared"],
            paths["prepare_manifest"],
            selection_manifest_path=paths["selection_manifest"],
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Prepared Text artifacts failed integrity validation: {exc}") from exc


def _current_adapter_source_sha256() -> str:
    return file_sha256(
        ADAPTER_ROOT
        / "java"
        / "ie"
        / "tcd"
        / "multimodal"
        / "rocksteady"
        / "RockSteadyCli.java"
    )


def _read_validated_rocksteady_manifest(path: Path) -> dict[str, object]:
    """Read one completed adapter manifest and bind it to current bridge code."""

    payload = _read_completed_manifest(path, "RockSteady")
    try:
        validated = validate_rocksteady_batch_manifest(
            path,
            expected_adapter_source_sha256=_current_adapter_source_sha256(),
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"RockSteady artifacts failed integrity validation: {exc}") from exc
    if validated != payload:
        raise RuntimeError("RockSteady manifest changed while it was being validated")
    return payload


def _validate_rocksteady_settings(
    payload: Mapping[str, object], settings: TextProcessingConfig
) -> None:
    manifest_settings = payload.get("settings")
    if not isinstance(manifest_settings, dict):
        raise RuntimeError("RockSteady manifest has no settings contract")
    expected_dictionaries: list[dict[str, str]] = []
    for value in settings.dictionaries:
        source, separator, dictionary_path = value.partition(":")
        if not separator:
            raise RuntimeError(f"Invalid configured RockSteady dictionary: {value}")
        expected_dictionaries.append({"source": source, "path": dictionary_path})
    expected_contract = {
        "dictionaries": expected_dictionaries,
        "combination": settings.dictionary_combination,
        "analyser": "simple",
        "value_type": "total",
        "categories": list(_effective_rocksteady_categories(settings.categories)),
        "threads": settings.threads,
    }
    if any(manifest_settings.get(key) != value for key, value in expected_contract.items()):
        raise RuntimeError("RockSteady inventory settings do not match the current Text config")


def _successful_identities(items: Sequence[Mapping[str, object]]) -> list[str]:
    identities = [str(item["identity"]) for item in items if item.get("status") == "completed"]
    if not identities:
        raise RuntimeError("Text inventory contains no completed video identities")
    return identities


def _inventory_from_transcription(
    payload: Mapping[str, object], whisper_root: Path
) -> list[dict[str, object]]:
    raw_videos = payload.get("videos")
    if not isinstance(raw_videos, list) or not raw_videos:
        raise RuntimeError("Transcription manifest has no video inventory")
    items: list[dict[str, object]] = []
    identities: set[str] = set()
    batch_config = payload.get("config")
    batch_provenance = payload.get("whisper_provenance")
    if not isinstance(batch_config, dict) or not isinstance(batch_provenance, dict):
        raise RuntimeError("Transcription manifest lacks config/provenance contracts")
    expected_tasks = {"original": "transcribe", "eng": "translate", "bilingual": "bilingual"}
    for raw in raw_videos:
        if not isinstance(raw, dict) or raw.get("status") not in {"completed", "skipped"}:
            raise RuntimeError("Transcription manifest contains an incomplete video")
        identity = raw.get("identity")
        if not isinstance(identity, str) or identity in identities:
            raise RuntimeError(f"Invalid or duplicate transcription identity: {identity!r}")
        identities.add(identity)
        artifacts: dict[str, object] = {}
        artifact_paths: dict[str, Path] = {}
        artifact_hashes: dict[str, str] = {}
        raw_artifacts = raw.get("artifacts")
        item_provenance = raw.get("whisper_provenance") or batch_provenance
        if not isinstance(item_provenance, dict):
            raise RuntimeError(f"Transcription item lacks Whisper provenance for {identity}")
        if not isinstance(raw_artifacts, dict) or set(raw_artifacts) != set(expected_tasks):
            raise RuntimeError(f"Transcription artifacts are malformed for {identity}")
        for kind, artifact_value in raw_artifacts.items():
            if isinstance(artifact_value, str):
                artifact = {"path": artifact_value}
            elif isinstance(artifact_value, dict):
                artifact = dict(artifact_value)
            else:
                raise RuntimeError(f"Transcription artifact is malformed for {identity}")
            relative_value = artifact.get("path")
            if not isinstance(relative_value, str) or not relative_value:
                raise RuntimeError(f"Transcription artifact path is missing for {identity}")
            relative = Path(relative_value)
            path = (whisper_root / relative).resolve()
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not path.is_relative_to(whisper_root.resolve())
                or not path.is_file()
            ):
                raise RuntimeError(f"Transcription artifact is missing or unsafe: {path}")
            digest = artifact.get("sha256")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
                raise RuntimeError(f"Transcription artifact has no valid SHA-256: {path}")
            if file_sha256(path) != digest.casefold():
                raise RuntimeError(f"Transcription artifact hash mismatch: {path}")
            try:
                transcript = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Transcription artifact is invalid JSON: {path}: {exc}") from exc
            if not isinstance(transcript, dict):
                raise RuntimeError(f"Transcription artifact must contain an object: {path}")
            if transcript.get("schema_version") != TEXT_SCHEMA_VERSION:
                raise RuntimeError(f"Transcription artifact has an unsupported schema: {path}")
            if transcript.get("task") != expected_tasks[kind]:
                raise RuntimeError(f"Transcription artifact task mismatch: {path}")
            if transcript.get("model") != batch_config.get("model"):
                raise RuntimeError(f"Transcription artifact model mismatch: {path}")
            if transcript.get("source_sha256") != raw.get("source_sha256"):
                raise RuntimeError(f"Transcription artifact source hash mismatch: {path}")
            if transcript.get("whisper_provenance") != item_provenance.get(kind):
                raise RuntimeError(f"Transcription artifact Whisper provenance mismatch: {path}")
            if str(transcript.get("source_id") or "") != str(raw.get("source_id") or ""):
                raise RuntimeError(f"Transcription artifact SourceID mismatch: {path}")
            if transcript.get("catalog_binding", {}) != raw.get("catalog_binding", {}):
                raise RuntimeError(f"Transcription artifact catalog binding mismatch: {path}")
            if not isinstance(transcript.get("segments"), list) or not transcript["segments"]:
                raise RuntimeError(f"Transcription artifact has no segments: {path}")
            artifact_paths[str(kind)] = path
            artifact_hashes[str(kind)] = digest.casefold()
            artifacts[str(kind)] = {**artifact, "path": str(path)}
        try:
            validate_transcription_artifact_set(
                artifact_paths,
                expected_model=str(batch_config["model"]),
                expected_source_sha256=str(raw.get("source_sha256")),
                expected_provenance_by_kind=item_provenance,
                expected_artifact_sha256_by_kind=artifact_hashes,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Transcription artifacts failed integrity validation for {identity}: {exc}"
            ) from exc
        items.append(
            {
                "source_path": raw.get("source_path"),
                "source_relative": raw.get("source_relative"),
                "source_id": str(raw.get("source_id") or ""),
                "catalog_binding": dict(raw.get("catalog_binding") or {}),
                "requested_language": str(raw.get("requested_language") or ""),
                "video_stem": raw.get("video_stem"),
                "identity": identity,
                "status": "completed",
                "source_fingerprint": raw.get("source_fingerprint"),
                "source_sha256": raw.get("source_sha256"),
                "stages": {"transcribe": {"status": raw.get("status"), "artifacts": artifacts}},
            }
        )
    return items


def _validate_source_provenance(items: Sequence[Mapping[str, object]]) -> None:
    for item in items:
        source = Path(str(item.get("source_path", "")))
        if not source.is_file():
            raise RuntimeError(f"Inventory source is missing: {source}")
        digest = item.get("source_sha256")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None
            or file_sha256(source) != digest.casefold()
        ):
            raise RuntimeError(f"Inventory source content changed: {source}")


def _by_identity(items: Sequence[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["identity"]): item for item in items}


def _safe_inventory_artifact(
    root: Path,
    value: object,
    label: str,
    *,
    directory: bool = False,
) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} artifact path is missing")
    relative = Path(value)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root.resolve()):
        raise RuntimeError(f"{label} artifact path is unsafe: {value!r}")
    exists = path.is_dir() if directory else path.is_file()
    if not exists:
        kind = "directory" if directory else "file"
        raise RuntimeError(f"{label} artifact {kind} is missing: {path}")
    return path


def _assert_identity_set(
    inventory: Sequence[dict[str, object]], records: Sequence[Mapping[str, object]], label: str
) -> None:
    expected = set(_by_identity(inventory))
    actual_values = [str(record.get("identity")) for record in records]
    actual = set(actual_values)
    if len(actual) != len(actual_values):
        raise RuntimeError(f"{label} identity inventory contains duplicates")
    if actual != expected:
        raise RuntimeError(
            f"{label} identity inventory mismatch; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    expected_source_ids = {
        str(item["identity"]): str(item.get("source_id") or "") for item in inventory
    }
    for record in records:
        identity = str(record.get("identity"))
        if str(record.get("source_id") or "") != expected_source_ids[identity]:
            raise RuntimeError(f"{label} SourceID does not match inventory identity {identity}")


def _merge_selection(
    items: list[dict[str, object]], payload: Mapping[str, object], root: Path
) -> None:
    records = payload.get("files")
    if not isinstance(records, list):
        raise RuntimeError("Selection manifest has no files inventory")
    _assert_identity_set(items, records, "selection")
    index = _by_identity(items)
    for raw in records:
        assert isinstance(raw, dict)
        path = _safe_inventory_artifact(root, raw.get("output"), "Selection")
        digest = raw.get("source_sha256")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None
            or file_sha256(path) != digest.casefold()
        ):
            raise RuntimeError(f"Selected transcript is missing or changed: {path}")
        index[str(raw["identity"])]["stages"]["select"] = {
            "status": "completed", "variant": raw.get("variant"),
            "artifacts": {"json": {"path": str(path), "sha256": raw.get("source_sha256")}},
        }


def _merge_prepare(
    items: list[dict[str, object]], payload: Mapping[str, object], root: Path
) -> None:
    records = payload.get("videos")
    if not isinstance(records, list):
        raise RuntimeError("Prepare manifest has no video inventory")
    _assert_identity_set(items, records, "prepare")
    index = _by_identity(items)
    for raw in records:
        assert isinstance(raw, dict)
        path = _safe_inventory_artifact(
            root, raw.get("artifact"), "Prepare", directory=True
        )
        identity = str(raw["identity"])
        selected_sha = (
            index[identity]
            .get("stages", {})
            .get("select", {})
            .get("artifacts", {})
            .get("json", {})
            .get("sha256")
        )
        if raw.get("source_sha256") != selected_sha:
            raise RuntimeError(f"Prepared input source hash mismatch for {identity}")
        index[str(raw["identity"])]["stages"]["prepare"] = {
            "status": "completed", "segment_count": raw.get("segment_count"),
            "artifacts": {"segments": {"path": str(path)}},
        }


def _merge_rocksteady(
    items: list[dict[str, object]], payload: Mapping[str, object], root: Path
) -> list[str]:
    records = payload.get("videos")
    if not isinstance(records, list):
        raise RuntimeError("RockSteady manifest has no video inventory")
    _assert_identity_set(items, records, "RockSteady")
    index = _by_identity(items)
    relative_paths: list[str] = []
    for raw in records:
        assert isinstance(raw, dict)
        relative = str(raw["output"])
        path = _safe_inventory_artifact(root, relative, "RockSteady")
        digest = raw.get("output_sha256")
        if not path.is_file() or not isinstance(digest, str) or file_sha256(path) != digest:
            raise RuntimeError(f"RockSteady CSV is missing or changed: {path}")
        relative_paths.append(relative)
        index[str(raw["identity"])]["stages"]["rocksteady"] = {
            "status": raw.get("status"),
            "artifacts": {"extra_csv": {"path": str(path), "sha256": digest}},
            "validation": raw.get("validation"),
        }
    return relative_paths


def _merge_derived(
    items: list[dict[str, object]], payload: Mapping[str, object], root: Path
) -> None:
    records = payload.get("files")
    if not isinstance(records, list):
        raise RuntimeError("Derived manifest has no files inventory")
    _assert_identity_set(items, records, "derived view")
    index = _by_identity(items)
    for raw in records:
        assert isinstance(raw, dict)
        path = _safe_inventory_artifact(root, raw.get("output"), "Derived view")
        digest = raw.get("output_sha256")
        if not path.is_file() or not isinstance(digest, str) or file_sha256(path) != digest:
            raise RuntimeError(f"Derived CSV is missing or changed: {path}")
        stage = index[str(raw["identity"])]["stages"]["rocksteady"]
        extra_artifact = stage.get("artifacts", {}).get("extra_csv", {})
        if (
            not isinstance(extra_artifact, dict)
            or raw.get("source_sha256") != extra_artifact.get("sha256")
            or raw.get("source") != raw.get("output")
        ):
            raise RuntimeError(
                f"Derived CSV is not bound to the canonical RockSteady CSV: {path}"
            )
        stage["artifacts"]["selected_csv"] = {"path": str(path), "sha256": digest}


def _validate_postprocess_identity_set(
    items: Sequence[dict[str, object]], payload: Mapping[str, object], label: str
) -> None:
    videos = payload.get("videos")
    if not isinstance(videos, list):
        raise RuntimeError(f"{label} postprocessing manifest has no videos")
    identities = {
        "/".join(
            str(value)
            for value in (
                video.get("country"),
                video.get("speaker"),
                video.get("video"),
            )
            if value is not None and str(value)
        )
        for video in videos
        if isinstance(video, dict)
    }
    expected = set(_by_identity(items))
    if identities != expected:
        raise RuntimeError(f"{label} postprocessing identity inventory mismatch")
    expected_source_ids = {
        str(item["identity"]): str(item.get("source_id") or "") for item in items
    }
    for video in videos:
        if not isinstance(video, dict):
            continue
        identity = "/".join(
            str(value)
            for value in (video.get("country"), video.get("speaker"), video.get("video"))
            if value is not None and str(value)
        )
        if str(video.get("source_id") or "") != expected_source_ids[identity]:
            raise RuntimeError(
                f"{label} postprocessing SourceID does not match inventory identity {identity}"
            )


def _validate_postprocess_pair(
    payload: Mapping[str, object], run_id: str, paths: Mapping[str, Path]
) -> None:
    if payload.get("kind") != PAIR_KIND:
        raise RuntimeError("Paired postprocessing manifest has the wrong kind")
    if payload.get("run_id") != run_id:
        raise RuntimeError("Paired postprocessing manifest belongs to another run")
    variants = payload.get("variants")
    if not isinstance(variants, dict) or not all(
        isinstance(variants.get(name), dict) for name in ("selected", "extra")
    ):
        raise RuntimeError("Paired postprocessing manifest has no selected/extra contract")
    for name in ("selected", "extra"):
        record = variants[name]
        assert isinstance(record, dict)
        expected_hash = record.get("output_manifest_sha256")
        manifest_path = paths[f"{name}_post_manifest"]
        if not isinstance(expected_hash, str) or file_sha256(manifest_path) != expected_hash:
            raise RuntimeError(
                f"Paired postprocessing manifest hash differs for {name}"
            )


def _merge_postprocess(items: list[dict[str, object]], paths: Mapping[str, Path]) -> None:
    for item in items:
        item["stages"]["postprocess"] = {
            "status": "completed",
            "artifacts": {
                "selected_output": {"path": str(paths["selected_post"])},
                "extra_output": {"path": str(paths["extra_post"])},
            },
        }


def _load_upstream_inventory(
    settings: TextProcessingConfig, paths: Mapping[str, Path], start_index: int
) -> tuple[list[dict[str, object]], dict[str, object]]:
    transcribe = _read_completed_manifest(paths["transcription_manifest"], "transcription")
    _validate_transcription_manifest(transcribe, settings, paths)
    items = _inventory_from_transcription(transcribe, paths["whisper"])
    _validate_source_provenance(items)
    artifacts: dict[str, object] = {
        "transcribe": {
            "root": str(paths["whisper"]), "manifest": str(paths["transcription_manifest"])
        }
    }
    if start_index >= 2:
        selection = _read_completed_manifest(paths["selection_manifest"], "language selection")
        _validate_selection_manifest(selection, settings, paths)
        _require_upstream_digest(selection, str(transcribe["inventory_sha256"]), "selection")
        _merge_selection(items, selection, paths["selected_whisper"])
        artifacts["select"] = {
            "root": str(paths["selected_whisper"]), "manifest": str(paths["selection_manifest"])
        }
    if start_index >= 3:
        prepare = _read_completed_manifest(paths["prepare_manifest"], "prepare")
        selection = _read_completed_manifest(paths["selection_manifest"], "language selection")
        _validate_selection_manifest(selection, settings, paths)
        _validate_prepare_manifest(prepare, paths)
        _require_upstream_digest(prepare, str(selection["inventory_sha256"]), "prepare")
        _validate_prepare_artifacts(paths)
        _merge_prepare(items, prepare, paths["prepared"])
        artifacts["prepare"] = {
            "root": str(paths["prepared"]), "manifest": str(paths["prepare_manifest"])
        }
    if start_index >= 4:
        rocksteady = _read_validated_rocksteady_manifest(paths["rocksteady_manifest"])
        prepare = _read_completed_manifest(paths["prepare_manifest"], "prepare")
        _validate_prepare_manifest(prepare, paths)
        _validate_prepare_artifacts(paths)
        _require_upstream_digest(rocksteady, str(prepare["inventory_sha256"]), "RockSteady")
        _validate_rocksteady_settings(rocksteady, settings)
        csv_paths = _merge_rocksteady(items, rocksteady, paths["extra_csv"])
        derived = _read_completed_manifest(paths["derived_manifest"], "derived view")
        _validate_derived_manifest(derived, paths)
        _require_upstream_digest(derived, str(rocksteady["inventory_sha256"]), "derived view")
        _merge_derived(items, derived, paths["selected_csv"])
        if {str(record.get("source")) for record in derived.get("files", [])} != set(csv_paths):
            raise RuntimeError("Derived view is not bound to the current RockSteady CSV set")
        artifacts["rocksteady"] = {
            "extra_root": str(paths["extra_csv"]), "selected_root": str(paths["selected_csv"]),
            "manifest": str(paths["rocksteady_manifest"]),
            "derived_manifest": str(paths["derived_manifest"]),
        }
    return items, artifacts


def _inventory_payload(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    copied = [dict(item) for item in items]
    digest = inventory_digest(copied)
    return {"digest": digest, "inventory_sha256": digest, "items": copied}


def _write_manifest(
    paths: Sequence[Path],
    config: TextProcessingConfig,
    run_id: str,
    started: datetime,
    stages: list[dict[str, object]],
    inventory_items: list[dict[str, object]],
    artifacts: Mapping[str, object],
    status: str,
) -> None:
    inventory = _inventory_payload(inventory_items)
    payload = {
        "schema_version": TEXT_SCHEMA_VERSION,
        "kind": "text-processing-pipeline",
        "run_id": run_id,
        "status": status,
        "started_at": started.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat()
        if status in {"completed", "failed", "cancelled"} else None,
        "config": asdict(config),
        "catalog_sha256": config.catalog_sha256,
        "processed_source_ids": list(config.source_ids),
        "summary": {
            "videos": len(inventory_items),
            "completed_stages": sum(record.get("status") == "completed" for record in stages),
            "failed_stages": sum(record.get("status") == "failed" for record in stages),
            "cancelled_stages": sum(record.get("status") == "cancelled" for record in stages),
        },
        "inventory": inventory,
        "artifacts": dict(artifacts),
        "stages": stages,
    }
    for path in paths:
        atomic_write_json(path, payload)
