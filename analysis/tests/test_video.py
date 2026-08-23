"""Canonical Video provider contract and read-only detection tests."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from analysis import video as video_module
from analysis.native_face import analyse_native_face_folder
from analysis.video import (
    CanonicalVideoResult,
    DetectedVideoSource,
    detect_video_source,
    load_canonical_video,
)
from analysis.video_contract import (
    VIDEO_COMMON_METRICS,
    VIDEO_IMOTIONS_CONDITIONAL_METRICS,
    VIDEO_IMOTIONS_ONLY_METRICS,
    VIDEO_METRICS,
    VIDEO_NORMALIZATION_VERSION,
    VIDEO_PYFEAT_METRICS,
    VIDEO_PYFEAT_ONLY_METRICS,
    available_video_metrics,
    conditionally_available_video_metrics,
    video_measure_guide_rows,
)
from processing.face_analysis.outputs import AU_NAMES, artifact_metadata


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, str], ...]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append((relative, "directory", ""))
        else:
            snapshot.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(snapshot)


def _source_context(
    root: Path,
    *,
    source_id: str = "source-0001",
    speaker: str = "speaker-a",
    speaker_display: str = "Speaker A",
    title: str = "First",
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "speaker": speaker,
        "speaker_display": speaker_display,
        "source_kind": "youtube",
        "resolved_link": f"https://www.youtube.com/watch?v={source_id}",
        "user_metadata": {"Country": "Ireland"},
        "system_metadata": {"title": title},
        "output_mapping": {"video_directory": str(root / "media" / source_id)},
        "run_root": str(root),
        "catalog_sha256": "a" * 64,
    }


def _write_verified_pyfeat_run(
    root: Path,
    sources: tuple[tuple[str, str, float, float], ...] = (
        ("Speaker A", "source-0001", 0.2, 0.75),
    ),
    *,
    titles: tuple[str, ...] | None = None,
) -> Path:
    if titles is not None and len(titles) != len(sources):
        raise ValueError("Py-Feat test titles must match the source count")
    header = [
        "media_id", "frame_index", "timestamp_seconds", "face_detected", "face_count",
        "face_index", "is_primary_face", "FaceRectX", "FaceRectY", "FaceRectWidth",
        "FaceRectHeight", "FaceScore", *AU_NAMES, "Neutral", "Happy", "Sad",
        "Surprise", "Fear", "Disgust", "Anger", "valence", "arousal",
    ]
    contexts: list[dict[str, object]] = []
    cores: list[Path] = []
    for index, (speaker_display, source_id, happy, arousal) in enumerate(sources, start=1):
        video = root / speaker_display / source_id
        video.mkdir(parents=True)
        core = video / "face_core.csv"
        cores.append(core)
        with core.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerow(
                [source_id, 0, 0, "true", 1, 0, "true", 0, 0, 1, 1, .95]
                + [0] * len(AU_NAMES)
                + [.1, happy, .3, .4, .5, .6, .7, -.25, arousal]
            )

        context = _source_context(
            root,
            source_id=source_id,
            speaker=f"speaker-{chr(96 + index)}",
            speaker_display=speaker_display,
            title=(titles[index - 1] if titles is not None else f"Interview {index}"),
        )
        contexts.append(context)
        canonical = json.dumps(
            context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        video_manifest = {
            "schema_version": "1.0",
            "status": "completed",
            "media_id": source_id,
            "source": {
                "source_id": source_id,
                "speaker": context["speaker"],
                "speaker_display": context["speaker_display"],
                "catalog_sha256": context["catalog_sha256"],
                "user_metadata": context["user_metadata"],
                "system_metadata": context["system_metadata"],
                "output_mapping": context["output_mapping"],
                "source_context_sha256": hashlib.sha256(canonical).hexdigest(),
                "source_context": context,
            },
            "output_contract_version": "1.0",
            "outputs": {"core": artifact_metadata(core, "core")},
        }
        (video / "video_manifest.json").write_text(
            json.dumps(video_manifest), encoding="utf-8"
        )
    (root / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "completed",
                "catalog_sha256": "a" * 64,
                "processed_source_ids": [context["source_id"] for context in contexts],
            }
        ),
        encoding="utf-8",
    )
    (root / "source_manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "catalog": {
                    "sha256": "a" * 64,
                    "metadata_headers": ["Country"],
                    "metadata_export_headers": {"Country": "Country"},
                },
                "sources": [{**context, "selected": True} for context in contexts],
            }
        ),
        encoding="utf-8",
    )
    with (root / "source_metadata.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["SourceID", "Country"])
        for context in contexts:
            writer.writerow([context["source_id"], "Ireland"])
    return cores[0]


def _write_verified_pyfeat_sources(root: Path, count: int) -> None:
    header = [
        "media_id", "frame_index", "timestamp_seconds", "face_detected", "face_count",
        "face_index", "is_primary_face", "FaceRectX", "FaceRectY", "FaceRectWidth",
        "FaceRectHeight", "FaceScore", *AU_NAMES, "Neutral", "Happy", "Sad",
        "Surprise", "Fear", "Disgust", "Anger", "valence", "arousal",
    ]
    for index in range(1, count + 1):
        source_id = f"source-{index}"
        video = root / "Speaker A" / source_id
        video.mkdir(parents=True)
        core = video / "face_core.csv"
        with core.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerow(
                [source_id, 0, 0, "true", 1, 0, "true", 0, 0, 1, 1, .95]
                + [0] * len(AU_NAMES)
                + [.1, .2, .3, .4, .5, .6, .7, -.25, .75]
            )
        (video / "video_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "completed",
                    "media_id": source_id,
                    "source": {"source_id": source_id},
                    "output_contract_version": "1.0",
                    "outputs": {"core": artifact_metadata(core, "core")},
                }
            ),
            encoding="utf-8",
        )


def _write_pyfeat_analysis_reports(
    report_root: Path,
    sources: tuple[tuple[str, str, float, float], ...] = (
        ("Speaker A", "source-0001", 0.2, 0.75),
    ),
    *,
    titles: tuple[str, ...] | None = None,
) -> Path:
    """Create the provider-tagged report tree emitted by analysis.native_face."""

    raw_root = report_root.parent / f"{report_root.name}-native-input"
    _write_verified_pyfeat_run(raw_root, sources, titles=titles)
    analyse_native_face_folder(
        raw_root,
        output_root=report_root,
        write_graphs=False,
    )
    return report_root


def _write_imotions_csv(root: Path, name: str = "imotions.csv") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["#INFO"])
        writer.writerow(["#Category", "Timestamp", "FEA(Emotions)", "FEA(Emotions)"])
        writer.writerow(["#DATA"])
        writer.writerow(["Row", "Timestamp", "Anger", "Engagement"])
        writer.writerow([1, 0, 10, 20])
    return path


def _write_imotions_sources(root: Path, count: int, *, include_arousal: bool = False) -> None:
    metrics = [
        "Anger", "Contempt", "Disgust", "Fear", "Joy", "Sadness", "Surprise",
        "Neutral", "Confusion", "Sentimentality", "Valence", "Adaptive Valence",
        "Engagement", "Adaptive Engagement",
    ]
    if include_arousal:
        metrics.append("Arousal")
    header = ["Row", "Timestamp", *metrics]
    categories = ["Counter", "Timestamp", *("FEA(Emotions)" for _ in metrics)]
    units = ["Index", "Millisecond", *("Index" for _ in metrics)]
    channels = [
        "Row",
        "Timestamp",
        *(f"FEA_Emotion_{metric.replace(' ', '_')}" for metric in metrics),
    ]
    values: list[object] = [
        1, 0, 10, "", 20, 30, 40, 50, 60, 70, 80, 90, -25, -10, 55, 65,
    ]
    if include_arousal:
        values.append(75)
    for index in range(1, count + 1):
        path = root / f"source-{index}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["#INFO"])
            writer.writerow(["#Category", *categories])
            writer.writerow(["#Unit", *units])
            writer.writerow(["#Display name", *header])
            writer.writerow(["#Channel identifier", *channels])
            writer.writerow(["#DATA"])
            writer.writerow(header)
            writer.writerow(values)


def _write_imported_column_manifest(root: Path, providers: tuple[str, ...]) -> Path:
    path = root / "combined" / "other_findings" / "column_manifest.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("source", "statistic", "source_column", "provided_by"),
        )
        writer.writeheader()
        for index, provider in enumerate(providers, start=1):
            writer.writerow(
                {
                    "source": f"source-{index:04d}",
                    "statistic": "Anger",
                    "source_column": "Anger",
                    "provided_by": provider,
                }
            )
    return path


def _write_legacy_descriptive_report(
    root: Path,
    measures: tuple[str, ...],
    category: str,
) -> Path:
    path = root / "Speaker A" / "combined" / "other_findings" / "descriptive_statistics.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for measure in measures:
            writer.writerow([measure])
            writer.writerow(["classification", "core", "category", category, "unit", "Index"])
            writer.writerow(["metric", "source-0001"])
            writer.writerow(["count", 1])
            writer.writerow(["missing", 0])
            writer.writerow(["mean", 10])
            writer.writerow(["stddev", 0])
            writer.writerow([])
    return path


def _write_legacy_imotions_report(root: Path) -> Path:
    return _write_legacy_descriptive_report(
        root,
        ("Anger", "Valence"),
        "FEA(Emotions)",
    )


def _write_speaker_legacy_imotions_report(
    root: Path,
    speaker: str,
    source_ids: tuple[str, ...],
    means: tuple[float, ...],
) -> Path:
    path = root / speaker / "combined" / "other_findings" / "descriptive_statistics.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for measure in ("Anger", "Valence"):
            writer.writerow([measure])
            writer.writerow(
                ["classification", "core", "category", "FEA(Emotions)", "unit", "Index"]
            )
            writer.writerow(["metric", *source_ids])
            writer.writerow(["count", *(1 for _ in source_ids)])
            writer.writerow(["missing", *(0 for _ in source_ids)])
            writer.writerow(["mean", *means])
            writer.writerow(["stddev", *(0 for _ in source_ids)])
            writer.writerow([])
    return path


class VideoContractTests(unittest.TestCase):
    def test_metric_groups_and_compatibility_union_are_stable(self) -> None:
        self.assertEqual(
            VIDEO_COMMON_METRICS,
            (
                "Anger", "Disgust", "Fear", "Joy", "Sadness", "Surprise",
                "Neutral", "Valence",
            ),
        )
        self.assertEqual(
            VIDEO_IMOTIONS_ONLY_METRICS,
            (
                "Contempt", "Confusion", "Sentimentality", "Adaptive Valence",
                "Engagement", "Adaptive Engagement",
            ),
        )
        self.assertEqual(VIDEO_IMOTIONS_CONDITIONAL_METRICS, ("Arousal",))
        self.assertEqual(VIDEO_PYFEAT_METRICS, ("Arousal",))
        self.assertEqual(VIDEO_PYFEAT_ONLY_METRICS, ())
        self.assertEqual(
            VIDEO_METRICS,
            (
                "Anger", "Contempt", "Disgust", "Fear", "Joy", "Sadness",
                "Surprise", "Neutral", "Confusion", "Sentimentality", "Valence",
                "Adaptive Valence", "Engagement", "Adaptive Engagement", "Arousal",
            ),
        )
        self.assertTrue(VIDEO_NORMALIZATION_VERSION)

    def test_provider_availability_marks_unsupported_measures_blank(self) -> None:
        expected_available = {
            "imotions_affdex": frozenset(
                (*VIDEO_COMMON_METRICS, *VIDEO_IMOTIONS_ONLY_METRICS, "Arousal")
            ),
            "pyfeat_native_face": frozenset((*VIDEO_COMMON_METRICS, *VIDEO_PYFEAT_METRICS)),
        }
        expected_conditional = {
            "imotions_affdex": frozenset({"Arousal"}),
            "pyfeat_native_face": frozenset(),
        }
        for provider, expected in expected_available.items():
            with self.subTest(provider=provider):
                self.assertEqual(available_video_metrics(provider), expected)
                self.assertEqual(
                    conditionally_available_video_metrics(provider),
                    expected_conditional[provider],
                )
                guide = video_measure_guide_rows(provider)
                self.assertEqual(tuple(row["canonical_measure"] for row in guide), VIDEO_METRICS)
                for row in guide:
                    metric = row["canonical_measure"]
                    availability = (
                        "conditionally available"
                        if metric in expected_conditional[provider]
                        else "available" if metric in expected else "unavailable"
                    )
                    self.assertEqual(
                        row["provider_availability"],
                        availability,
                    )
                    self.assertTrue(row["source_channel"])
                    self.assertTrue(row["output_scale"])
                    self.assertEqual(
                        row["unsupported_value_rule"],
                        "Unsupported values remain blank.",
                    )
                    if metric not in expected:
                        self.assertEqual(row["source_channel"], "Unavailable")
                    elif metric in expected_conditional[provider]:
                        self.assertEqual(
                            row["source_channel"],
                            "Arousal (supported FEA channel only)",
                        )


class PyFeatCanonicalVideoTests(unittest.TestCase):
    def test_loads_provider_tagged_analysis_reports_without_raw_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = _write_pyfeat_analysis_reports(
                root / "pyfeat-analysis",
                (
                    ("Speaker A", "source-0001", 0.2, 0.75),
                    ("Speaker B", "source-0002", 0.6, -0.25),
                ),
            )
            self.assertFalse(any(reports.rglob("face_core.csv")))
            self.assertFalse(any(reports.rglob("video_manifest.json")))
            before = _tree_snapshot(reports)

            detected = detect_video_source(reports, "import")
            result = load_canonical_video(detected)

            self.assertEqual(detected.provider, "pyfeat_native_face")
            self.assertEqual(result.provider, "pyfeat_native_face")
            self.assertEqual(result.source_ids, ("Interview_1", "Interview_2"))
            self.assertEqual(tuple(row["Joy"] for row in result.rows), (20.0, 60.0))
            self.assertEqual(tuple(row["Arousal"] for row in result.rows), (75.0, -25.0))
            self.assertTrue(
                any(
                    item.source_id == "Interview_1"
                    and item.canonical_measure == "Joy"
                    and item.original_field == "Happy"
                    for item in result.provenance
                )
            )
            self.assertEqual(_tree_snapshot(reports), before)

    def test_namespaces_repeated_local_source_ids_across_speaker_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports = _write_pyfeat_analysis_reports(
                root / "pyfeat-analysis",
                (
                    ("Speaker A", "source-0001", 0.2, 0.75),
                    ("Speaker B", "source-0002", 0.6, -0.25),
                ),
                titles=("Interview 1", "Interview 1"),
            )
            before = _tree_snapshot(reports)

            result = load_canonical_video(detect_video_source(reports, "import"))

            expected = ("Speaker A::Interview_1", "Speaker B::Interview_1")
            self.assertEqual(result.source_ids, expected)
            self.assertEqual(tuple(row["Joy"] for row in result.rows), (20.0, 60.0))
            self.assertEqual(
                tuple(
                    item.source_id
                    for item in result.provenance
                    if item.canonical_measure == "Joy"
                ),
                expected,
            )
            self.assertEqual(_tree_snapshot(reports), before)

    def test_normalizes_names_scales_and_union_blanks_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_verified_pyfeat_sources(root, 1)
            before = _tree_snapshot(root)

            result = load_canonical_video(detect_video_source(root, "run"))

            self.assertIsInstance(result, CanonicalVideoResult)
            self.assertEqual(result.provider, "pyfeat_native_face")
            self.assertEqual(result.normalization_version, VIDEO_NORMALIZATION_VERSION)
            self.assertEqual(result.source_ids, ("source-1",))
            self.assertEqual(tuple(result.rows[0]), VIDEO_METRICS)
            self.assertEqual(
                result.rows[0],
                {
                    "Anger": 70.0,
                    "Contempt": None,
                    "Disgust": 60.0,
                    "Fear": 50.0,
                    "Joy": 20.0,
                    "Sadness": 30.0,
                    "Surprise": 40.0,
                    "Neutral": 10.0,
                    "Confusion": None,
                    "Sentimentality": None,
                    "Valence": -25.0,
                    "Adaptive Valence": None,
                    "Engagement": None,
                    "Adaptive Engagement": None,
                    "Arousal": 75.0,
                },
            )
            self.assertTrue(
                any(
                    item.canonical_measure == "Joy" and item.original_field == "Happy"
                    for item in result.provenance
                )
            )
            self.assertTrue(
                any(
                    item.canonical_measure == "Sadness" and item.original_field == "Sad"
                    for item in result.provenance
                )
            )
            self.assertEqual(_tree_snapshot(root), before)

    def test_provenance_omits_schema_only_unsupported_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_verified_pyfeat_sources(root, 1)

            result = load_canonical_video(detect_video_source(root, "run"))

            provenance_metrics = {
                item.canonical_measure
                for item in result.provenance
                if item.source_id == "source-1"
            }
            self.assertEqual(
                provenance_metrics,
                available_video_metrics("pyfeat_native_face"),
            )
            self.assertTrue({"Contempt", "Confusion"}.isdisjoint(provenance_metrics))

    def test_retains_natural_source_order_without_a_source_count_cap(self) -> None:
        for count in (1, 7, 14):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                _write_verified_pyfeat_sources(root, count)

                result = load_canonical_video(detect_video_source(root, "run"))

                self.assertEqual(
                    result.source_ids,
                    tuple(f"source-{index}" for index in range(1, count + 1)),
                )
                self.assertEqual(len(result.rows), count)


class IMotionsCanonicalVideoTests(unittest.TestCase):
    def test_normalizes_common_and_provider_metrics_while_preserving_blanks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_imotions_sources(root, 1)
            before = _tree_snapshot(root)

            result = load_canonical_video(detect_video_source(root, "run"))

            self.assertEqual(result.provider, "imotions_affdex")
            self.assertEqual(result.source_ids, ("source-1",))
            self.assertEqual(tuple(result.rows[0]), VIDEO_METRICS)
            self.assertEqual(
                result.rows[0],
                {
                    "Anger": 10.0,
                    "Contempt": None,
                    "Disgust": 20.0,
                    "Fear": 30.0,
                    "Joy": 40.0,
                    "Sadness": 50.0,
                    "Surprise": 60.0,
                    "Neutral": 70.0,
                    "Confusion": 80.0,
                    "Sentimentality": 90.0,
                    "Valence": -25.0,
                    "Adaptive Valence": -10.0,
                    "Engagement": 55.0,
                    "Adaptive Engagement": 65.0,
                    "Arousal": None,
                },
            )
            self.assertIsNone(result.rows[0]["Contempt"])
            self.assertNotEqual(result.rows[0]["Contempt"], 0)
            self.assertTrue(
                any(
                    item.canonical_measure == "Adaptive Engagement"
                    and item.original_field == "Adaptive Engagement"
                    and item.channel_identifier == "FEA_Emotion_Adaptive_Engagement"
                    for item in result.provenance
                )
            )
            self.assertEqual(_tree_snapshot(root), before)

    def test_populates_arousal_only_from_an_actual_supported_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_imotions_sources(root, 1, include_arousal=True)

            result = load_canonical_video(detect_video_source(root, "run"))

            self.assertEqual(result.rows[0]["Arousal"], 75.0)
            self.assertTrue(
                any(
                    item.canonical_measure == "Arousal"
                    and item.original_field == "Arousal"
                    for item in result.provenance
                )
            )

    def test_retains_natural_source_order_without_a_source_count_cap(self) -> None:
        for count in (1, 7, 14):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                _write_imotions_sources(root, count)

                result = load_canonical_video(detect_video_source(root, "run"))

                self.assertEqual(
                    result.source_ids,
                    tuple(f"source-{index}" for index in range(1, count + 1)),
                )
                self.assertEqual(len(result.rows), count)

    def test_loads_legacy_descriptive_reports_through_the_imotions_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_legacy_imotions_report(root)
            detected = detect_video_source(root, "import")

            result = load_canonical_video(detected)

            self.assertEqual(result.source_ids, ("source-0001",))
            self.assertEqual(result.rows[0]["Anger"], 10.0)
            self.assertEqual(result.rows[0]["Valence"], 10.0)
            self.assertIsNone(result.rows[0]["Engagement"])
            self.assertTrue(any("legacy" in warning.casefold() for warning in result.warnings))

    def test_namespaces_colliding_local_ordinals_across_legacy_speaker_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_speaker_legacy_imotions_report(root, "Speaker A", ("001", "002"), (10, 20))
            _write_speaker_legacy_imotions_report(root, "Speaker B", ("001", "002"), (30, 40))

            result = load_canonical_video(detect_video_source(root, "import"))

            self.assertEqual(
                result.source_ids,
                (
                    "Speaker A::001",
                    "Speaker A::002",
                    "Speaker B::001",
                    "Speaker B::002",
                ),
            )
            self.assertEqual(tuple(row["Anger"] for row in result.rows), (10, 20, 30, 40))

    def test_preserves_globally_unique_ids_across_legacy_speaker_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_speaker_legacy_imotions_report(root, "Speaker A", ("source-a",), (10,))
            _write_speaker_legacy_imotions_report(root, "Speaker B", ("source-b",), (30,))

            result = load_canonical_video(detect_video_source(root, "import"))

            self.assertEqual(result.source_ids, ("source-a", "source-b"))

    def test_preserves_single_legacy_report_source_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_speaker_legacy_imotions_report(root, "Speaker A", ("001", "002"), (10, 20))

            result = load_canonical_video(detect_video_source(root, "import"))

            self.assertEqual(result.source_ids, ("001", "002"))

    def test_rejects_contradictory_imported_provider_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_legacy_imotions_report(root)
            _write_imported_column_manifest(root, ("Py-Feat / Native Face",))
            detected = DetectedVideoSource(
                provider="imotions_affdex",
                source_path=root.resolve(),
                source_method="import",
                evidence=("Caller-supplied iMotions import.",),
            )

            with self.assertRaisesRegex(ValueError, "contradictory.*provider metadata"):
                load_canonical_video(detected)


class VideoOutputProvenanceTests(unittest.TestCase):
    def test_serializes_provider_detection_availability_and_actual_columns_read_only(self) -> None:
        """Dropping detection or actual-field metadata must make manifest handoff incomplete."""

        fixtures = (
            ("pyfeat_native_face", _write_verified_pyfeat_sources),
            ("imotions_affdex", _write_imotions_sources),
        )
        for provider, writer in fixtures:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                writer(root, 1)
                before = _tree_snapshot(root)
                detected = detect_video_source(root, "run")
                result = load_canonical_video(detected)

                provenance_builder = getattr(result, "output_provenance", None)
                self.assertIsNotNone(
                    provenance_builder,
                    "Canonical Video results must expose provider-aware output provenance.",
                )
                provenance = provenance_builder(detected)
                payload = provenance.to_manifest_payload()
                json.dumps(payload)
                self.assertEqual(payload["requested_modality"], "video")
                self.assertEqual(payload["resolved_provider"], provider)
                self.assertEqual(payload["source_method"], "run")
                self.assertEqual(payload["source_path"], str(root.resolve()))
                self.assertEqual(payload["detection_evidence"], list(detected.evidence))
                self.assertEqual(payload["detection_warnings"], list(detected.warnings))
                self.assertEqual(
                    payload["normalization_contract_version"],
                    VIDEO_NORMALIZATION_VERSION,
                )
                self.assertEqual(
                    [row["canonical_measure"] for row in payload["canonical_availability"]],
                    list(VIDEO_METRICS),
                )
                self.assertTrue(payload["original_columns"])
                self.assertTrue(
                    all(row["original_field"] for row in payload["original_columns"])
                )
                self.assertTrue(
                    all(row["channel_identifier"] for row in payload["original_columns"])
                )
                column_rows = provenance.to_column_manifest_rows()
                self.assertEqual(
                    tuple(row["canonical_measure"] for row in column_rows),
                    VIDEO_METRICS,
                )
                self.assertTrue(
                    all(row["requested_modality"] == "video" for row in column_rows)
                )
                self.assertTrue(
                    all(row["resolved_provider"] == provider for row in column_rows)
                )
                self.assertEqual(_tree_snapshot(root), before)

    def test_removed_provider_sheet_overrides_return_actionable_video_migration_error(self) -> None:
        """Provider-sheet override aliases must never fail as unexplained unknown keys."""

        validator = getattr(video_module, "validate_video_reference_override_keys", None)
        self.assertIsNotNone(validator)
        for key, replacement in (
            ("Native Face", "Video"),
            ("Py-Feat - Native Face|Arousal", "Video|Arousal"),
            ("Py-Feat / Native Face|Valence", "Video|Valence"),
            ("Video / iMotions|Engagement", "Video|Engagement"),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(
                ValueError,
                rf"removed provider-specific.*{re.escape(replacement)}",
            ):
                validator((key,))
        self.assertEqual(
            validator(("Video", "Video|Anger", "Audio|Arousal")),
            ("Video", "Video|Anger", "Audio|Arousal"),
        )


class VideoDetectionTests(unittest.TestCase):
    def test_detects_verified_pyfeat_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_verified_pyfeat_run(root)
            before = _tree_snapshot(root)

            detected = detect_video_source(root, "run")

            self.assertEqual(detected.provider, "pyfeat_native_face")
            self.assertEqual(detected.source_path, root.resolve())
            self.assertEqual(detected.source_method, "run")
            self.assertTrue(any("verified" in item.casefold() for item in detected.evidence))
            self.assertEqual(_tree_snapshot(root), before)

    def test_detects_imotions_csv_headers_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_imotions_csv(root)
            before = _tree_snapshot(root)

            detected = detect_video_source(root, "run")

            self.assertEqual(detected.provider, "imotions_affdex")
            self.assertTrue(any("data row" in item.casefold() for item in detected.evidence))
            self.assertEqual(_tree_snapshot(root), before)

    def test_unbound_video_manifest_does_not_override_valid_imotions_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_imotions_csv(root)
            (root / "video_manifest.json").write_text(
                json.dumps({"kind": "unrelated-video-report", "status": "completed"}),
                encoding="utf-8",
            )
            before = _tree_snapshot(root)

            try:
                detected = detect_video_source(root, "run")
            except ValueError as exc:
                self.fail(f"An unbound video manifest must not claim Native Face: {exc}")

            self.assertEqual(detected.provider, "imotions_affdex")
            self.assertEqual(_tree_snapshot(root), before)

    def test_non_object_video_manifest_does_not_override_valid_imotions_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_imotions_csv(root)
            (root / "video_manifest.json").write_text(
                json.dumps(["unrelated-video-report"]),
                encoding="utf-8",
            )
            before = _tree_snapshot(root)

            detected = detect_video_source(root, "run")

            self.assertEqual(detected.provider, "imotions_affdex")
            self.assertEqual(_tree_snapshot(root), before)

    def test_rejects_source_with_no_provider_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "unrelated.txt").write_text("not provider data", encoding="utf-8")
            before = _tree_snapshot(root)

            with self.assertRaisesRegex(ValueError, "iMotions.*face_core.csv"):
                detect_video_source(root, "import")

            self.assertEqual(_tree_snapshot(root), before)

    def test_rejects_source_with_both_provider_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_verified_pyfeat_run(root)
            _write_imotions_csv(root)
            before = _tree_snapshot(root)

            with self.assertRaisesRegex(ValueError, "both.*iMotions.*Py-Feat"):
                detect_video_source(root, "run")

            self.assertEqual(_tree_snapshot(root), before)

    def test_incomplete_pyfeat_signature_fails_as_pyfeat_without_imotions_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "native").mkdir()
            (root / "native" / "face_core.csv").write_text("incomplete", encoding="utf-8")
            _write_imotions_csv(root)
            before = _tree_snapshot(root)

            with self.assertRaisesRegex(ValueError, "Py-Feat.*Native Face"):
                detect_video_source(root, "run")

            self.assertEqual(_tree_snapshot(root), before)

    def test_bound_face_run_manifest_fails_as_pyfeat_without_imotions_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "outputs": {
                            "run_index": "run_index.csv",
                            "per_video": {
                                "core": "face_core.csv",
                                "full": "face_features.parquet",
                                "manifest": "video_manifest.json",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            _write_imotions_csv(root)
            before = _tree_snapshot(root)

            with self.assertRaisesRegex(ValueError, "Py-Feat.*Native Face"):
                detect_video_source(root, "run")

            self.assertEqual(_tree_snapshot(root), before)

    def test_tampered_pyfeat_binding_fails_before_output_directory_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            core = _write_verified_pyfeat_run(root)
            manifest_path = core.with_name("video_manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source"]["speaker"] = "tampered-speaker"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            prospective_output = root / "analysis"
            before = _tree_snapshot(root)

            with self.assertRaisesRegex(ValueError, "Py-Feat.*speaker.*does not match"):
                detect_video_source(root, "run")

            self.assertFalse(prospective_output.exists())
            self.assertEqual(_tree_snapshot(root), before)

    def test_imported_manifest_provider_conflict_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_imported_column_manifest(root, ("iMotions AFFDEX", "Py-Feat / Native Face"))
            before = _tree_snapshot(root)

            with self.assertRaisesRegex(ValueError, "conflicting imported Video provider metadata"):
                detect_video_source(root, "import")

            self.assertEqual(_tree_snapshot(root), before)

    def test_legacy_imotions_report_shape_returns_warning_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_legacy_imotions_report(root)
            before = _tree_snapshot(root)

            detected = detect_video_source(root, "import")

            self.assertEqual(detected.provider, "imotions_affdex")
            self.assertTrue(any("legacy" in item.casefold() for item in detected.evidence))
            self.assertTrue(any("legacy" in item.casefold() for item in detected.warnings))
            self.assertEqual(_tree_snapshot(root), before)

    def test_bare_engagement_legacy_report_is_not_imotions_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_legacy_descriptive_report(root, ("Engagement",), "Business KPI")
            before = _tree_snapshot(root)

            with self.assertRaisesRegex(ValueError, "No supported Video provider evidence"):
                detect_video_source(root, "import")

            self.assertEqual(_tree_snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
