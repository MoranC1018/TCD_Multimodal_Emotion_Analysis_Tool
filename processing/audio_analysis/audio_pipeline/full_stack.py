from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from spreadsheet_safety import SpreadsheetSafeWriter, neutralize_spreadsheet_value
from procurement.input_limits import count_json_items
from .source_context import (
    MAX_SOURCE_CONTEXT_BYTES,
    MAX_SOURCE_CONTEXT_ITEMS,
    preflight_run_sidecars,
    publish_run_sidecars,
    snapshot_run_sidecars,
    validate_source_context,
)


AUDIO_ANALYSIS_FILENAME = "audio_analysis.csv"
MAX_AUDIO_MANIFEST_BYTES = 1024 * 1024
BATCH_MANIFEST_FILENAME = "audio_analysis_manifest.csv"
BATCH_STATE_FILENAME = ".audio_analysis_run.json"
MAX_BATCH_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_BATCH_MANIFEST_ROWS = 10_000


def current_batch_audio_inputs(root: Path) -> tuple[list[Path], list[Path]] | None:
    """Select a complete batch by its manifest; None means an unmanifested legacy tree.

    Absolute producer paths are checked for internal consistency, then remapped
    through video_folder. This lets an intact run be copied to another machine.
    No producer absolute path is opened and no invalid manifest falls back to glob.
    """

    manifest = root / BATCH_MANIFEST_FILENAME
    state_path = root / BATCH_STATE_FILENAME
    has_manifest = _lexically_exists(manifest)
    if not has_manifest and not _lexically_exists(state_path):
        return None
    try:
        state = None
        if _lexically_exists(state_path):
            state = json.loads(_control_snapshot(state_path, root, max_bytes=65536, label="batch state"))
            if (
                not isinstance(state, dict) or state.get("version") != 1
                or state.get("status") != "complete"
                or type(state.get("expected_count")) is not int
                or not 0 < state["expected_count"] <= MAX_BATCH_MANIFEST_ROWS
            ):
                raise ValueError("Incomplete or invalid audio batch state; rerun extraction to completion.")
        if not has_manifest:
            raise ValueError("Incomplete audio batch: its manifest is missing.")
        content = _control_snapshot(manifest, root, max_bytes=MAX_BATCH_MANIFEST_BYTES, label="batch manifest")
        if state is not None and state.get("manifest_sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError("Audio batch manifest does not match its completed run state.")
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        required = {
            "status", "video_folder", "output_folder", "audio_analysis_csv",
            "opensmile_features_csv", "per_video_manifest", "window_count",
        }
        if (
            not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames))
            or not required.issubset(reader.fieldnames)
        ):
            raise ValueError("Invalid audio batch manifest columns.")
        analysis_paths: list[Path] = []
        feature_paths: list[Path] = []
        seen: set[str] = set()
        producer_root = None
        for row in reader:
            if len(analysis_paths) >= MAX_BATCH_MANIFEST_ROWS:
                raise ValueError("Audio batch manifest exceeds the row limit.")
            if None in row or any(value is None for value in row.values()) or row["status"] != "ok":
                raise ValueError("Incomplete or malformed audio batch manifest row.")
            raw_folder = row["video_folder"]
            producer_folder = _manifest_path(row["output_folder"])
            # Spreadsheet escaping is reversible only when the declared output
            # path confirms the unescaped folder; preserve literal apostrophes.
            if raw_folder.startswith("'") and neutralize_spreadsheet_value(raw_folder[1:]) == raw_folder:
                candidate = _manifest_path(raw_folder[1:])
                if producer_folder.parts[-len(candidate.parts):] == candidate.parts:
                    raw_folder = raw_folder[1:]
            folder = _manifest_path(raw_folder)
            if folder.is_absolute() or PureWindowsPath(raw_folder).drive:
                raise ValueError("Audio batch manifest video_folder must be relative.")
            key = str(folder).casefold()
            if key in seen:
                raise ValueError("Duplicate video_folder in audio batch manifest.")
            seen.add(key)
            folder_parts = tuple(part.casefold() for part in folder.parts)
            producer_parts = tuple(part.casefold() for part in producer_folder.parts)
            if folder_parts and producer_parts[-len(folder_parts):] != folder_parts:
                raise ValueError("Audio batch manifest output_folder does not match video_folder.")
            base = producer_parts[:-len(folder_parts)] if folder_parts else producer_parts
            if producer_root is not None and base != producer_root:
                raise ValueError("Audio batch manifest contains inconsistent output roots.")
            producer_root = base
            count = row["window_count"]
            if not count.isdecimal() or not 0 < int(count) <= 10_000:
                raise ValueError("Invalid window_count in audio batch manifest.")
            selected = []
            for field, filename in (
                ("audio_analysis_csv", AUDIO_ANALYSIS_FILENAME),
                ("opensmile_features_csv", "opensmile_features.csv"),
                ("per_video_manifest", "audio_analysis_manifest.json"),
            ):
                declared = _manifest_path(row[field])
                expected = producer_folder / filename
                if str(declared).casefold() != str(expected).casefold():
                    raise ValueError(f"Audio batch manifest {field} disagrees with output_folder.")
                local_path = root.joinpath(*folder.parts, filename)
                _preflight_regular_source(local_path, root, "batch manifest output")
                selected.append(local_path)
            per_video = json.loads(_control_snapshot(
                selected[2], root, max_bytes=MAX_AUDIO_MANIFEST_BYTES, label="per-video manifest"
            ))
            if not isinstance(per_video, dict) or per_video.get("window_count", int(count)) != int(count):
                raise ValueError("Per-video manifest disagrees with audio batch window_count.")
            analysis_paths.append(selected[0])
            feature_paths.append(selected[1])
        if not analysis_paths or (state is not None and len(analysis_paths) != state["expected_count"]):
            raise ValueError("Incomplete audio batch manifest: unexpected result count.")
        return analysis_paths, feature_paths
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
        raise ValueError(f"Invalid or incomplete audio batch manifest: {exc}") from exc


def _manifest_path(value: str) -> PurePosixPath:
    if not value or "\x00" in value:
        raise ValueError("Audio batch manifest contains an empty or invalid path.")
    path = PurePosixPath(value.replace("\\", "/"))
    if ".." in path.parts:
        raise ValueError("Audio batch manifest paths must not contain parent traversal.")
    return path


def discover_audio_output_files(root: Path) -> tuple[list[Path], list[Path], set[Path]]:
    """Honor the nearest batch manifest, including runs below a legacy parent."""

    current = current_batch_audio_inputs(root)
    if current is not None:
        return current[0], current[1], {root}
    managed_roots: set[Path] = set()
    analysis_paths: list[Path] = []
    feature_paths: list[Path] = []
    candidates = {
        path.parent for name in (BATCH_MANIFEST_FILENAME, BATCH_STATE_FILENAME)
        for path in root.rglob(name)
    }
    for directory in sorted(candidates, key=lambda path: (len(path.parts), str(path).casefold())):
        if any(parent in managed_roots for parent in directory.parents):
            continue
        selected = current_batch_audio_inputs(directory)
        if selected is None:
            raise ValueError("Audio batch manifest disappeared during discovery.")
        analysis_paths.extend(selected[0])
        feature_paths.extend(selected[1])
        managed_roots.add(directory)
    for filename, paths in ((AUDIO_ANALYSIS_FILENAME, analysis_paths), ("opensmile_features.csv", feature_paths)):
        paths.extend(
            path for path in root.rglob(filename)
            if not any(parent in managed_roots for parent in path.parents)
        )
        paths.sort(key=lambda path: str(path).casefold())
    return analysis_paths, feature_paths, managed_roots


def export_batch_to_analysis_audio_outputs(
    audio_output_root: Path,
    *,
    repo_root: Path | None = None,
    run_name: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Copy per-video audio outputs into the analysis audio input area."""

    audio_output_root = audio_output_root.expanduser().resolve(strict=True)
    resolved_repo_root = (repo_root or find_project_root(audio_output_root)).expanduser().resolve()
    audio_outputs_root = resolved_repo_root / "analysis" / "audio_outputs"
    destination_root = (
        audio_outputs_root
        / safe_folder_name(run_name or audio_output_root.name)
    )
    _preflight_destination_path(resolved_repo_root, audio_outputs_root, destination_root)
    _preflight_destination_tree(destination_root)

    source_csvs, _feature_csvs, managed_roots = discover_audio_output_files(audio_output_root)
    expected_context_paths = {source_csv.parent / "source_context.json" for source_csv in source_csvs}
    context_paths = [
        path for path in audio_output_root.rglob("source_context.json")
        if path in expected_context_paths or not any(parent in managed_roots for parent in path.parents)
    ]
    orphan_contexts = [path for path in context_paths if path not in expected_context_paths]
    if orphan_contexts:
        raise ValueError(f"Orphan audio source context has no audio analysis CSV: {orphan_contexts[0]}")

    export_plan: list[dict[str, object]] = []
    source_bindings: list[tuple[Path, dict[str, object]]] = []
    missing_context_csvs: list[Path] = []
    for source_csv in source_csvs:
        _preflight_regular_source(source_csv, audio_output_root, "audio analysis CSV")
        relative_path = source_csv.relative_to(audio_output_root)
        destination_csv = destination_root / relative_path
        _preflight_destination_path(resolved_repo_root, audio_outputs_root, destination_csv)
        source_manifest = source_csv.parent / "audio_analysis_manifest.json"
        manifest_bytes: bytes | None = None
        if _lexically_exists(source_manifest):
            manifest_bytes = _control_snapshot(
                source_manifest,
                audio_output_root,
                max_bytes=MAX_AUDIO_MANIFEST_BYTES,
                label="audio analysis manifest",
            )
        source_context = source_csv.parent / "source_context.json"
        context_bytes: bytes | None = None
        context_payload: dict[str, object] = {}
        if _lexically_exists(source_context):
            context_bytes = _control_snapshot(
                source_context,
                audio_output_root,
                max_bytes=MAX_SOURCE_CONTEXT_BYTES,
                label="audio source context",
            )
            try:
                raw_context = json.loads(context_bytes.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid audio source context JSON: {source_context}") from exc
            if count_json_items(raw_context, stop_after=MAX_SOURCE_CONTEXT_ITEMS) > MAX_SOURCE_CONTEXT_ITEMS:
                raise ValueError(
                    f"Audio source context contains more than {MAX_SOURCE_CONTEXT_ITEMS} items: {source_context}"
                )
            context_payload = validate_source_context(raw_context, path=source_context)
            source_bindings.append((source_csv, context_payload))
        else:
            missing_context_csvs.append(source_csv)
        export_plan.append(
            {
                "source_csv": source_csv,
                "destination_csv": destination_csv,
                "relative_path": relative_path,
                "manifest_bytes": manifest_bytes,
                "context_bytes": context_bytes,
                "context_payload": context_payload,
            }
        )

    source_ids = {str(context.get("source_id") or "") for _path, context in source_bindings}
    sidecar_pair = snapshot_run_sidecars(
        audio_output_root,
        expected_source_ids=source_ids,
        source_bindings=source_bindings,
        require_mapped_input_paths=False,
    )
    if sidecar_pair is not None and missing_context_csvs:
        raise ValueError(f"Catalog audio analysis CSV has no source context: {missing_context_csvs[0]}")
    if sidecar_pair is None and source_bindings:
        raise ValueError("Audio source contexts require an immutable top-level source sidecar pair.")
    if sidecar_pair is None and any(
        _lexically_exists(destination_root / name)
        for name in ("source_manifest.json", "source_metadata.csv")
    ):
        raise FileExistsError("Existing analysis audio output has source sidecars but the new input does not.")
    if sidecar_pair is not None:
        preflight_run_sidecars(destination_root, sidecar_pair)

    audio_outputs_root.mkdir(parents=True, exist_ok=True)
    if sidecar_pair is not None:
        publish_run_sidecars(destination_root, sidecar_pair)
    clear_destination_root(destination_root, audio_outputs_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    copied_rows: list[dict[str, str]] = []
    for item in export_plan:
        source_csv = item["source_csv"]
        destination_csv = item["destination_csv"]
        relative_path = item["relative_path"]
        assert isinstance(source_csv, Path)
        assert isinstance(destination_csv, Path)
        assert isinstance(relative_path, Path)
        destination_csv.parent.mkdir(parents=True, exist_ok=True)
        copy_regular_file_snapshot(source_csv, destination_csv)
        destination_manifest = destination_csv.parent / "audio_analysis_manifest.json"
        manifest_value = ""
        manifest_bytes = item["manifest_bytes"]
        if isinstance(manifest_bytes, bytes):
            publish_control_snapshot(destination_manifest, manifest_bytes)
            manifest_value = str(destination_manifest)
        destination_context = destination_csv.parent / "source_context.json"
        context_value = ""
        context_payload = item["context_payload"]
        assert isinstance(context_payload, dict)
        context_bytes = item["context_bytes"]
        if isinstance(context_bytes, bytes):
            publish_control_snapshot(destination_context, context_bytes)
            context_value = str(destination_context)
        metadata = context_payload.get("user_metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        copied_rows.append(
            {
                "source_audio_analysis_csv": str(source_csv),
                "analysis_audio_analysis_csv": str(destination_csv),
                "analysis_audio_manifest_json": manifest_value,
                "analysis_source_context_json": context_value,
                "source_id": str(context_payload.get("source_id") or ""),
                "source_speaker": str(context_payload.get("speaker") or ""),
                "source_metadata": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                "relative_path": str(relative_path),
            }
        )

    write_manifest(destination_root / "audio_outputs_manifest.csv", copied_rows)
    emit(progress, f"Copied {len(copied_rows)} audio analysis CSV(s) to {destination_root}.")
    return destination_root


def find_project_root(start: Path) -> Path:
    """Find the repo root that owns procurement, processing, and analysis."""

    start = start.expanduser().resolve()
    search_points = [start, *start.parents]
    for path in search_points:
        if (path / "procurement").is_dir() and (path / "processing").is_dir() and (path / "analysis").is_dir():
            return path
    raise FileNotFoundError(
        "Could not find the Multimodal Emotion Analysis Tool project root. Pass repo_root explicitly "
        "or run from inside the project checkout."
    )


def write_manifest(path: Path, rows: list[dict[str, str]]) -> Path:
    fields = [
        "relative_path",
        "source_audio_analysis_csv",
        "analysis_audio_analysis_csv",
        "analysis_audio_manifest_json",
        "analysis_source_context_json",
        "source_id",
        "source_speaker",
        "source_metadata",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = SpreadsheetSafeWriter(csv.DictWriter(handle, fieldnames=fields))
        writer.writeheader()
        writer.writerows(rows)
    return path


def copy_bounded_control_file(
    source: Path,
    destination: Path,
    allowed_root: Path,
    *,
    max_bytes: int,
) -> None:
    if source.is_symlink():
        raise ValueError(f"Audio control file must not be a symlink: {source}")
    resolved = source.resolve(strict=True)
    root = allowed_root.resolve(strict=True)
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Audio control file escapes the output root: {source}")
    content = read_bounded_control_snapshot(resolved, max_bytes=max_bytes)
    publish_control_snapshot(destination, content)


def _control_snapshot(source: Path, allowed_root: Path, *, max_bytes: int, label: str) -> bytes:
    _preflight_regular_source(source, allowed_root, label)
    return read_bounded_control_snapshot(source, max_bytes=max_bytes)


def _preflight_regular_source(source: Path, allowed_root: Path, label: str) -> None:
    lexical_root = Path(os.path.abspath(allowed_root))
    lexical_source = Path(os.path.abspath(source))
    try:
        relative = lexical_source.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError(f"{label.capitalize()} escapes the audio output root: {source}") from exc
    current = lexical_root
    for part in relative.parts:
        current = current / part
        if _is_reparse_path(current):
            raise ValueError(f"{label.capitalize()} must not contain a symlink or reparse point: {current}")
    details = lexical_source.lstat()
    if not stat.S_ISREG(details.st_mode):
        raise ValueError(f"{label.capitalize()} must be a regular file: {source}")


def copy_regular_file_snapshot(source: Path, destination: Path) -> None:
    before = source.lstat()
    try:
        with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
            opened = os.fstat(source_handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or _file_identity(before) != _file_identity(opened):
                raise ValueError(f"Audio analysis CSV changed while it was opened: {source}")
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            after = os.fstat(source_handle.fileno())
            if not _same_open_snapshot(opened, after):
                raise ValueError(f"Audio analysis CSV changed while it was copied: {source}")
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def read_bounded_control_snapshot(source: Path, *, max_bytes: int) -> bytes:
    before = source.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Audio control file must be a regular non-symlink: {source}")
    if before.st_size > max_bytes:
        raise ValueError(f"Audio control file exceeds {max_bytes} bytes: {source}")
    with source.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError(f"Audio control file changed while it was opened: {source}")
        content = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    if len(content) > max_bytes:
        raise ValueError(f"Audio control file exceeds {max_bytes} bytes: {source}")
    try:
        current = source.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"Audio control file changed while it was read: {source}") from exc
    if not _same_open_snapshot(opened, after) or _file_identity(opened) != _file_identity(current):
        raise ValueError(f"Audio control file changed while it was read: {source}")
    return content


def publish_control_snapshot(destination: Path, content: bytes) -> None:
    if destination.is_symlink() or destination.exists():
        raise FileExistsError(f"Audio control destination already exists: {destination}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def clear_destination_root(destination_root: Path, audio_outputs_root: Path) -> None:
    destination = Path(os.path.abspath(destination_root))
    allowed_root = Path(os.path.abspath(audio_outputs_root))
    if not destination.exists():
        return
    try:
        destination.relative_to(allowed_root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to clean path outside analysis/audio_outputs: {destination}") from exc
    if destination == allowed_root:
        raise RuntimeError(f"Refusing to clean audio_outputs root itself: {destination}")
    _preflight_destination_tree(destination)
    for child in destination.iterdir():
        if child.name in {"source_manifest.json", "source_metadata.csv"}:
            continue
        if child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)


def safe_folder_name(value: str) -> str:
    cleaned = re.sub(r"\s+", "_", value.strip())
    cleaned = re.sub(r"[^\w.\-]+", "_", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    cleaned = cleaned or "audio_output"
    if cleaned.split(".", 1)[0].casefold() in {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }:
        cleaned = f"_{cleaned}"
    return cleaned


def _preflight_destination_path(repo_root: Path, allowed_root: Path, destination: Path) -> None:
    lexical_repo = Path(os.path.abspath(repo_root))
    lexical_allowed = Path(os.path.abspath(allowed_root))
    lexical_destination = Path(os.path.abspath(destination))
    try:
        lexical_allowed.relative_to(lexical_repo)
        lexical_destination.relative_to(lexical_allowed)
    except ValueError as exc:
        raise ValueError("Analysis audio destination escapes the project analysis/audio_outputs root.") from exc
    current = lexical_repo
    for part in lexical_destination.relative_to(lexical_repo).parts:
        current = current / part
        if _is_reparse_path(current):
            raise ValueError(f"Analysis audio destination must not contain a symlink or reparse point: {current}")
        if _lexically_exists(current) and current != lexical_destination and not current.is_dir():
            raise ValueError(f"Analysis audio destination parent is not a directory: {current}")


def _preflight_destination_tree(root: Path) -> None:
    if not _lexically_exists(root):
        return
    if _is_reparse_path(root):
        raise ValueError(f"Analysis audio destination must not be a symlink or reparse point: {root}")
    details = root.lstat()
    if not stat.S_ISDIR(details.st_mode):
        raise ValueError(f"Analysis audio destination must be a directory: {root}")
    for child in root.iterdir():
        if _is_reparse_path(child):
            raise ValueError(f"Analysis audio destination must not contain a symlink or reparse point: {child}")
        child_details = child.lstat()
        if stat.S_ISDIR(child_details.st_mode):
            _preflight_destination_tree(child)


def _is_reparse_path(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    attributes = int(getattr(details, "st_file_attributes", 0) or 0)
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    return stat.S_ISLNK(details.st_mode) or bool(reparse_flag and attributes & reparse_flag)


def _lexically_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _file_identity(details: os.stat_result) -> tuple[int, int]:
    return int(details.st_dev), int(details.st_ino)


def _same_open_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _file_identity(left) == _file_identity(right)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def emit(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)
