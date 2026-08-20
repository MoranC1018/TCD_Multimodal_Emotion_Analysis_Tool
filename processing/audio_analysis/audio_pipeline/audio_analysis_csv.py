from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from spreadsheet_safety import SpreadsheetSafeWriter

from .emotion_models import EMOTION_COLUMNS, EmotionModelResult, EmotionModels
from .opensmile_runner import format_window_number
from .windows import AudioWindow


AUDIO_ANALYSIS_FIELDS = [
    "WindowIndex",
    "StartSeconds",
    "EndSeconds",
    "PredictedEmotion",
    "EmotionConfidence",
    *EMOTION_COLUMNS,
    "Arousal",
    "Dominance",
    "Valence",
]

AUDIO_ANALYSIS_METADATA_FIELDS = [
    "FormatVersion",
    "SourceFile",
    "SpeakerName",
    "VideoTitle",
    "YoutubeID",
    "SourceID",
    "SourceSpeaker",
    "SourceMetadata",
    "UserLanguage",
    "YouTubeLanguage",
    "ModelCategoricalName",
    "ModelCategoricalVersion",
    "ModelDimensionalName",
    "ModelDimensionalVersion",
    "CategoricalModelAvailable",
    "DimensionalModelAvailable",
    "EmotionModelsSkipped",
    "ModelDevice",
    "ModelErrors",
    "OpenSMILEFeatureSet",
    "WindowSeconds",
    "StrideSeconds",
    "Note",
]

YOUTUBE_ID_PATTERN = re.compile(r"^(?P<title>.*?)(?:_)?\[(?P<youtube_id>[^\[\]]+)\]$")


@dataclass(frozen=True)
class VideoContext:
    source_file: Path
    speaker_name: str
    video_title: str
    youtube_id: str


def build_audio_analysis_rows(
    *,
    input_video: Path,
    windows: Sequence[AudioWindow],
    emotion_results: Sequence[EmotionModelResult],
    emotion_models: EmotionModels,
    opensmile_feature_set: str,
    window_seconds: float,
    stride_seconds: float,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for window, model_result in zip(windows, emotion_results):
        predicted_emotion, confidence = predicted_emotion_from_probabilities(model_result.probabilities)
        row = {
            "WindowIndex": str(window.row),
            "StartSeconds": format_window_number(window.start),
            "EndSeconds": format_window_number(window.end),
            "PredictedEmotion": predicted_emotion,
            "EmotionConfidence": format_optional_number(confidence),
            "Arousal": format_optional_number(model_result.arousal),
            "Dominance": format_optional_number(model_result.dominance),
            "Valence": format_optional_number(model_result.valence),
        }
        for emotion in EMOTION_COLUMNS:
            row[emotion] = format_optional_number(model_result.probabilities.get(emotion, ""))
        rows.append(row)
    return rows


def build_audio_analysis_metadata(
    *,
    input_video: Path,
    emotion_models: EmotionModels,
    opensmile_feature_set: str,
    window_seconds: float,
    stride_seconds: float,
    source_context: dict[str, object] | None = None,
) -> dict[str, str]:
    context = parse_video_context(input_video)
    provenance = source_context or {}
    user_metadata = provenance.get("user_metadata")
    if not isinstance(user_metadata, dict):
        user_metadata = {}
    system_metadata = provenance.get("system_metadata")
    if not isinstance(system_metadata, dict):
        system_metadata = {}
    source_speaker = str(provenance.get("speaker") or "")
    source_speaker_display = str(provenance.get("speaker_display") or source_speaker)
    return {
        "FormatVersion": "2",
        "SourceFile": str(context.source_file),
        "SpeakerName": source_speaker_display if provenance else context.speaker_name,
        "VideoTitle": context.video_title,
        "YoutubeID": context.youtube_id,
        "SourceID": str(provenance.get("source_id") or ""),
        "SourceSpeaker": source_speaker,
        "SourceMetadata": json.dumps(user_metadata, ensure_ascii=False, sort_keys=True),
        "UserLanguage": str(user_metadata.get("Language") or ""),
        "YouTubeLanguage": str(system_metadata.get("youtube_language") or ""),
        "ModelCategoricalName": emotion_models.categorical_model_name,
        "ModelCategoricalVersion": emotion_models.categorical_model_version,
        "ModelDimensionalName": emotion_models.dimensional_model_name,
        "ModelDimensionalVersion": emotion_models.dimensional_model_version,
        "CategoricalModelAvailable": str(bool(emotion_models.categorical_available)).lower(),
        "DimensionalModelAvailable": str(bool(emotion_models.dimensional_available)).lower(),
        "EmotionModelsSkipped": str(bool(emotion_models.skipped)).lower(),
        "ModelDevice": emotion_models.device,
        "ModelErrors": " | ".join(emotion_models.errors or []),
        "OpenSMILEFeatureSet": opensmile_feature_set,
        "WindowSeconds": format_window_number(window_seconds),
        "StrideSeconds": format_window_number(stride_seconds),
        "Note": "Per-window audio waveform/acoustic model outputs only; no transcription, text sentiment, or final interpretation.",
    }


def write_audio_analysis_csv(
    path: Path,
    rows: Sequence[dict[str, str]],
    *,
    metadata: dict[str, str] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        metadata = metadata or {}
        metadata_writer = SpreadsheetSafeWriter(csv.writer(handle))
        metadata_writer.writerow(["#INFO"])
        for field in AUDIO_ANALYSIS_METADATA_FIELDS:
            metadata_writer.writerow([f"#{field}", metadata.get(field, "")])
        metadata_writer.writerow(["#DATA"])
        writer = SpreadsheetSafeWriter(csv.DictWriter(handle, fieldnames=AUDIO_ANALYSIS_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def parse_video_context(input_video: Path) -> VideoContext:
    input_video = input_video.expanduser().resolve()
    speaker_name = ""
    video_title, youtube_id = split_video_title_and_id(input_video.parent.name)
    downloads_relative_folder: Path | None = None
    for parent in input_video.parents:
        if parent.name.casefold() != "downloads":
            continue
        try:
            downloads_relative_folder = input_video.parent.relative_to(parent)
        except ValueError:
            downloads_relative_folder = None
        break

    if downloads_relative_folder is not None and len(downloads_relative_folder.parts) >= 2:
        speaker_name = downloads_relative_folder.parts[0]
        if input_video.name.lower() == "stitched_imotions.mp4":
            video_title, youtube_id = split_video_title_and_id(downloads_relative_folder.parts[-1])

    if input_video.name.lower() != "stitched_imotions.mp4":
        video_title, youtube_id = split_video_title_and_id(input_video.stem)
    return VideoContext(
        source_file=input_video,
        speaker_name=speaker_name,
        video_title=video_title,
        youtube_id=youtube_id,
    )


def split_video_title_and_id(value: str) -> tuple[str, str]:
    match = YOUTUBE_ID_PATTERN.match(value)
    if not match:
        return value, ""
    title = match.group("title").rstrip("_")
    return title, match.group("youtube_id")


def predicted_emotion_from_probabilities(probabilities: dict[str, float | str | None]) -> tuple[str, float | str]:
    numeric = {emotion: to_float(probabilities.get(emotion)) for emotion in EMOTION_COLUMNS}
    numeric = {emotion: value for emotion, value in numeric.items() if value is not None}
    if not numeric:
        return "", ""
    emotion, confidence = max(numeric.items(), key=lambda item: item[1])
    return emotion, confidence


def format_optional_number(value: float | str | None) -> str:
    number = to_float(value)
    if number is None:
        return "" if value is None else str(value)
    return format_window_number(number)


def to_float(value: float | str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
