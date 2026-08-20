"""Build the canonical mixed-language Whisper tree used by this project."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from processing.io_utils import atomic_write_json, exclusive_process_lock

from .contracts import (
    TEXT_SCHEMA_VERSION,
    canonical_video_relative,
    file_sha256,
    inventory_digest,
    text_identity_parts,
    validate_text_identity,
)
from .filesystem import (
    OWNER_FILE,
    assert_safe_output_target,
    create_stage_directory,
    replace_stage_directory,
)


DEFAULT_LANGUAGE_POLICY: dict[str, str] = {}
SELECTION_MANIFEST = "selection_manifest.json"
TEXT_METADATA_JSON_FILES = frozenset(
    {
        OWNER_FILE.casefold(),
        SELECTION_MANIFEST.casefold(),
        ".prepare_manifest.json",
    }
)
TEXT_METADATA_DIRECTORIES = frozenset({"_manifests"})


def is_text_metadata_json(path: Path, root: Path) -> bool:
    """Return whether ``path`` is a recognized pipeline metadata JSON.

    Discovery deliberately uses an explicit allow-list.  Unknown JSON files
    are left for the canonical transcript-path validators to reject instead
    of being hidden by a broad ``*manifest*.json`` rule.
    """

    relative = Path(path).relative_to(Path(root))
    directory_names = {part.casefold() for part in relative.parts[:-1]}
    return bool(
        directory_names.intersection(TEXT_METADATA_DIRECTORIES)
        or relative.name.casefold() in TEXT_METADATA_JSON_FILES
    )


def build_selected_whisper_tree(
    whisper_root: Path,
    selected_root: Path,
    *,
    language_policy: Mapping[str, str] = DEFAULT_LANGUAGE_POLICY,
    default_variant: str = "eng",
    identities: Sequence[str | Path] | None = None,
    input_path: str | None = None,
    upstream_inventory_sha256: str | None = None,
) -> int:
    """Build one selected-language snapshot under its standalone stage lock."""

    target = Path(selected_root).resolve()
    lock_path = target.parent / f".{target.name}.selection.lock"
    with exclusive_process_lock(
        lock_path, purpose=f"publishing selected Whisper tree {target}"
    ):
        pattern = f".{target.name}_staging_*"
        preexisting = {path.resolve() for path in target.parent.glob(pattern)}
        try:
            return _build_selected_whisper_tree_unlocked(
                whisper_root,
                target,
                language_policy=language_policy,
                default_variant=default_variant,
                identities=identities,
                input_path=input_path,
                upstream_inventory_sha256=upstream_inventory_sha256,
            )
        except BaseException:
            for candidate in target.parent.glob(pattern):
                if candidate.resolve() not in preexisting and candidate.is_dir():
                    shutil.rmtree(candidate, ignore_errors=True)
            raise


def _build_selected_whisper_tree_unlocked(
    whisper_root: Path,
    selected_root: Path,
    *,
    language_policy: Mapping[str, str] = DEFAULT_LANGUAGE_POLICY,
    default_variant: str = "eng",
    identities: Sequence[str | Path] | None = None,
    input_path: str | None = None,
    upstream_inventory_sha256: str | None = None,
) -> int:
    """Atomically create a selected-language transcript snapshot.

    When ``identities`` is provided it is authoritative: no historical JSON
    outside that set is copied.  Current procurement identities use
    ``Speaker/Video``; historical canonical identities retain
    ``Country/Speaker/Video``.
    """

    if default_variant not in {"original", "eng"}:
        raise ValueError("default_variant must be original or eng")
    if any(variant not in {"original", "eng"} for variant in language_policy.values()):
        raise ValueError("language_policy values must be original or eng")
    whisper_root = Path(whisper_root).resolve()
    source_roots = {variant: whisper_root / variant for variant in ("original", "eng")}
    selected_root = assert_safe_output_target(selected_root, *source_roots.values())
    if identities is None:
        available = _discover_variant_files(source_roots)
        selected_identities = sorted(set(available["original"]) | set(available["eng"]), key=str.casefold)
    else:
        selected_identities = sorted(
            {validate_text_identity(Path(identity)).as_posix() for identity in identities},
            key=str.casefold,
        )
        available = _resolve_authoritative_variant_files(source_roots, selected_identities)
    if not selected_identities:
        raise ValueError(f"No canonical Whisper JSON files found below {whisper_root}")

    staging = create_stage_directory(selected_root, "selection")
    items: list[dict[str, object]] = []
    try:
        for identity in selected_identities:
            relative = Path(identity)
            country, _speaker, _video = text_identity_parts(relative)
            variant = language_policy.get(country, default_variant) if country else default_variant
            source = available[variant].get(identity)
            if source is None:
                raise FileNotFoundError(
                    f"Missing Whisper {variant} JSON for {identity}; expected it below {source_roots[variant]}"
                )
            payload = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list) or not payload["segments"]:
                raise ValueError(f"Whisper JSON has no segments: {source}")
            target = staging / relative.with_suffix(".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            items.append(
                {
                    "identity": identity,
                    "source_id": str(payload.get("source_id") or ""),
                    "video_stem": relative.name,
                    "country": country,
                    "variant": variant,
                    "source": source.relative_to(whisper_root).as_posix(),
                    "output": relative.with_suffix(".json").as_posix(),
                    "source_sha256": file_sha256(source),
                    "status": "completed",
                }
            )

        manifest = {
            "schema_version": TEXT_SCHEMA_VERSION,
            "kind": "text-language-selection",
            "status": "completed",
            "input_path": input_path,
            "default_variant": default_variant,
            "language_policy": dict(language_policy),
            "upstream_inventory_sha256": upstream_inventory_sha256,
            "inventory_sha256": inventory_digest(items),
            "summary": {"total": len(items), "completed": len(items), "failed": 0},
            "files": items,
        }
        atomic_write_json(staging / SELECTION_MANIFEST, manifest)
        replace_stage_directory(staging, selected_root, "selection")
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return len(items)


def _discover_variant_files(source_roots: Mapping[str, Path]) -> dict[str, dict[str, Path]]:
    result: dict[str, dict[str, Path]] = {"original": {}, "eng": {}}
    for variant, source_root in source_roots.items():
        if not source_root.is_dir():
            continue
        for source in sorted(source_root.rglob("*.json")):
            relative = source.relative_to(source_root)
            if is_text_metadata_json(source, source_root):
                continue
            if len(relative.parts) == 1:
                canonical = canonical_video_relative(source.stem).with_suffix(".json")
            elif len(relative.parts) in {2, 3}:
                canonical = validate_text_identity(relative).with_suffix(".json")
            else:
                raise ValueError(
                    "Whisper JSON must be root-level legacy, Speaker/Video.json, "
                    f"or Country/Speaker/Video.json: {source}"
                )
            identity = canonical.with_suffix("").as_posix()
            previous = result[variant].get(identity)
            if previous is not None:
                raise ValueError(
                    f"Duplicate Whisper {variant} identity {identity}: {previous} and {source}"
                )
            result[variant][identity] = source
    return result


def _resolve_authoritative_variant_files(
    source_roots: Mapping[str, Path], identities: Sequence[str]
) -> dict[str, dict[str, Path]]:
    """Resolve only manifest-bound transcript paths.

    A resumed pipeline already has an authoritative identity inventory.  It
    must not recursively inspect unrelated JSON left in a shared Whisper root,
    because an old malformed file outside the current run is neither an input
    nor a reason to block the run.
    """

    result: dict[str, dict[str, Path]] = {"original": {}, "eng": {}}
    for variant, source_root in source_roots.items():
        for identity in identities:
            relative = validate_text_identity(Path(identity)).with_suffix(".json")
            canonical = (source_root / relative).resolve()
            legacy = (source_root / relative.name).resolve()
            candidates = [path for path in (canonical, legacy) if path.is_file()]
            if len(candidates) > 1:
                raise ValueError(
                    f"Duplicate Whisper {variant} identity {identity}: "
                    f"{candidates[0]} and {candidates[1]}"
                )
            if candidates:
                result[variant][identity] = candidates[0]
    return result
