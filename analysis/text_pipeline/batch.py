"""Atomic selected/extra orchestration for text postprocessing."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from analysis.histograms import default_output_root
from analysis.text_pipeline.postprocess import (
    DEFAULT_SEGMENT_SAMPLE_COUNTS,
    TextAnalysisResult,
    analyse_text_segments_folder,
    normalize_segment_alignment_policy,
    normalize_segment_sample_counts,
    normalize_text_language,
    resolve_prepare_root,
    resolve_segment_input_folder,
    resolve_whisper_root,
)
from analysis.text_pipeline.ownership import (
    BATCH_MANIFEST_FILE,
    PAIR_KIND,
    assert_publishable_output,
    normalize_run_id,
    text_output_lock,
    validate_distinct_variant_inputs,
    validate_output_boundaries,
    write_output_owner,
)
from analysis.text_pipeline.constructs import write_construct_alignment
from analysis.text_pipeline.distribution_comparisons import (
    DEFAULT_PERMUTATIONS,
    DEFAULT_RANDOM_SEED,
)
from analysis.text_pipeline.provenance import sha256_file
from analysis.text_pipeline.transaction import replace_output_dir
from processing.io_utils import atomic_write_json, make_staging_directory


@dataclass(frozen=True)
class TextPairAnalysisResult:
    """Published paths and summaries for one indivisible selected/extra run."""

    run_id: str
    output_root: Path
    batch_manifest_path: Path
    selected: TextAnalysisResult
    extra: TextAnalysisResult
    identity_count: int


def analyse_text_segment_pair(
    selected_input_folder: str | Path,
    extra_input_folder: str | Path,
    output_root: str | Path | None = None,
    *,
    whisper_root: str | Path | None = None,
    prepare_root: str | Path | None = None,
    write_graphs: bool = True,
    segment_sample_counts: Sequence[int] = DEFAULT_SEGMENT_SAMPLE_COUNTS,
    segment_alignment: str = "error",
    text_language: str = "original",
    run_id: str | None = None,
) -> TextPairAnalysisResult:
    """Generate selected and extra outputs, then publish them as one directory.

    Neither visible variant changes until both variants are complete and their
    identity/source contracts agree.  A failure at generation, validation, or
    final publication therefore leaves the previous complete pair untouched.
    """

    selected_input = resolve_segment_input_folder(selected_input_folder)
    extra_input = resolve_segment_input_folder(extra_input_folder)
    for label, path in (("selected", selected_input), ("extra", extra_input)):
        if not path.is_dir():
            raise NotADirectoryError(f"{label.capitalize()} input folder does not exist: {path}")
    validate_distinct_variant_inputs(selected_input, extra_input)

    requested_output_root = (
        Path(output_root).expanduser()
        if output_root is not None
        else (
            default_output_root() / "text" / "text_output"
        )
    )
    resolved_whisper_root = resolve_whisper_root(
        whisper_root,
        input_dir=selected_input,
    )
    resolved_prepare_root = resolve_prepare_root(prepare_root)
    final_root = validate_output_boundaries(
        requested_output_root,
        (
            selected_input,
            extra_input,
            resolved_whisper_root,
            resolved_prepare_root,
        ),
    )

    sample_counts = normalize_segment_sample_counts(segment_sample_counts)
    alignment_policy = normalize_segment_alignment_policy(segment_alignment)
    selected_text_language = normalize_text_language(text_language)
    effective_run_id = normalize_run_id(run_id)

    with text_output_lock(final_root, scope="pair"):
        ownership = assert_publishable_output(final_root, scope="pair")
        final_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root = make_staging_directory(
            final_root.parent,
            f".{final_root.name}_pair_",
        )
        try:
            staged_selected = analyse_text_segments_folder(
                selected_input,
                output_root=staging_root / "selected",
                whisper_root=resolved_whisper_root,
                prepare_root=resolved_prepare_root,
                write_graphs=write_graphs,
                segment_sample_counts=sample_counts,
                segment_alignment=alignment_policy,
                text_language=selected_text_language,
                run_id=effective_run_id,
                output_variant="selected",
                _reported_output_root=final_root / "selected",
            )
            staged_extra = analyse_text_segments_folder(
                extra_input,
                output_root=staging_root / "extra",
                whisper_root=resolved_whisper_root,
                prepare_root=resolved_prepare_root,
                write_graphs=write_graphs,
                segment_sample_counts=sample_counts,
                segment_alignment=alignment_policy,
                text_language=selected_text_language,
                run_id=effective_run_id,
                output_variant="extra",
                _reported_output_root=final_root / "extra",
            )
            multimodal_contract = write_construct_alignment(
                staging_root / "extra",
                variant="extra",
                output_root=staging_root / "multimodal",
            )

            selected_manifest = _read_completed_variant_manifest(
                staging_root / "selected" / "output_manifest.json",
                expected_variant="selected",
                expected_run_id=effective_run_id,
            )
            extra_manifest = _read_completed_variant_manifest(
                staging_root / "extra" / "output_manifest.json",
                expected_variant="extra",
                expected_run_id=effective_run_id,
            )
            identity_contract = validate_pair_identity_contract(
                selected_manifest,
                extra_manifest,
            )
            lineage_contract = validate_pair_lineage_contract(
                selected_manifest,
                extra_manifest,
            )
            batch_manifest = _build_batch_manifest(
                run_id=effective_run_id,
                final_root=final_root,
                selected_input=selected_input,
                extra_input=extra_input,
                whisper_root=resolved_whisper_root,
                prepare_root=resolved_prepare_root,
                write_graphs=write_graphs,
                sample_counts=sample_counts,
                alignment_policy=alignment_policy,
                text_language=selected_text_language,
                previous_ownership_state=ownership.state,
                selected_manifest_path=staging_root / "selected" / "output_manifest.json",
                extra_manifest_path=staging_root / "extra" / "output_manifest.json",
                selected_manifest=selected_manifest,
                extra_manifest=extra_manifest,
                identity_contract=identity_contract,
                lineage_contract=lineage_contract,
                multimodal_contract=multimodal_contract,
            )
            atomic_write_json(staging_root / BATCH_MANIFEST_FILE, batch_manifest)
            write_output_owner(
                staging_root,
                scope="pair",
                run_id=effective_run_id,
            )
            validate_output_boundaries(
                final_root,
                (
                    selected_input,
                    extra_input,
                    resolved_whisper_root,
                    resolved_prepare_root,
                ),
            )
            replace_output_dir(staging_root, final_root)
        except BaseException:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            raise

    selected_result = _rebase_result(
        staged_selected,
        staged_selected.output_dir,
        final_root / "selected",
    )
    extra_result = _rebase_result(
        staged_extra,
        staged_extra.output_dir,
        final_root / "extra",
    )
    return TextPairAnalysisResult(
        run_id=effective_run_id,
        output_root=final_root,
        batch_manifest_path=final_root / BATCH_MANIFEST_FILE,
        selected=selected_result,
        extra=extra_result,
        identity_count=len(identity_contract),
    )


def validate_pair_identity_contract(
    selected_manifest: Mapping[str, object],
    extra_manifest: Mapping[str, object],
) -> Mapping[str, Mapping[str, object]]:
    """Require both variants to describe the same videos and source evidence."""

    selected = _video_source_contract(selected_manifest, "selected")
    extra = _video_source_contract(extra_manifest, "extra")
    selected_ids = set(selected)
    extra_ids = set(extra)
    if selected_ids != extra_ids:
        raise ValueError(
            "Selected/extra postprocessing identity sets differ: "
            f"missing_from_extra={sorted(selected_ids - extra_ids)[:12]}, "
            f"missing_from_selected={sorted(extra_ids - selected_ids)[:12]}"
        )
    mismatched = [
        identity
        for identity in sorted(selected_ids)
        if selected[identity] != extra[identity]
    ]
    if mismatched:
        examples = {
            identity: {
                "selected": selected[identity],
                "extra": extra[identity],
            }
            for identity in mismatched[:5]
        }
        raise ValueError(
            "Selected/extra postprocessing source evidence differs for common identities: "
            f"{json.dumps(examples, ensure_ascii=False, sort_keys=True)}"
        )
    return {identity: selected[identity] for identity in sorted(selected)}


def validate_pair_lineage_contract(
    selected_manifest: Mapping[str, object],
    extra_manifest: Mapping[str, object],
) -> Mapping[str, object]:
    """Prove that a verified selected view was derived from this extra batch.

    Matching transcripts alone are not enough: two unrelated RockSteady runs
    over the same videos could have different dictionaries, analyser settings,
    or results.  The selected derived-view provenance therefore has to point
    at the exact adapter manifest used by the extra variant, by resolved path,
    source root, and SHA-256.

    Manifest-less standalone inputs remain supported, but the pair manifest
    labels that relationship ``legacy_unverified`` instead of claiming proof.
    A mixed verified/unverified pair is rejected because its lineage cannot be
    established safely.
    """

    selected_provenance = _upstream_provenance(selected_manifest, "selected")
    extra_provenance = _upstream_provenance(extra_manifest, "extra")
    selected_verified = str(selected_provenance.get("status", "")).startswith("verified_")
    extra_verified = str(extra_provenance.get("status", "")).startswith("verified_")
    if not selected_verified and not extra_verified:
        return {
            "status": "legacy_unverified",
            "reason": "Neither variant has a verified upstream manifest lineage.",
        }
    if not selected_verified or not extra_verified:
        raise ValueError(
            "Selected/extra upstream lineage mixes verified and unverified inputs; "
            "re-run both variants from the same manifest-backed RockSteady batch."
        )
    if selected_provenance.get("kind") != "derived-rocksteady-category-view":
        raise ValueError(
            "Verified selected output is not a derived RockSteady category view, so its "
            "relationship to the extra batch cannot be proven."
        )
    if extra_provenance.get("kind") != "rocksteady-adapter-batch":
        raise ValueError(
            "Verified extra output is not backed by a RockSteady adapter batch manifest."
        )

    selected_details = selected_provenance.get("details")
    if not isinstance(selected_details, dict):
        raise ValueError("Verified selected provenance has no source-lineage details")
    selected_source_hash = selected_details.get("source_manifest_sha256")
    extra_manifest_hash = extra_provenance.get("manifest_sha256")
    if not _is_sha256(selected_source_hash) or not _is_sha256(extra_manifest_hash):
        raise ValueError(
            "Verified selected/extra provenance lacks a complete source manifest SHA-256"
        )
    if str(selected_source_hash).casefold() != str(extra_manifest_hash).casefold():
        raise ValueError(
            "Selected derived view belongs to a different RockSteady adapter manifest "
            "than the extra output."
        )

    selected_source_root = _resolved_path_field(
        selected_details.get("source_root"),
        "selected upstream_provenance.details.source_root",
    )
    extra_inputs = extra_manifest.get("inputs")
    if not isinstance(extra_inputs, dict):
        raise ValueError("Extra output manifest has no inputs contract")
    extra_input_root = _resolved_path_field(
        extra_inputs.get("rocksteady_csv_root"),
        "extra inputs.rocksteady_csv_root",
    )
    if selected_source_root != extra_input_root:
        raise ValueError(
            "Selected derived-view source_root is not the extra RockSteady input root: "
            f"selected_source={selected_source_root}, extra_input={extra_input_root}"
        )

    selected_source_manifest = _resolved_path_field(
        selected_details.get("source_manifest_path"),
        "selected upstream_provenance.details.source_manifest_path",
    )
    extra_manifest_path = _resolved_path_field(
        extra_provenance.get("manifest_path"),
        "extra upstream_provenance.manifest_path",
    )
    if selected_source_manifest != extra_manifest_path:
        raise ValueError(
            "Selected derived view points to a different source manifest path than extra: "
            f"selected_source={selected_source_manifest}, extra_manifest={extra_manifest_path}"
        )
    expected_extra_manifest = (
        extra_input_root / "_manifests" / "rocksteady_run_manifest.json"
    ).resolve()
    if extra_manifest_path != expected_extra_manifest:
        raise ValueError(
            "Extra upstream manifest is not inside its declared RockSteady input root: "
            f"expected={expected_extra_manifest}, found={extra_manifest_path}"
        )

    return {
        "status": "verified_sha256",
        "selected_derived_manifest_sha256": selected_provenance.get("manifest_sha256"),
        "source_adapter_manifest": str(extra_manifest_path),
        "source_adapter_manifest_sha256": str(extra_manifest_hash).casefold(),
        "source_root": str(extra_input_root),
    }


def _video_source_contract(
    manifest: Mapping[str, object],
    label: str,
) -> dict[str, Mapping[str, object]]:
    videos = manifest.get("videos")
    if not isinstance(videos, list) or not videos:
        raise ValueError(f"{label.capitalize()} output manifest has no video records")
    result: dict[str, Mapping[str, object]] = {}
    for row_number, item in enumerate(videos, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{label.capitalize()} video record {row_number} is not an object")
        country = item.get("country")
        speaker = item.get("speaker")
        video = item.get("video")
        if (
            not isinstance(country, str)
            or not isinstance(speaker, str)
            or not speaker
            or not isinstance(video, str)
            or not video
        ):
            raise ValueError(
                f"{label.capitalize()} video record {row_number} has an invalid identity"
            )
        identity = "/".join(part for part in (country, speaker, video) if part)
        if identity in result:
            raise ValueError(f"{label.capitalize()} output repeats identity {identity!r}")
        whisper_hash = item.get("whisper_json_sha256")
        if not isinstance(whisper_hash, str) or len(whisper_hash) != 64:
            raise ValueError(f"{label.capitalize()} output lacks a Whisper hash for {identity}")
        alignment = item.get("alignment_mapping")
        if not isinstance(alignment, dict):
            raise ValueError(f"{label.capitalize()} output lacks alignment evidence for {identity}")
        result[identity] = {
            "whisper_json_sha256": whisper_hash,
            "source_whisper_segments": item.get("source_whisper_segments"),
            "prepare_manifest_sha256": alignment.get("manifest_sha256"),
            "alignment_segments": alignment.get("segments"),
        }
    return result


def _upstream_provenance(
    manifest: Mapping[str, object], label: str
) -> Mapping[str, object]:
    provenance = manifest.get("upstream_provenance")
    if not isinstance(provenance, dict):
        raise ValueError(f"{label.capitalize()} output manifest has no upstream provenance")
    return provenance


def _resolved_path_field(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Pair lineage field {field} must be a non-empty path")
    return Path(value).expanduser().resolve()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _read_completed_variant_manifest(
    path: Path,
    *,
    expected_variant: str,
    expected_run_id: str,
) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read generated variant manifest {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Generated variant manifest must be a JSON object: {path}")
    if (
        payload.get("kind") != "text-postprocessing-variant"
        or payload.get("status") != "completed"
        or payload.get("variant") != expected_variant
        or payload.get("run_id") != expected_run_id
    ):
        raise ValueError(
            f"Generated {expected_variant} manifest has a stale or invalid run contract: {path}"
        )
    return payload


def _build_batch_manifest(
    *,
    run_id: str,
    final_root: Path,
    selected_input: Path,
    extra_input: Path,
    whisper_root: Path,
    prepare_root: Path,
    write_graphs: bool,
    sample_counts: Sequence[int],
    alignment_policy: str,
    text_language: str,
    previous_ownership_state: str,
    selected_manifest_path: Path,
    extra_manifest_path: Path,
    selected_manifest: Mapping[str, object],
    extra_manifest: Mapping[str, object],
    identity_contract: Mapping[str, Mapping[str, object]],
    lineage_contract: Mapping[str, object],
    multimodal_contract: Mapping[str, object],
) -> dict[str, object]:
    identity_json = json.dumps(
        identity_contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": "1.0",
        "kind": PAIR_KIND,
        "run_id": run_id,
        "status": "completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_root": str(final_root),
        "inputs": {
            "selected_rocksteady_csv_root": str(selected_input),
            "extra_rocksteady_csv_root": str(extra_input),
            "whisper_json_root": str(whisper_root),
            "prepare_mapping_root": str(prepare_root),
        },
        "config": {
            "rocksteady_value_type": "total",
            "text_language": text_language,
            "segment_alignment": alignment_policy,
            "write_graphs": write_graphs,
            "segment_sample_counts": list(sample_counts),
            "mean_permutation_test": {
                "permutations": DEFAULT_PERMUTATIONS,
                "random_seed": DEFAULT_RANDOM_SEED,
                "multiple_comparison_adjustment": "Holm",
            },
        },
        "publication": {
            "previous_target_state": previous_ownership_state,
            "atomic_pair_replacement": True,
        },
        "identity_inventory": {
            "count": len(identity_contract),
            "sha256": hashlib.sha256(identity_json).hexdigest(),
            "identities": list(identity_contract),
        },
        "lineage": dict(lineage_contract),
        "multimodal": {
            "path": "multimodal",
            "contract": "multimodal/alignment_contract.json",
            "summary": dict(multimodal_contract.get("rows", {})),
            "graphs": multimodal_contract.get("graphs", 0),
        },
        "variants": {
            "selected": _variant_batch_record(
                selected_manifest_path,
                selected_manifest,
                "selected/output_manifest.json",
            ),
            "extra": _variant_batch_record(
                extra_manifest_path,
                extra_manifest,
                "extra/output_manifest.json",
            ),
        },
        "start_here": {
            "selected": "selected/video_level_summary.csv",
            "extra": "extra/video_level_summary.csv",
            "multimodal": "multimodal/video_level_summary.csv",
        },
    }


def _variant_batch_record(
    manifest_path: Path,
    manifest: Mapping[str, object],
    relative_path: str,
) -> dict[str, object]:
    categories = manifest.get("categories")
    if not isinstance(categories, list):
        raise ValueError(f"Variant manifest has no category contract: {manifest_path}")
    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        raise ValueError(f"Variant manifest has no summary contract: {manifest_path}")
    return {
        "path": manifest_path.parent.name,
        "output_manifest": relative_path,
        "output_manifest_sha256": sha256_file(manifest_path),
        "summary": dict(summary),
        "categories": categories,
    }


def _rebase_result(
    result: TextAnalysisResult,
    old_root: Path,
    new_root: Path,
) -> TextAnalysisResult:
    def rebase(path: Path) -> Path:
        return new_root / path.relative_to(old_root)

    return TextAnalysisResult(
        run_id=result.run_id,
        input_dir=result.input_dir,
        output_dir=new_root,
        csv_count=result.csv_count,
        segment_count=result.segment_count,
        video_summary_path=rebase(result.video_summary_path),
        speaker_summary_path=rebase(result.speaker_summary_path),
        descriptor_path=rebase(result.descriptor_path),
        alignment_audit_path=rebase(result.alignment_audit_path),
        output_manifest_path=rebase(result.output_manifest_path),
        graph_paths=[rebase(path) for path in result.graph_paths],
    )
