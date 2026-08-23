"""Canonical provider-neutral metric contract for Video Analysis."""

from __future__ import annotations

from typing import Literal


VideoProvider = Literal["imotions_affdex", "pyfeat_native_face"]

VIDEO_NORMALIZATION_VERSION = "1"

VIDEO_COMMON_METRICS = (
    "Anger", "Disgust", "Fear", "Joy", "Sadness", "Surprise",
    "Neutral", "Valence",
)
VIDEO_IMOTIONS_ONLY_METRICS = (
    "Contempt", "Confusion", "Sentimentality", "Adaptive Valence",
    "Engagement", "Adaptive Engagement",
)
VIDEO_IMOTIONS_CONDITIONAL_METRICS = ("Arousal",)
VIDEO_PYFEAT_METRICS = ("Arousal",)
# Backward-compatible public name: no Video measure is now exclusive to Py-Feat.
VIDEO_PYFEAT_ONLY_METRICS: tuple[str, ...] = ()

# Preserve the established iMotions Video column order and append Arousal, which
# Py-Feat always supplies and iMotions supplies only through a supported channel.
VIDEO_METRICS = (
    "Anger", "Contempt", "Disgust", "Fear", "Joy", "Sadness", "Surprise",
    "Neutral", "Confusion", "Sentimentality", "Valence", "Adaptive Valence",
    "Engagement", "Adaptive Engagement", "Arousal",
)

_AVAILABLE_METRICS: dict[VideoProvider, frozenset[str]] = {
    "imotions_affdex": frozenset(
        (*VIDEO_COMMON_METRICS, *VIDEO_IMOTIONS_ONLY_METRICS, *VIDEO_IMOTIONS_CONDITIONAL_METRICS)
    ),
    "pyfeat_native_face": frozenset((*VIDEO_COMMON_METRICS, *VIDEO_PYFEAT_METRICS)),
}

_CONDITIONAL_METRICS: dict[VideoProvider, frozenset[str]] = {
    "imotions_affdex": frozenset(VIDEO_IMOTIONS_CONDITIONAL_METRICS),
    "pyfeat_native_face": frozenset(),
}

_IMOTIONS_CHANNELS = {
    metric: metric
    for metric in (
        *VIDEO_COMMON_METRICS,
        *VIDEO_IMOTIONS_ONLY_METRICS,
        *VIDEO_IMOTIONS_CONDITIONAL_METRICS,
    )
}
_PYFEAT_CHANNELS = {
    "Anger": "Anger",
    "Disgust": "Disgust",
    "Fear": "Fear",
    "Joy": "Happy",
    "Sadness": "Sad",
    "Surprise": "Surprise",
    "Neutral": "Neutral",
    "Valence": "valence",
    "Arousal": "arousal",
}


def available_video_metrics(provider: VideoProvider) -> frozenset[str]:
    """Return the canonical measures that the provider can supply."""

    try:
        return _AVAILABLE_METRICS[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported Video provider: {provider!r}") from exc


def conditionally_available_video_metrics(provider: VideoProvider) -> frozenset[str]:
    """Return measures that require an actual supported provider channel."""

    try:
        return _CONDITIONAL_METRICS[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported Video provider: {provider!r}") from exc


def validate_video_provider_options(
    provider: VideoProvider,
    *,
    include_landmarks: bool = False,
    include_timing: bool = False,
    exclude_geometry: bool = False,
) -> None:
    """Reject iMotions-only workflow options for a detected Py-Feat source."""

    available_video_metrics(provider)
    unsupported = tuple(
        option
        for enabled, option in (
            (include_landmarks, "--include-landmarks"),
            (include_timing, "--include-timing"),
            (exclude_geometry, "--exclude-geometry"),
        )
        if enabled
    )
    if provider != "pyfeat_native_face" or not unsupported:
        return
    raise ValueError(
        "Video source was detected as Py-Feat / Native Face, which does not support "
        + ", ".join(unsupported)
        + ". Disable these iMotions-only options or select an iMotions AFFDEX source."
    )


def video_measure_guide_rows(provider: VideoProvider) -> tuple[dict[str, str], ...]:
    """Describe provider channels, output scales, and explicit missing values."""

    available = available_video_metrics(provider)
    conditional = conditionally_available_video_metrics(provider)
    channels = _IMOTIONS_CHANNELS if provider == "imotions_affdex" else _PYFEAT_CHANNELS
    rows: list[dict[str, str]] = []
    for metric in VIDEO_METRICS:
        is_available = metric in available
        is_conditional = metric in conditional
        rows.append(
            {
                "canonical_measure": metric,
                "provider": provider,
                "provider_availability": (
                    "conditionally available"
                    if is_conditional
                    else "available" if is_available else "unavailable"
                ),
                "source_channel": (
                    f"{channels[metric]} (supported FEA channel only)"
                    if is_conditional
                    else channels[metric] if is_available else "Unavailable"
                ),
                "output_scale": _output_scale(metric),
                "unsupported_value_rule": "Unsupported values remain blank.",
            }
        )
    return tuple(rows)


def _output_scale(metric: str) -> str:
    if metric in {"Valence", "Adaptive Valence", "Arousal"}:
        return "-100..100"
    return "0..100"
