from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_pipeline.batch import discover_videos, run_batch
from audio_pipeline.pipeline import run_single_video
from audio_pipeline import source_context as source_context_module
from audio_pipeline.source_context import copy_run_sidecars, load_source_context


class SkippedModels:
    categorical_model_name = ""
    categorical_model_version = ""
    dimensional_model_name = ""
    dimensional_model_version = ""
    device = "cpu"
    skipped = True
    categorical_available = False
    dimensional_available = False
    errors: list[str] = []


def source_context() -> dict[str, object]:
    return {
        "format_version": 1,
        "source_id": "source-0007",
        "speaker": "Speaker A",
        "speaker_display": "Speaker A",
        "source_kind": "youtube",
        "resolved_link": "https://www.youtube.com/watch?v=abcdefghijk",
        "catalog_path": "sources.csv",
        "catalog_sha256": "a" * 64,
        "user_metadata": {"Country": "=Ireland", "Language": "Irish"},
        "system_metadata": {"title": "Speech", "duration_seconds": 10, "youtube_language": "ga"},
        "output_mapping": {"video_directory": "run/Speaker_A/source-0007_Speech"},
    }


def pooled_source_context() -> dict[str, object]:
    context = source_context()
    context["speaker"] = ""
    context["speaker_display"] = "Pooled (no speaker)"
    return context


def source_manifest_entry(context: dict[str, object], *, selected: bool = True) -> dict[str, object]:
    return {
        "source_id": context["source_id"],
        "speaker": context["speaker"],
        "speaker_display": context["speaker_display"],
        "source_kind": context["source_kind"],
        "resolved_link": context["resolved_link"],
        "selected": selected,
        "user_metadata": context["user_metadata"],
        "system_metadata": context["system_metadata"],
        "output_mapping": context["output_mapping"],
    }


class AudioSourceContextPropagationTests(unittest.TestCase):
    def test_batch_discovery_loads_nearest_bounded_source_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            source_root = root / "Speaker_A" / "source-0007_Speech"
            video = source_root / "download" / "stitched_imotions.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"mp4")
            (source_root / "source_context.json").write_text(
                json.dumps(source_context()),
                encoding="utf-8",
            )

            jobs = discover_videos(root)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source_context["source_id"], "source-0007")
        self.assertEqual(jobs[0].source_context["user_metadata"]["Language"], "Irish")

    def test_expected_catalog_digest_rejects_another_run_before_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "run"
            run_root.mkdir()
            manifest = {
                "format_version": 1,
                "catalog": {"sha256": "a" * 64},
                "sources": [],
            }
            (run_root / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (run_root / "source_metadata.csv").write_text("SourceID\n", encoding="utf-8")
            output = root / "audio-output"

            with self.assertRaisesRegex(ValueError, "catalog digest"):
                copy_run_sidecars(
                    run_root,
                    output,
                    expected_catalog_sha256="b" * 64,
                )

            self.assertFalse(output.exists())

    def test_single_audio_outputs_propagate_source_id_speaker_and_distinct_languages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "run" / "Speaker_A" / "source-0007_Speech" / "stitched_imotions.mp4"
            input_video.parent.mkdir(parents=True)
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text("Row,WindowStart,WindowEnd\n1,0,1\n", encoding="utf-8")
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=1.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                result = run_single_video(
                    input_video,
                    root / "audio-output",
                    emotion_models=SkippedModels(),
                    source_context=source_context(),
                )

            rows = list(csv.reader(result.audio_analysis_csv.open(encoding="utf-8-sig", newline="")))
            data_index = rows.index(["#DATA"])
            metadata = {row[0].lstrip("#"): row[1] for row in rows[1:data_index]}
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            copied_context = json.loads((result.output_dir / "source_context.json").read_text(encoding="utf-8"))

        self.assertEqual(metadata["SourceID"], "source-0007")
        self.assertEqual(metadata["SpeakerName"], "Speaker A")
        self.assertEqual(metadata["SourceSpeaker"], "Speaker A")
        self.assertEqual(metadata["UserLanguage"], "Irish")
        self.assertEqual(metadata["YouTubeLanguage"], "ga")
        self.assertEqual(json.loads(metadata["SourceMetadata"]), {"Country": "=Ireland", "Language": "Irish"})
        self.assertEqual(manifest["source_id"], "source-0007")
        self.assertEqual(manifest["source_metadata"], {"Country": "=Ireland", "Language": "Irish"})
        self.assertEqual(copied_context["source_id"], "source-0007")

    def test_batch_passes_context_to_pipeline_and_exports_it_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = root / "run"
            source_root = downloads / "source-0007_Speech"
            video = source_root / "stitched_imotions.mp4"
            source_root.mkdir(parents=True)
            video.write_bytes(b"mp4")
            context = source_context()
            context["run_root"] = str(downloads.resolve())
            context["output_mapping"] = {"video_directory": str(source_root.resolve())}
            (source_root / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
            manifest_bytes = (
                json.dumps(
                    {
                        "format_version": 1,
                        "catalog": {"sha256": "a" * 64},
                        "sources": [source_manifest_entry(context)],
                    }
                )
                + "\n"
            ).encode("utf-8")
            metadata_bytes = b"\xef\xbb\xbfSourceID,Selected\r\nsource-0007,true\r\n"
            (downloads / "source_manifest.json").write_bytes(manifest_bytes)
            (downloads / "source_metadata.csv").write_bytes(metadata_bytes)
            observed: list[dict[str, object]] = []

            def fake_run(input_video: Path, output_dir: Path, **kwargs):
                observed.append(kwargs["source_context"])
                output_dir.mkdir(parents=True, exist_ok=True)
                for name in ("audio_analysis.csv", "opensmile_features.csv", "audio_analysis_manifest.json"):
                    (output_dir / name).write_text("{}", encoding="utf-8")
                return type(
                    "Result",
                    (),
                    {
                        "output_dir": output_dir,
                        "audio_analysis_csv": output_dir / "audio_analysis.csv",
                        "opensmile_csv": output_dir / "opensmile_features.csv",
                        "manifest_path": output_dir / "audio_analysis_manifest.json",
                        "window_count": 1,
                    },
                )()

            with (
                patch("audio_pipeline.batch.EmotionModelBundle.load", return_value=SkippedModels()),
                patch("audio_pipeline.batch.run_single_video", side_effect=fake_run),
            ):
                result = run_batch(downloads, root / "audio-output")
            with result.manifest_csv.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            copied_manifest_bytes = (result.output_root / "source_manifest.json").read_bytes()
            copied_metadata_bytes = (result.output_root / "source_metadata.csv").read_bytes()

        self.assertEqual(observed[0]["source_id"], "source-0007")
        self.assertEqual(row["source_id"], "source-0007")
        self.assertEqual(row["source_speaker"], "Speaker A")
        self.assertEqual(json.loads(row["source_metadata"]), {"Country": "=Ireland", "Language": "Irish"})
        self.assertEqual(copied_manifest_bytes, manifest_bytes)
        self.assertEqual(copied_metadata_bytes, metadata_bytes)

    def test_batch_source_id_filter_is_repeated_order_independent_and_server_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            for number in (1, 2):
                source_root = root / f"source-{number:04d}_Speech"
                source_root.mkdir(parents=True)
                (source_root / "stitched_imotions.mp4").write_bytes(b"mp4")
                context = source_context()
                context["source_id"] = f"source-{number:04d}"
                (source_root / "source_context.json").write_text(json.dumps(context), encoding="utf-8")

            jobs = discover_videos(root, selected_source_ids=["source-0002", "source-0001"])

            self.assertEqual([job.source_context["source_id"] for job in jobs], ["source-0001", "source-0002"])
            for invalid in (["source-9999"], ["source-0001", "source-0001"]):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    discover_videos(root, selected_source_ids=invalid)

    def test_pooled_procurement_context_is_discoverable_while_raw_speaker_stays_blank(self) -> None:
        from analysis.combined_summary import AUDIO_REQUIRED_METRICS
        from application import backend
        from audio_pipeline.audio_analysis_csv import (
            build_audio_analysis_metadata,
            write_audio_analysis_csv,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata = build_audio_analysis_metadata(
                input_video=root / "source-0007_Speech" / "stitched_imotions.mp4",
                emotion_models=SkippedModels(),
                opensmile_feature_set="egemaps",
                window_seconds=10,
                stride_seconds=5,
                source_context=pooled_source_context(),
            )
            output_csv = root / "audio-output" / "source-0007_Speech" / "audio_analysis.csv"
            row = {
                "WindowIndex": "1",
                "StartSeconds": "0",
                "EndSeconds": "1",
                **{
                    "Happiness" if metric == "Joy" else metric: "0.5"
                    for metric in AUDIO_REQUIRED_METRICS
                },
            }
            write_audio_analysis_csv(output_csv, [row], metadata=metadata)

            discovery = backend.discover_analysis_speakers(
                (backend.AnalysisModalityRunRequest("audio", "run", root / "audio-output"),)
            )

        self.assertEqual(metadata["SpeakerName"], "Pooled (no speaker)")
        self.assertEqual(metadata["SourceSpeaker"], "")
        self.assertEqual(discovery["warnings"], [])
        self.assertEqual(discovery["speakers"][0]["name"], "Pooled (no speaker)")

    def test_top_sidecar_discovery_does_not_inherit_unrelated_ancestor_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ancestor = Path(temp_dir)
            selected_input = ancestor / "unrelated" / "input"
            output = ancestor / "audio-output"
            selected_input.mkdir(parents=True)
            (ancestor / "source_manifest.json").write_text(
                '{"format_version":1,"sources":[]}\n',
                encoding="utf-8",
            )
            (ancestor / "source_metadata.csv").write_text("SourceID\n", encoding="utf-8")

            copied = copy_run_sidecars(selected_input, output)

            self.assertFalse(copied)
            self.assertFalse((output / "source_manifest.json").exists())

    def test_single_file_context_does_not_inherit_an_unrelated_ancestor_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ancestor = Path(temp_dir)
            video = ancestor / "nested" / "video.mp4"
            video.parent.mkdir()
            video.write_bytes(b"mp4")
            (ancestor / "source_context.json").write_text(json.dumps(source_context()), encoding="utf-8")
            (ancestor / "source_manifest.json").write_text(
                '{"catalog":{"sha256":"unrelated"},"sources":[]}\n',
                encoding="utf-8",
            )
            (ancestor / "source_metadata.csv").write_text("SourceID\n", encoding="utf-8")

            self.assertEqual(load_source_context(video), {})

    def test_single_file_context_uses_only_its_explicit_catalog_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "catalog-run"
            source_root = run_root / "source-0007_Speech"
            source_root.mkdir(parents=True)
            video = source_root / "stitched_imotions.mp4"
            video.write_bytes(b"mp4")
            context = source_context()
            context["run_root"] = str(run_root.resolve())
            context["output_mapping"] = {"video_directory": str(source_root.resolve())}
            (source_root / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
            (run_root / "source_manifest.json").write_text(
                json.dumps(
                    {
                        "catalog": {"sha256": "a" * 64},
                        "sources": [source_manifest_entry(context)],
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "source_metadata.csv").write_text("SourceID\nsource-0007\n", encoding="utf-8")

            self.assertEqual(load_source_context(video)["source_id"], "source-0007")

            context.pop("run_root")
            (source_root / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicit catalog run root"):
                load_source_context(video)

    def test_top_sidecar_copy_accepts_over_one_mib_and_rejects_conflicting_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected_input = root / "run"
            output = root / "audio-output"
            selected_input.mkdir()
            manifest = b'{"format_version":1,"sources":[]}\n'
            metadata = b"SourceID,Notes\r\nsource-0001," + (b"x" * (1024 * 1024 + 32)) + b"\r\n"
            (selected_input / "source_manifest.json").write_bytes(manifest)
            (selected_input / "source_metadata.csv").write_bytes(metadata)

            self.assertTrue(copy_run_sidecars(selected_input, output))
            self.assertEqual((output / "source_metadata.csv").read_bytes(), metadata)
            (output / "source_metadata.csv").write_bytes(b"conflict")
            with self.assertRaises(FileExistsError):
                copy_run_sidecars(selected_input, output)

    def test_catalog_audio_binding_rejects_missing_duplicate_or_mismatched_context_before_output(self) -> None:
        for case in ("missing", "duplicate", "mismatch", "orphan"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                run_root = root / "run"
                source_root = run_root / "source-0007_Speech"
                source_root.mkdir(parents=True)
                (source_root / "stitched_imotions.mp4").write_bytes(b"mp4")
                context = source_context()
                context["run_root"] = str(run_root.resolve())
                context["output_mapping"] = {"video_directory": str(source_root.resolve())}
                manifest_context = dict(context)
                if case != "missing":
                    written_context = dict(context)
                    if case == "mismatch":
                        written_context["user_metadata"] = {"Country": "Spoofed"}
                    (source_root / "source_context.json").write_text(
                        json.dumps(written_context),
                        encoding="utf-8",
                    )
                if case == "duplicate":
                    second_root = run_root / "another-video"
                    second_root.mkdir()
                    (second_root / "stitched_imotions.mp4").write_bytes(b"mp4")
                    duplicate_context = dict(context)
                    duplicate_context["output_mapping"] = {"video_directory": str(second_root.resolve())}
                    (second_root / "source_context.json").write_text(
                        json.dumps(duplicate_context),
                        encoding="utf-8",
                    )
                if case == "orphan":
                    orphan_root = run_root / "orphan"
                    orphan_root.mkdir()
                    orphan_context = dict(context)
                    orphan_context["source_id"] = "source-9999"
                    orphan_context["output_mapping"] = {"video_directory": str(orphan_root.resolve())}
                    (orphan_root / "source_context.json").write_text(
                        json.dumps(orphan_context),
                        encoding="utf-8",
                    )
                (run_root / "source_manifest.json").write_text(
                    json.dumps(
                        {
                            "catalog": {"sha256": "a" * 64},
                            "sources": [source_manifest_entry(manifest_context)],
                        }
                    ),
                    encoding="utf-8",
                )
                (run_root / "source_metadata.csv").write_text("SourceID\nsource-0007\n", encoding="utf-8")
                output = root / "audio-output"

                with (
                    patch("audio_pipeline.batch.EmotionModelBundle.load") as load_models,
                    self.assertRaises(ValueError),
                ):
                    run_batch(run_root, output)

                load_models.assert_not_called()
                self.assertFalse(output.exists())

    def test_audio_discovery_excludes_catalog_internal_cache_and_download_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_video = root / "source-0001" / "stitched_imotions.mp4"
            cached_video = root / "_clean_speaker_beta_cache" / "source-0002" / "stitched_imotions.mp4"
            downloaded_video = root / "_downloads" / "download.mp4"
            for video in (real_video, cached_video, downloaded_video):
                video.parent.mkdir(parents=True, exist_ok=True)
                video.write_bytes(b"mp4")

            jobs = discover_videos(root)

        self.assertEqual([job.input_video for job in jobs], [real_video])

    def test_audio_rejects_orphan_source_context_without_top_sidecar_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_root = root / "run"
            source_root = run_root / "source-0007_Speech"
            source_root.mkdir(parents=True)
            video = source_root / "stitched_imotions.mp4"
            video.write_bytes(b"mp4")
            context = source_context()
            context["run_root"] = str(run_root.resolve())
            context["output_mapping"] = {"video_directory": str(source_root.resolve())}
            (source_root / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
            output = root / "audio-output"

            with (
                patch("audio_pipeline.batch.EmotionModelBundle.load") as load_models,
                self.assertRaisesRegex(ValueError, "sidecar pair"),
            ):
                run_batch(run_root, output)

            load_models.assert_not_called()
            self.assertFalse(output.exists())

    def test_audio_sidecar_snapshot_rejects_same_byte_path_replacement_during_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "source_manifest.json"
            replacement = root / "replacement.json"
            target.write_bytes(b"same bytes")
            replacement.write_bytes(b"same bytes")
            real_open = Path.open
            replaced = False

            def replace_before_open(path: Path, *args, **kwargs):
                nonlocal replaced
                if path == target and not replaced:
                    replaced = True
                    replacement.replace(target)
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", replace_before_open):
                with self.assertRaisesRegex(ValueError, "changed"):
                    source_context_module._read_regular_bounded(target, 64)

    def test_audio_sidecar_rollback_preserves_concurrent_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "source_manifest.json"
            metadata = root / "source_metadata.csv"
            real_link = os.link

            def replace_then_fail(source, destination, *args, **kwargs):
                destination_path = Path(destination)
                if destination_path == metadata:
                    manifest.unlink()
                    manifest.write_bytes(b"manifest")
                    raise OSError("synthetic second publish race")
                return real_link(source, destination, *args, **kwargs)

            with patch("audio_pipeline.source_context.os.link", side_effect=replace_then_fail):
                with self.assertRaisesRegex(OSError, "synthetic second publish race"):
                    source_context_module._publish_sidecar_pair(
                        (manifest, b"manifest"),
                        (metadata, b"metadata"),
                    )

            self.assertEqual(manifest.read_bytes(), b"manifest")
            self.assertFalse(metadata.exists())


if __name__ == "__main__":
    unittest.main()
