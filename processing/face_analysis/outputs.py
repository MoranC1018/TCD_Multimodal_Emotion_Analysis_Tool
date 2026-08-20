"""Stable output contract for high-dimensional Py-Feat predictions."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import shutil
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence

from .media import VideoMetadata, file_sha256
from .ownership import write_face_video_owner_marker
from processing.io_utils import make_staging_directory, publish_directory
from spreadsheet_safety import neutralize_spreadsheet_value


AU_NAMES = tuple(f"AU{number:02d}" for number in (1, 2, 4, 5, 6, 7, 9, 10, 11, 12, 14, 15, 17, 20, 23, 24, 25, 26, 28, 43))
EMOTION_NAMES = ("Neutral", "Happy", "Sad", "Surprise", "Fear", "Disgust", "Anger")
DETECTION_REQUIRED_COLUMNS = (
    "frame",
    "FaceRectX",
    "FaceRectY",
    "FaceRectWidth",
    "FaceRectHeight",
    "FaceScore",
)
PYFEAT_2_1_1_CORE_COLUMNS = (
    *DETECTION_REQUIRED_COLUMNS,
    *AU_NAMES,
    *EMOTION_NAMES,
    "valence",
    "arousal",
)
CORE_CANDIDATES = (
    "FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight", "FaceScore",
    "valence", "arousal", "gaze_yaw", "gaze_pitch",
    "Yaw", "Pitch", "Roll", "pose_yaw", "pose_pitch", "pose_roll", "pose_tx", "pose_ty", "pose_tz",
    "Identity",
)

OUTPUT_CONTRACT_VERSION = "1.0"
ARTIFACT_FILENAMES = {
    "full": "face_features.parquet",
    "core": "face_core.csv",
}
FULL_REQUIRED_COLUMNS = (
    "media_id",
    "frame",
    "FaceScore",
    "timestamp_seconds",
    "face_index",
    "is_primary_face",
)
CORE_REQUIRED_COLUMNS = (
    "media_id",
    "frame_index",
    "timestamp_seconds",
    "face_detected",
    "face_count",
    "face_index",
    "is_primary_face",
    "FaceScore",
)


def build_output_tables(
    detections: pd.DataFrame,
    metadata: VideoMetadata,
    *,
    sample_fps: float,
    media_id: str,
    minimum_face_score: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    import pandas as pd

    raw = detections.copy()
    _require_pyfeat_2_1_1_core_schema(raw, "Face backend output", frame_column="frame")
    frame_column = require_column(raw, "frame")
    score_column = require_column(raw, "FaceScore")

    frames = pd.to_numeric(raw[frame_column], errors="coerce")
    if frames.isna().any() or not frames.eq(frames.round()).all() or frames.lt(0).any():
        raise RuntimeError("Face backend frame values must be non-negative integers")
    raw[frame_column] = frames.astype("int64")
    sampling = sampling_metadata(metadata, sample_fps)
    sampled_frames = expected_sampled_frames(metadata, sample_fps)
    unexpected_frames = sorted(set(raw[frame_column].astype(int)) - set(sampled_frames))
    if unexpected_frames:
        preview = ", ".join(str(frame) for frame in unexpected_frames[:10])
        raise RuntimeError(
            "Face backend returned frames outside the expected sampling grid: " + preview
        )

    scores = pd.to_numeric(raw[score_column], errors="coerce")
    invalid_scores = raw[score_column].notna() & scores.isna()
    if invalid_scores.any():
        raise RuntimeError("FaceScore values must be numeric or missing")
    raw[score_column] = scores
    finite_scores = scores.dropna()
    if finite_scores.lt(0).any() or finite_scores.gt(1).any():
        raise RuntimeError("FaceScore values must be between 0 and 1")
    accepted = scores.gt(0) if minimum_face_score is None else scores.ge(minimum_face_score)
    rejected_rows = int((~accepted).sum())
    # Detectorv2 emits zero-score placeholder rows for sampled frames where
    # no face was found. They are not detections and must become explicit
    # no-face rows in the stable core table instead.
    raw = raw.loc[accepted].copy()
    raw.insert(0, "media_id", media_id)
    score_column = find_column(raw, "FaceScore")
    raw["timestamp_seconds"] = raw[frame_column] / metadata.fps
    raw["face_index"] = raw.groupby(frame_column, sort=False).cumcount()
    if score_column:
        scores = pd.to_numeric(raw[score_column], errors="coerce")
        raw["is_primary_face"] = False
        valid_scores = scores.dropna()
        if not valid_scores.empty:
            primary_indices = valid_scores.groupby(raw.loc[valid_scores.index, frame_column]).idxmax()
            raw.loc[primary_indices, "is_primary_face"] = True
        frames_without_score = set(raw[frame_column]) - set(raw.loc[valid_scores.index, frame_column])
        if frames_without_score:
            fallback = raw[raw[frame_column].isin(frames_without_score)].groupby(frame_column).head(1).index
            raw.loc[fallback, "is_primary_face"] = True
    else:
        raw["is_primary_face"] = raw["face_index"].eq(0)

    core = _core_detection_rows(raw, frame_column)
    detected_frames = set(core["frame_index"].astype(int)) if not core.empty else set()
    missing = pd.DataFrame(
        {
            "media_id": media_id,
            "frame_index": [frame for frame in sampled_frames if frame not in detected_frames],
            "timestamp_seconds": [frame / metadata.fps for frame in sampled_frames if frame not in detected_frames],
            "face_detected": False,
            "face_count": 0,
            "face_index": pd.NA,
            "is_primary_face": False,
        }
    )
    core = pd.concat([core, missing], ignore_index=True, sort=False).sort_values(
        ["frame_index", "face_index"], na_position="last", kind="stable"
    )
    core["frame_index"] = pd.to_numeric(core["frame_index"], errors="raise").astype("int64")
    core["face_index"] = pd.to_numeric(core["face_index"], errors="coerce").astype("Int64")
    core["face_count"] = pd.to_numeric(core["face_count"], errors="raise").astype("int64")
    ordered = [
        "media_id", "frame_index", "timestamp_seconds", "face_detected", "face_count",
        "face_index", "is_primary_face",
    ]
    core = core[ordered + [column for column in core.columns if column not in ordered]]
    quality = {
        "sampled_frames": len(sampled_frames),
        "frames_with_face": len(detected_frames),
        "frames_without_face": len(sampled_frames) - len(detected_frames),
        "face_coverage": len(detected_frames) / len(sampled_frames) if sampled_frames else 0.0,
        "detected_face_rows": len(raw),
        "rejected_placeholder_or_low_score_rows": rejected_rows,
        "multiple_face_frames": int((raw.groupby(frame_column).size() > 1).sum()) if not raw.empty else 0,
        "frame_step": sampling["frame_step"],
        "effective_sample_fps": sampling["effective_sample_fps"],
    }
    return raw, core, quality


def expected_sampled_frames(metadata: VideoMetadata, sample_fps: float) -> list[int]:
    step = int(sampling_metadata(metadata, sample_fps)["frame_step"])
    total = metadata.frame_count or max(1, round(metadata.duration_seconds * metadata.fps))
    return list(range(0, total, step))


def sampling_metadata(metadata: VideoMetadata, sample_fps: float) -> dict[str, object]:
    """Describe the exact integer-frame sampling implemented by Py-Feat."""

    step = max(1, round(metadata.fps / sample_fps))
    total = metadata.frame_count or max(1, round(metadata.duration_seconds * metadata.fps))
    return {
        "requested_sample_fps": sample_fps,
        "frame_step": step,
        "effective_sample_fps": metadata.fps / step,
        "expected_sampled_frames": len(range(0, total, step)),
    }


def _core_detection_rows(raw: pd.DataFrame, frame_column: str) -> pd.DataFrame:
    import pandas as pd

    lookup = {str(column).casefold(): str(column) for column in raw.columns}
    selected: list[str] = []
    for candidate in (*CORE_CANDIDATES, *AU_NAMES, *EMOTION_NAMES):
        actual = lookup.get(candidate.casefold())
        if actual and actual not in selected:
            selected.append(actual)
    core = raw[["media_id", frame_column, "timestamp_seconds", "face_index", "is_primary_face", *selected]].copy()
    core = core.rename(columns={frame_column: "frame_index"})
    core["face_detected"] = True
    core["face_count"] = core.groupby("frame_index")["frame_index"].transform("size")
    return core


def find_column(frame: pd.DataFrame, wanted: str) -> str | None:
    return next((str(column) for column in frame.columns if str(column).casefold() == wanted.casefold()), None)


def require_column(frame: pd.DataFrame, wanted: str) -> str:
    actual = find_column(frame, wanted)
    if actual is None:
        raise RuntimeError(f"Face backend output does not contain the required {wanted} column")
    return actual


def artifact_metadata(path: Path, artifact: str) -> dict[str, object]:
    """Read and fingerprint one completed artifact; raise if it is unusable."""

    if artifact not in ARTIFACT_FILENAMES:
        raise ValueError(f"Unknown face artifact: {artifact}")
    if path.name != ARTIFACT_FILENAMES[artifact]:
        raise ValueError(f"Unexpected {artifact} artifact filename: {path.name}")
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Face artifact is missing or empty: {path}")
    try:
        if artifact == "full":
            columns, rows = _inspect_parquet(path)
            sha256 = file_sha256(path)
        else:
            columns, rows, sha256 = _inspect_csv(path)
    except Exception as exc:
        raise RuntimeError(f"Could not read {artifact} face artifact {path}: {exc}") from exc

    required = FULL_REQUIRED_COLUMNS if artifact == "full" else CORE_REQUIRED_COLUMNS
    _require_artifact_columns(columns, required, artifact)
    _require_pyfeat_2_1_1_core_schema(
        columns,
        f"{artifact.capitalize()} face artifact",
        frame_column="frame" if artifact == "full" else "frame_index",
    )
    if artifact == "core" and rows == 0:
        raise RuntimeError("Core face artifact must contain at least one sampled frame")
    return {
        "path": path.name,
        "format": "parquet" if artifact == "full" else "csv",
        "size_bytes": path.stat().st_size,
        "sha256": sha256,
        "rows": rows,
        "columns": len(columns),
        "schema_fingerprint": _schema_fingerprint(columns),
    }


def verify_artifacts(output_dir: Path, outputs: object) -> bool:
    """Verify stored metadata against readable files in one video directory."""

    if not isinstance(outputs, dict) or set(outputs) != set(ARTIFACT_FILENAMES):
        return False
    try:
        for artifact, filename in ARTIFACT_FILENAMES.items():
            stored = outputs.get(artifact)
            if not isinstance(stored, dict) or stored.get("path") != filename:
                return False
            actual = artifact_metadata(output_dir / filename, artifact)
            if stored != actual:
                return False
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _require_artifact_columns(
    columns: Sequence[str],
    required: tuple[str, ...],
    artifact: str,
) -> None:
    lookup = {str(column).casefold() for column in columns}
    missing = [column for column in required if column.casefold() not in lookup]
    if missing:
        raise RuntimeError(
            f"{artifact.capitalize()} face artifact is missing required columns: "
            + ", ".join(missing)
        )


def _require_pyfeat_2_1_1_core_schema(
    table_or_columns: pd.DataFrame | Sequence[str],
    label: str,
    *,
    frame_column: str,
) -> None:
    """Require the complete research-facing schema shipped by Py-Feat 2.1.1."""

    import pandas as pd

    columns = table_or_columns.columns if isinstance(table_or_columns, pd.DataFrame) else table_or_columns
    normalized = [str(column).casefold() for column in columns]
    duplicates = sorted({column for column in normalized if normalized.count(column) > 1})
    if duplicates:
        raise RuntimeError(
            f"{label} contains ambiguous duplicate columns: " + ", ".join(duplicates)
        )
    lookup = set(normalized)
    required = (
        frame_column,
        *DETECTION_REQUIRED_COLUMNS[1:],
        *AU_NAMES,
        *EMOTION_NAMES,
        "valence",
        "arousal",
    )
    missing = [column for column in required if column.casefold() not in lookup]
    if missing:
        raise RuntimeError(
            f"{label} is missing required Py-Feat 2.1.1 core columns: "
            + ", ".join(missing)
        )


def _inspect_parquet(path: Path) -> tuple[list[str], int]:
    import pyarrow.parquet as parquet

    parquet_file = parquet.ParquetFile(path)
    columns = [str(name) for name in parquet_file.schema_arrow.names]
    frame_column = _find_name(columns, "frame")
    if frame_column is None:
        raise RuntimeError("Full face artifact is missing required frame column")
    frame_values = parquet_file.read(columns=[frame_column]).column(0).to_pylist()
    _validate_frame_values(frame_values, "Full face artifact", "frame")
    return columns, parquet_file.metadata.num_rows


def _inspect_csv(path: Path) -> tuple[list[str], int, str]:
    with path.open("rb") as source:
        hashing_source = _HashingRawReader(source)
        with io.TextIOWrapper(
            io.BufferedReader(hashing_source), encoding="utf-8", newline=""
        ) as text:
            reader = csv.reader(text)
            header = next(reader, None)
            if not header:
                raise RuntimeError("Core face artifact has no CSV header")
            frame_index = _find_name(header, "frame_index")
            if frame_index is None:
                raise RuntimeError("Core face artifact is missing required frame_index column")
            frame_position = header.index(frame_index)
            rows = 0
            for row in reader:
                if len(row) != len(header):
                    raise RuntimeError(
                        f"Core face artifact row {rows + 2} has {len(row)} fields; "
                        f"expected {len(header)}"
                    )
                _validate_frame_values(
                    [row[frame_position]], "Core face artifact", "frame_index"
                )
                rows += 1
        return [str(column) for column in header], rows, hashing_source.hexdigest()


class _HashingRawReader(io.RawIOBase):
    """Update a SHA-256 digest while the CSV parser consumes one byte stream."""

    def __init__(self, source: BinaryIO) -> None:
        super().__init__()
        self._source = source
        self._digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        chunk = self._source.read(len(buffer))
        if not chunk:
            return 0
        buffer[: len(chunk)] = chunk
        self._digest.update(chunk)
        return len(chunk)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _find_name(columns: Sequence[str], wanted: str) -> str | None:
    return next((str(column) for column in columns if str(column).casefold() == wanted.casefold()), None)


def _validate_frame_values(values: Sequence[object], label: str, column: str) -> None:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{label} has invalid {column} value: {value!r}") from exc
        if not math.isfinite(number) or number < 0 or not number.is_integer():
            raise RuntimeError(f"{label} has invalid {column} value: {value!r}")


def _schema_fingerprint(columns: Sequence[str]) -> str:
    # Artifact hashes prove byte integrity. This separate fingerprint names the
    # ordered column contract and remains stable across platform dtype inference.
    encoded = json.dumps([str(column) for column in columns], ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_video_outputs(
    output_dir: Path,
    raw: pd.DataFrame,
    core: pd.DataFrame,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = make_staging_directory(output_dir.parent, f".{output_dir.name}_")
    try:
        raw.to_parquet(staging / ARTIFACT_FILENAMES["full"], index=False)
        safe_core = core.rename(columns=neutralize_spreadsheet_value)
        if hasattr(safe_core, "map"):
            safe_core = safe_core.map(neutralize_spreadsheet_value)
        else:  # pandas < 2.1 compatibility for lightweight test environments
            safe_core = safe_core.applymap(neutralize_spreadsheet_value)
        safe_core.to_csv(staging / ARTIFACT_FILENAMES["core"], index=False, encoding="utf-8")
        completed_manifest = dict(manifest)
        completed_manifest["output_contract_version"] = OUTPUT_CONTRACT_VERSION
        completed_manifest["outputs"] = {
            artifact: artifact_metadata(staging / filename, artifact)
            for artifact, filename in ARTIFACT_FILENAMES.items()
        }
        (staging / "video_manifest.json").write_text(
            json.dumps(completed_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_face_video_owner_marker(staging)
        publish_directory(staging, output_dir)
        return completed_manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
