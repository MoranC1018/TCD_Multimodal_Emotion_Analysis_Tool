"""Application service for batch facial processing."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from .backend import FaceBackend, PyFeatBackend
from .config import FaceProcessingConfig
from .media import VideoMetadata, discover_videos, probe_video, stable_media_id
from .model_provenance import model_weight_set_signature
from .outputs import (
    OUTPUT_CONTRACT_VERSION,
    build_output_tables,
    sampling_metadata,
    verify_artifacts,
    write_video_outputs,
)
from .ownership import prepare_face_output_root
from processing.ffmpeg_runtime import configure_ffmpeg_shared_libraries
from processing.io_utils import atomic_write_csv, atomic_write_json, exclusive_process_lock


VIDEO_MANIFEST_SCHEMA_VERSION = "2.0"
RUN_MANIFEST_SCHEMA_VERSION = "1.1"
_RUN_POLICY_CONFIG_KEYS = {"recursive", "overwrite"}
FaceProgressCallback = Callable[[int, int, str, str], None]


@dataclass(frozen=True)
class FaceProcessingResult:
    input_path: Path
    output_root: Path
    processed: int
    skipped: int
    failed: int
    run_manifest: Path
    run_index: Path
    run_id: str


def process_face_input(
    source: str | Path,
    output_root: str | Path,
    *,
    config: FaceProcessingConfig | None = None,
    backend: FaceBackend | None = None,
    run_id: str | None = None,
    progress_callback: FaceProgressCallback | None = None,
) -> FaceProcessingResult:
    settings = (config or FaceProcessingConfig()).validate()
    # A newly installed WinGet package is not guaranteed to be present in the
    # caller's inherited PATH. Discover it before ffprobe or TorchCodec is used.
    configure_ffmpeg_shared_libraries()
    input_path = Path(source).expanduser().resolve()
    # Ownership validation must see the caller's lexical path before
    # ``resolve()`` can hide a symlink or Windows junction/reparse component.
    destination = Path(output_root).expanduser()
    videos = discover_videos(input_path, recursive=settings.recursive)
    destination = prepare_face_output_root(input_path, destination)
    with exclusive_process_lock(
        destination / ".face.run.lock",
        purpose=f"running Face processing in {destination}",
    ):
        return _process_face_input_locked(
            input_path,
            destination,
            videos,
            settings,
            backend,
            run_id,
            progress_callback,
        )


def _process_face_input_locked(
    input_path: Path,
    destination: Path,
    videos: list[Path],
    settings: FaceProcessingConfig,
    backend: FaceBackend | None,
    run_id: str | None,
    progress_callback: FaceProgressCallback | None,
) -> FaceProcessingResult:
    """Execute one Face run while its output-root lock is held."""

    engine = backend or PyFeatBackend()
    current_run_id = run_id or uuid.uuid4().hex
    started = datetime.now(timezone.utc)
    records: list[dict[str, object]] = []
    interrupted_error: KeyboardInterrupt | None = None

    video_total = len(videos)
    for video_index, video in enumerate(videos, start=1):
        relative_input = _relative_input(input_path, video)
        if progress_callback is not None:
            progress_callback(video_index, video_total, "analysing", relative_input)
        record: dict[str, object] = {
            "input_video": str(video),
            "input_relative": relative_input,
            "input_sha256": "",
            "status": "failed",
            "media_id": "",
            "output_relative": "",
            "quality": {},
        }
        stage = "probe"
        try:
            metadata = probe_video(video)
            record["input_sha256"] = metadata.sha256
            media_id = stable_media_id(video, metadata.sha256)
            video_dir = _video_output_dir(destination, input_path, video, media_id)
            record["media_id"] = media_id
            record["output_relative"] = str(video_dir.relative_to(destination))
            manifest_path = video_dir / "video_manifest.json"
            stage = "provenance"
            backend_provenance = _backend_provenance(engine, settings)
            analysis_fingerprint = _analysis_fingerprint(settings, backend_provenance)
            stage = "resume"
            if manifest_path.exists() and not settings.overwrite:
                existing = _load_manifest(manifest_path)
                if existing is not None and _is_reusable_output(
                    existing, video_dir, metadata, settings, engine
                ):
                    record.update(
                        _record_outputs(
                            input_path, destination, video, video_dir, media_id,
                            existing.get("quality"),
                        )
                    )
                    record["status"] = "skipped"
                    records.append(record)
                    if progress_callback is not None:
                        progress_callback(video_index, video_total, "skipped", relative_input)
                    continue
            stage = "analyse"
            detections = engine.analyse(video, metadata, settings)
            stage = "provenance"
            backend_provenance = _backend_provenance(engine, settings)
            analysis_fingerprint = _analysis_fingerprint(settings, backend_provenance)
            stage = "transform"
            raw, core, quality = build_output_tables(
                detections,
                metadata,
                sample_fps=settings.sample_fps,
                media_id=media_id,
                minimum_face_score=settings.face_detection_threshold,
            )
            video_manifest = {
                "schema_version": VIDEO_MANIFEST_SCHEMA_VERSION,
                "status": "completed",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "run_id": current_run_id,
                "media_id": media_id,
                "input": metadata.to_dict(),
                "backend": backend_provenance,
                "config": settings.to_dict(),
                "analysis_fingerprint": analysis_fingerprint,
                "sampling": sampling_metadata(metadata, settings.sample_fps),
                "quality": quality,
            }
            stage = "write"
            write_video_outputs(video_dir, raw, core, video_manifest)
            record.update(
                _record_outputs(
                    input_path, destination, video, video_dir, media_id, quality
                )
            )
            record["status"] = "completed"
        except KeyboardInterrupt as exc:
            record.update(
                {
                    "status": "interrupted",
                    "error_stage": stage,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc) or "Interrupted by user",
                    "error": "KeyboardInterrupt: Interrupted by user",
                }
            )
            records.append(record)
            if progress_callback is not None:
                progress_callback(video_index, video_total, "interrupted", relative_input)
            interrupted_error = exc
            break
        except Exception as exc:
            record.update(
                {
                    "error_stage": stage,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        records.append(record)
        if progress_callback is not None:
            progress_callback(
                video_index,
                video_total,
                str(record["status"]),
                relative_input,
            )

    finished = datetime.now(timezone.utc)
    completed = sum(record["status"] == "completed" for record in records)
    skipped = sum(record["status"] == "skipped" for record in records)
    failed = sum(record["status"] == "failed" for record in records)
    interrupted = sum(record["status"] == "interrupted" for record in records)
    run_payload = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": current_run_id,
        "status": (
            "cancelled"
            if interrupted
            else ("completed" if failed == 0 else "completed_with_errors")
        ),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "input": str(input_path),
        "output_root": str(destination),
        "config": settings.to_dict(),
        "runtime": {"python": sys.version, "platform": platform.platform()},
        "summary": {
            "discovered_videos": len(videos),
            "processed": completed,
            "skipped": skipped,
            "failed": failed,
            **({"interrupted": interrupted} if interrupted else {}),
        },
        "outputs": {
            "run_index": "run_index.csv",
            "per_video": {
                "core": "face_core.csv",
                "full": "face_features.parquet",
                "manifest": "video_manifest.json",
            },
        },
        "videos": records,
    }
    run_manifest = destination / "run_manifest.json"
    run_index = destination / "run_index.csv"
    _write_run_index(run_index, records)
    # Publish the manifest last: it is the completion marker for all run-level
    # artifacts and must never claim an index exists before that index is safe.
    atomic_write_json(run_manifest, run_payload)
    if interrupted_error is not None:
        raise interrupted_error
    return FaceProcessingResult(
        input_path,
        destination,
        completed,
        skipped,
        failed,
        run_manifest,
        run_index,
        current_run_id,
    )


def _video_output_dir(
    destination: Path,
    input_path: Path,
    video: Path,
    media_id: str,
) -> Path:
    """Keep single-file compatibility and mirror directory inputs for navigation."""

    if input_path.is_dir():
        return destination / video.parent.relative_to(input_path) / media_id
    return destination / media_id


def _relative_input(input_path: Path, video: Path) -> str:
    if not input_path.is_dir():
        return video.name
    try:
        return str(video.relative_to(input_path))
    except ValueError:
        # Resolved symlink targets may sit outside the selected directory. Keep
        # the source auditable rather than aborting before a failure record.
        return video.name


def _record_outputs(
    input_path: Path,
    destination: Path,
    video: Path,
    video_dir: Path,
    media_id: str,
    quality: object,
) -> dict[str, object]:
    relative_input = _relative_input(input_path, video)
    return {
        "input_relative": relative_input,
        "media_id": media_id,
        "output_dir": str(video_dir),
        "output_relative": str(video_dir.relative_to(destination)),
        "quality": quality if isinstance(quality, dict) else {},
    }


def _write_run_index(path: Path, records: list[dict[str, object]]) -> None:
    """Write one human-readable row per discovered video."""

    rows: list[dict[str, object]] = []
    for record in records:
        quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
        output_dir = Path(str(record["output_dir"])) if record.get("output_dir") else None
        rows.append(
            {
                "status": record.get("status", ""),
                "input_relative": record.get("input_relative", ""),
                "input_video": record.get("input_video", ""),
                "input_sha256": record.get("input_sha256", ""),
                "media_id": record.get("media_id", ""),
                "output_relative": record.get("output_relative", ""),
                "face_core_csv": str(output_dir / "face_core.csv") if output_dir else "",
                "face_features_parquet": str(output_dir / "face_features.parquet") if output_dir else "",
                "video_manifest": str(output_dir / "video_manifest.json") if output_dir else "",
                "sampled_frames": quality.get("sampled_frames", ""),
                "frames_with_face": quality.get("frames_with_face", ""),
                "face_coverage": quality.get("face_coverage", ""),
                "detected_face_rows": quality.get("detected_face_rows", ""),
                "error_stage": record.get("error_stage", ""),
                "error_type": record.get("error_type", ""),
                "error_message": record.get("error_message", ""),
                "error": record.get("error", ""),
            }
        )
    atomic_write_csv(
        path,
        rows,
        (
            "status", "input_relative", "input_video", "input_sha256",
            "media_id", "output_relative",
            "face_core_csv", "face_features_parquet", "video_manifest",
            "sampled_frames", "frames_with_face", "face_coverage",
            "detected_face_rows", "error_stage", "error_type", "error_message", "error",
        ),
    )


def _is_reusable_output(
    manifest: dict[str, object],
    video_dir: Path,
    metadata: VideoMetadata,
    settings: FaceProcessingConfig,
    engine: FaceBackend,
) -> bool:
    """Return true only when an existing result proves it is reusable."""

    if manifest.get("schema_version") != VIDEO_MANIFEST_SCHEMA_VERSION:
        return False
    if manifest.get("status") != "completed":
        return False
    input_record = manifest.get("input")
    backend_record = manifest.get("backend")
    config_record = manifest.get("config")
    if not isinstance(input_record, dict) or input_record != metadata.to_dict():
        return False
    if not isinstance(backend_record, dict):
        return False
    if not isinstance(config_record, dict):
        return False
    if manifest.get("output_contract_version") != OUTPUT_CONTRACT_VERSION:
        return False
    expected_backend = _backend_provenance(engine, settings)
    if _backend_signature(backend_record) != _backend_signature(expected_backend):
        return False
    if _analysis_config_from_mapping(config_record) != _analysis_config(settings):
        return False
    expected_fingerprint = _analysis_fingerprint(settings, expected_backend)
    if manifest.get("analysis_fingerprint") != expected_fingerprint:
        return False
    if manifest.get("sampling") != sampling_metadata(metadata, settings.sample_fps):
        return False
    outputs = manifest.get("outputs")
    if not verify_artifacts(video_dir, outputs):
        return False
    return _quality_matches_outputs(manifest.get("quality"), outputs, manifest["sampling"])


def _load_manifest(path: Path) -> dict[str, object] | None:
    """Treat unreadable state as a cache miss rather than a fatal video error."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _backend_provenance(
    engine: FaceBackend,
    settings: FaceProcessingConfig,
) -> dict[str, object]:
    provider = getattr(engine, "provenance", None)
    if callable(provider):
        supplied = provider(settings)
        if not isinstance(supplied, Mapping):
            raise RuntimeError("Face backend provenance() must return a mapping")
        record = {str(key): value for key, value in supplied.items()}
    else:
        record = {}
    record.setdefault("name", engine.name)
    record.setdefault("version", engine.version)
    record.setdefault("resolved_device", settings.device)
    return record


def _analysis_fingerprint(
    settings: FaceProcessingConfig,
    backend_provenance: Mapping[str, object],
) -> str:
    encoded = json.dumps(
        {
            "config": _analysis_config(settings),
            "backend": _backend_signature(backend_provenance),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _analysis_config(settings: FaceProcessingConfig) -> dict[str, object]:
    return _analysis_config_from_mapping(settings.to_dict())


def _analysis_config_from_mapping(config: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): value
        for key, value in config.items()
        if key not in _RUN_POLICY_CONFIG_KEYS
    }


def _backend_signature(provenance: Mapping[str, object]) -> dict[str, object]:
    signature = {
        key: provenance.get(key)
        for key in (
            "name",
            "version",
            "resolved_device",
            "models",
            "package_versions",
        )
    }
    # Local cache paths are useful audit facts, but they are not model
    # identity.  Resume depends on the three checkpoint repositories,
    # revisions, commits, sizes and content hashes instead.
    signature["weights"] = model_weight_set_signature(provenance.get("weights"))
    return signature


def _quality_matches_outputs(quality: object, outputs: object, sampling: object) -> bool:
    if not isinstance(quality, dict) or not isinstance(outputs, dict) or not isinstance(sampling, dict):
        return False
    full = outputs.get("full")
    core = outputs.get("core")
    if not isinstance(full, dict) or not isinstance(core, dict):
        return False
    try:
        sampled = int(quality["sampled_frames"])
        with_face = int(quality["frames_with_face"])
        without_face = int(quality["frames_without_face"])
        detected_rows = int(quality["detected_face_rows"])
        coverage = float(quality["face_coverage"])
        expected_frames = int(sampling["expected_sampled_frames"])
        full_rows = int(full["rows"])
        core_rows = int(core["rows"])
    except (KeyError, TypeError, ValueError):
        return False
    expected_core_rows = sampled + detected_rows - with_face
    return (
        sampled == expected_frames
        and with_face + without_face == sampled
        and 0 <= with_face <= sampled
        and detected_rows >= with_face
        and detected_rows == full_rows
        and expected_core_rows == core_rows
        and math.isclose(
            coverage,
            with_face / sampled if sampled else 0.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
