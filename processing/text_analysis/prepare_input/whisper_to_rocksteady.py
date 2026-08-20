"""Convert Whisper JSON into one canonical text file per analysis segment."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from processing.io_utils import (
    atomic_write_json,
    exclusive_process_lock,
    lexical_absolute_path,
)
from processing.text_analysis.contracts import (
    TEXT_SCHEMA_VERSION,
    canonical_video_relative,
    file_sha256,
    inventory_digest,
    validate_text_identity,
)
from processing.text_analysis.filesystem import (
    assert_safe_output_target,
    create_stage_directory,
    replace_stage_directory,
)
from processing.text_analysis.selection import is_text_metadata_json
from processing.text_analysis.prepare_input.integrity import (
    PREPARE_MANIFEST,
    prepared_content_sha256,
    validate_prepared_video_tree,
)


LANG_KEY = {
    "original": "text_original",
    "en": "text_en",
    "fr": "text_fr",
    "it": "text_it",
    "pl": "text_pl",
}
@dataclass(frozen=True)
class PreparedSegment:
    analysis_segment_id: int
    source_segment_index: int
    source_segment_id: str | int | float | bool | None
    text: str

    def mapping(self) -> dict[str, object]:
        return {
            "analysis_segment_id": self.analysis_segment_id,
            "source_segment_index": self.source_segment_index,
            "source_segment_id": self.source_segment_id,
        }


def bilingual_text_key(lang: str) -> str:
    """Return the preferred segment key for a bilingual Whisper JSON."""

    normalised = (lang or "original").strip().lower()
    return LANG_KEY.get(normalised, f"text_{normalised}")


def segment_text(seg: dict, task: str, lang: str = "original") -> str:
    """Return the selected text for one Whisper segment."""

    key = bilingual_text_key(lang) if task == "bilingual" else "text"
    fallback_key = "text_original" if task == "bilingual" and key != "text_en" else None
    value = seg.get(key, "") or (seg.get(fallback_key, "") if fallback_key else "")
    if not isinstance(value, str):
        raise ValueError(f"Whisper segment text must be a string, got {type(value).__name__}")
    return value.strip()


def extract_segments(data: dict, lang: str = "original") -> list[str]:
    return [segment.text for segment in extract_indexed_segments(data, lang=lang)]


def extract_indexed_segments(data: dict, lang: str = "original") -> list[PreparedSegment]:
    """Return non-empty text with contiguous IDs and an explicit source mapping."""

    if not isinstance(data, dict):
        raise ValueError("Whisper JSON root must be an object")
    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list):
        raise ValueError("Whisper JSON must contain a segments array")
    task = str(data.get("task", "transcribe"))
    prepared: list[PreparedSegment] = []
    for source_index, raw_segment in enumerate(raw_segments):
        if not isinstance(raw_segment, dict):
            raise ValueError(f"Whisper segment at index {source_index} must be an object")
        text = segment_text(raw_segment, task, lang=lang)
        if not text:
            continue
        source_id = raw_segment.get("id")
        if source_id is not None and not isinstance(source_id, (str, int, float, bool)):
            raise ValueError(f"Whisper segment id at index {source_index} must be scalar or null")
        prepared.append(
            PreparedSegment(
                analysis_segment_id=len(prepared) + 1,
                source_segment_index=source_index,
                source_segment_id=source_id,
                text=text,
            )
        )
    return prepared


def extract_text(data: dict, lang: str = "original") -> str:
    return " ".join(extract_segments(data, lang=lang))


def collect_json_files(input_path: str | Path) -> tuple[Path, list[Path]]:
    path = Path(input_path)
    if path.is_file():
        if path.suffix.lower() != ".json":
            raise ValueError(f"Input file is not a .json: {path}")
        return path.parent.resolve(), [path.resolve()]
    if path.is_dir():
        files = sorted(
            candidate.resolve()
            for candidate in path.rglob("*.json")
            if not is_text_metadata_json(candidate, path)
        )
        if not files:
            raise ValueError(f"No Whisper JSON files found under {path}")
        return path.resolve(), files
    raise FileNotFoundError(f"Input not found: {path}")


def collect_inventory_files(input_root: Path, inventory_path: Path) -> tuple[list[Path], dict[str, dict[str, object]]]:
    """Resolve the exact selected JSON set recorded by a selection manifest."""

    payload = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != TEXT_SCHEMA_VERSION
        or payload.get("kind") != "text-language-selection"
        or payload.get("status") != "completed"
        or not isinstance(payload.get("files"), list)
    ):
        raise ValueError(f"Selection inventory is not completed: {inventory_path}")
    if payload.get("inventory_sha256") != inventory_digest(payload["files"]):
        raise ValueError(f"Selection inventory digest mismatch: {inventory_path}")
    files: list[Path] = []
    items: dict[str, dict[str, object]] = {}
    for raw in payload["files"]:
        if (
            not isinstance(raw, dict)
            or raw.get("status") != "completed"
            or not isinstance(raw.get("identity"), str)
        ):
            raise ValueError(f"Malformed selection inventory item in {inventory_path}")
        identity = validate_text_identity(Path(raw["identity"])).as_posix()
        relative = Path(str(raw.get("output", f"{identity}.json")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe selection inventory path: {relative}")
        source = (input_root / relative).resolve()
        if not source.is_relative_to(input_root.resolve()) or not source.is_file():
            raise FileNotFoundError(f"Selected Whisper JSON is missing: {source}")
        expected_hash = raw.get("source_sha256")
        if not isinstance(expected_hash, str) or file_sha256(source) != expected_hash:
            raise ValueError(f"Selected Whisper JSON changed after selection: {source}")
        if identity in items:
            raise ValueError(f"Duplicate selection identity: {identity}")
        files.append(source)
        items[identity] = raw
    return files, items


def replace_segment_directory(
    video_dir: Path,
    video_stem: str,
    segments: Sequence[PreparedSegment | tuple[int, str]],
    *,
    video_identity: str | None = None,
    source_sha256_value: str | None = None,
    selection_source_sha256: str | None = None,
    source_id: str = "",
) -> None:
    """Write a complete, mapped segment set and atomically replace one video directory."""

    normalised = _normalise_segments(segments)
    identity = video_identity or video_stem
    desired = [
        (f"{video_stem}__segment_{segment.analysis_segment_id:06d}.txt", segment)
        for segment in normalised
    ]
    content_sha256 = prepared_content_sha256(
        [(name, segment.text, segment.mapping()) for name, segment in desired]
    )
    mapping = [segment.mapping() for segment in normalised]
    expected_manifest = {
        "schema_version": TEXT_SCHEMA_VERSION,
        "video_identity": identity,
        "source_id": source_id,
        "content_sha256": content_sha256,
        "segment_count": len(desired),
        "segments": mapping,
        "source_sha256": source_sha256_value,
        "selection_source_sha256": selection_source_sha256,
    }

    video_dir = Path(video_dir).resolve()
    video_dir.parent.mkdir(parents=True, exist_ok=True)
    if video_dir.exists():
        if not video_dir.is_dir():
            raise NotADirectoryError(f"Output path is not a directory: {video_dir}")
        existing_files = sorted(video_dir.glob("*.txt"))
        existing_names = [path.name for path in existing_files]
        desired_names = [name for name, _ in desired]
        try:
            existing_manifest = json.loads((video_dir / PREPARE_MANIFEST).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_manifest = None
        if existing_manifest == expected_manifest and existing_names == desired_names:
            try:
                validate_prepared_video_tree(
                    video_dir,
                    expected_identity=identity,
                    expected_source_sha256=source_sha256_value,
                    expected_selection_source_sha256=selection_source_sha256,
                )
            except ValueError:
                pass
            else:
                return
        if existing_names == desired_names and all(
            existing.read_text(encoding="utf-8") == segment.text
            for existing, (_, segment) in zip(existing_files, desired)
        ):
            atomic_write_json(video_dir / PREPARE_MANIFEST, expected_manifest)
            return

    staging = create_stage_directory(video_dir, "prepare-video")
    try:
        for output_name, segment in desired:
            (staging / output_name).write_text(segment.text, encoding="utf-8")
        atomic_write_json(staging / PREPARE_MANIFEST, expected_manifest)
        replace_stage_directory(staging, video_dir, "prepare-video")
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _normalise_segments(
    segments: Sequence[PreparedSegment | tuple[int, str]],
) -> list[PreparedSegment]:
    result: list[PreparedSegment] = []
    for position, value in enumerate(segments):
        if isinstance(value, PreparedSegment):
            segment = value
        else:
            source_number, text = value
            segment = PreparedSegment(position + 1, int(source_number) - 1, int(source_number) - 1, text)
        if segment.analysis_segment_id != position + 1:
            raise ValueError("analysis_segment_id values must be contiguous from 1")
        if not segment.text.strip():
            raise ValueError("Prepared segment text must not be empty")
        result.append(segment)
    return result


def _video_identity_for_json(json_file: Path, input_root: Path) -> str:
    relative = json_file.relative_to(input_root)
    if len(relative.parts) in {2, 3}:
        return validate_text_identity(relative).as_posix()
    if len(relative.parts) == 1:
        return canonical_video_relative(json_file.stem).as_posix()
    raise ValueError(
        "Whisper JSON must be root-level legacy, Speaker/Video.json, or "
        f"Country/Speaker/Video.json: {json_file}"
    )


def _write_batch_manifest(
    path: Path,
    *,
    status: str,
    input_root: Path,
    output_root: Path,
    language: str,
    started_at: str,
    records: list[dict[str, object]],
    upstream_inventory_sha256: str | None,
) -> None:
    completed = sum(record.get("status") == "completed" for record in records)
    failed = sum(record.get("status") == "failed" for record in records)
    interrupted = sum(record.get("status") == "interrupted" for record in records)
    payload = {
        "schema_version": TEXT_SCHEMA_VERSION,
        "kind": "whisper-to-rocksteady-prepare",
        "status": status,
        "started_at": started_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(input_root),
        "output_root": str(output_root),
        "language": language,
        "upstream_inventory_sha256": upstream_inventory_sha256,
        "inventory_sha256": inventory_digest(records),
        "summary": {
            "total": len(records),
            "completed": completed,
            "failed": failed,
            **({"interrupted": interrupted} if interrupted else {}),
        },
        "videos": records,
    }
    atomic_write_json(Path(path), payload)


def _main_unlocked(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract one mapped plain-text RockSteady input file per Whisper segment"
    )
    parser.add_argument("input", help="A Whisper JSON file or a folder of them")
    parser.add_argument("-o", "--output", default=None, help="Output root folder")
    parser.add_argument("--lang", default="original", help="Selected bilingual text language")
    parser.add_argument("--join-segments", action="store_true", help="Write one full-speech .txt per JSON")
    parser.add_argument("--inventory", type=Path, help="Authoritative selection_manifest.json")
    parser.add_argument("--batch-manifest", type=Path, help="External batch manifest path")
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        inventory_items: dict[str, dict[str, object]] = {}
        upstream_inventory_sha256: str | None = None
        if args.inventory is not None:
            input_root = Path(args.input).resolve()
            if not input_root.is_dir():
                raise ValueError("--inventory requires input to be the selected Whisper directory")
            inventory_payload = json.loads(args.inventory.read_text(encoding="utf-8"))
            upstream_inventory_sha256 = inventory_payload.get("inventory_sha256")
            discovered, inventory_items = collect_inventory_files(input_root, args.inventory)
        else:
            input_root, discovered = collect_json_files(args.input)
        default_output = "rocksteady_input" if args.join_segments else "rocksteady_input_segments"
        output_root = lexical_absolute_path(
            Path(args.output) if args.output else Path(__file__).parent / default_output
        )
        output_root = assert_safe_output_target(output_root, input_root)
        batch_manifest = (
            args.batch_manifest.resolve()
            if args.batch_manifest is not None
            else output_root.parent / "_manifests" / f"{output_root.name}_prepare_run_manifest.json"
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    staging_root = create_stage_directory(output_root, "prepare-batch")
    records: list[dict[str, object]] = []
    _write_batch_manifest(
        batch_manifest,
        status="running",
        input_root=input_root,
        output_root=output_root,
        language=args.lang,
        started_at=started_at,
        records=records,
        upstream_inventory_sha256=upstream_inventory_sha256,
    )
    try:
        for json_file in discovered:
            try:
                identity = _video_identity_for_json(json_file, input_root)
                relative_source = json_file.relative_to(input_root).as_posix()
                data = json.loads(json_file.read_text(encoding="utf-8"))
                segments = extract_indexed_segments(data, lang=args.lang)
                if not segments:
                    raise ValueError("no non-empty text segments")
                relative_identity = Path(identity)
                selected_item = inventory_items.get(identity, {})
                source_id = str(data.get("source_id") or selected_item.get("source_id") or "")
                source_hash = file_sha256(json_file)
                selected_source_hash = selected_item.get("source_sha256")
                if selected_source_hash is not None and not isinstance(selected_source_hash, str):
                    raise ValueError(f"Selection source hash is invalid for {identity}")
                if args.join_segments:
                    target = staging_root / relative_identity.with_suffix(".txt")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(" ".join(segment.text for segment in segments), encoding="utf-8")
                    artifact = target.relative_to(staging_root).as_posix()
                    prepared_manifest_hash = None
                else:
                    video_dir = staging_root / relative_identity
                    replace_segment_directory(
                        video_dir,
                        relative_identity.name,
                        segments,
                        video_identity=identity,
                        source_sha256_value=source_hash,
                        selection_source_sha256=selected_source_hash,
                        source_id=source_id,
                    )
                    prepared_manifest = validate_prepared_video_tree(
                        video_dir,
                        expected_identity=identity,
                        expected_source_sha256=source_hash,
                        expected_selection_source_sha256=selected_source_hash,
                    )
                    prepared_manifest_hash = file_sha256(video_dir / PREPARE_MANIFEST)
                    artifact = video_dir.relative_to(staging_root).as_posix()
                records.append(
                    {
                        "source_path": str(json_file),
                        "source_relative": relative_source,
                        "video_stem": relative_identity.name,
                        "identity": identity,
                        "source_id": source_id,
                        "status": "completed",
                        "artifact": artifact,
                        "segment_count": len(segments),
                        "source_sha256": source_hash,
                        "selection_source_sha256": selected_source_hash,
                        "selection_variant": selected_item.get("variant"),
                        "prepared_content_sha256": (
                            prepared_manifest.get("content_sha256")
                            if not args.join_segments
                            else None
                        ),
                        "prepare_manifest_sha256": prepared_manifest_hash,
                    }
                )
            except Exception as exc:  # report every bad video before failing the batch
                records.append(
                    {
                        "source_path": str(json_file),
                        "source_relative": json_file.relative_to(input_root).as_posix(),
                        "video_stem": json_file.stem,
                        "identity": None,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"ERROR: {json_file}: {exc}", file=sys.stderr)

        failures = sum(record["status"] == "failed" for record in records)
        if failures:
            _write_batch_manifest(
                batch_manifest,
                status="failed",
                input_root=input_root,
                output_root=output_root,
                language=args.lang,
                started_at=started_at,
                records=records,
                upstream_inventory_sha256=upstream_inventory_sha256,
            )
            shutil.rmtree(staging_root)
            print(f"Prepare failed for {failures}/{len(records)} video(s); previous output was preserved.", file=sys.stderr)
            return 1
        replace_stage_directory(staging_root, output_root, "prepare-batch")
        _write_batch_manifest(
            batch_manifest,
            status="completed",
            input_root=input_root,
            output_root=output_root,
            language=args.lang,
            started_at=started_at,
            records=records,
            upstream_inventory_sha256=upstream_inventory_sha256,
        )
        print(f"Done. {len(records)} video(s) prepared under {output_root}")
        return 0
    except BaseException as exc:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        _write_batch_manifest(
            batch_manifest,
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            input_root=input_root,
            output_root=output_root,
            language=args.lang,
            started_at=started_at,
            records=records + [
                {
                    "status": (
                        "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
                    ),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            ],
            upstream_inventory_sha256=upstream_inventory_sha256,
        )
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"ERROR: prepare batch could not be published: {exc}", file=sys.stderr)
        return 1


def _interrupt_manifest(path: Path) -> None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict) or payload.get("status") != "running":
        return
    payload["status"] = "interrupted"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["interruption"] = {
        "type": "KeyboardInterrupt",
        "message": "Preparation was interrupted; the previous visible output was preserved.",
    }
    atomic_write_json(Path(path), payload)


def main(argv: list[str] | None = None) -> int:
    """Run one standalone prepare snapshot under its output-set lock."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("input", nargs="?")
    pre_parser.add_argument("-o", "--output", default=None)
    pre_parser.add_argument("--join-segments", action="store_true")
    pre_parser.add_argument("--batch-manifest", type=Path)
    preliminary, _unknown = pre_parser.parse_known_args(arguments)
    default_output = (
        "rocksteady_input" if preliminary.join_segments else "rocksteady_input_segments"
    )
    output_root = assert_safe_output_target(
        lexical_absolute_path(
            Path(preliminary.output)
            if preliminary.output
            else Path(__file__).parent / default_output
        )
    )
    batch_manifest = (
        preliminary.batch_manifest.resolve()
        if preliminary.batch_manifest is not None
        else output_root.parent / "_manifests" / f"{output_root.name}_prepare_run_manifest.json"
    )
    lock_path = output_root.parent / f".{output_root.name}.prepare.lock"
    with exclusive_process_lock(
        lock_path, purpose=f"publishing prepared Text tree {output_root}"
    ):
        pattern = f".{output_root.name}_staging_*"
        preexisting = {path.resolve() for path in output_root.parent.glob(pattern)}
        manifest_temporary_pattern = f".{batch_manifest.name}.*.tmp"
        preexisting_manifest_temporaries = {
            path.resolve()
            for path in batch_manifest.parent.glob(manifest_temporary_pattern)
        }
        try:
            return _main_unlocked(arguments)
        except KeyboardInterrupt:
            _interrupt_manifest(batch_manifest)
            raise
        finally:
            for candidate in output_root.parent.glob(pattern):
                if candidate.resolve() not in preexisting and candidate.is_dir():
                    shutil.rmtree(candidate, ignore_errors=True)
            for temporary in batch_manifest.parent.glob(manifest_temporary_pattern):
                if (
                    temporary.resolve() not in preexisting_manifest_temporaries
                    and temporary.is_file()
                ):
                    temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
