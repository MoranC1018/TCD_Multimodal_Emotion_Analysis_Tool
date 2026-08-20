from __future__ import annotations

import csv
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from docx import Document

from application import backend
from application import launcher
from application import manual_segments
from analysis.combined_summary import AUDIO_METRICS, AUDIO_REQUIRED_METRICS


_Speaker = type(backend.SPEAKERS[0])
NEUTRAL_SPEAKERS = tuple(
    _Speaker(f"speaker_{letter.casefold()}", f"Speaker {letter}", f"Speaker {letter}", "Group", column, (f"speaker {letter.casefold()}",))
    for letter, column in zip("ABCDE", "DEFGH")
)


def neutral_resolve_speaker(value: str):
    key = backend.normalized(value)
    for speaker in NEUTRAL_SPEAKERS:
        if key in {backend.normalized(speaker.speaker_id), backend.normalized(speaker.display_name)}:
            return speaker
    raise backend.InputError(f"Could not uniquely identify speaker from {value!r}; matches: none")


class LauncherProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._speaker_registry = patch.object(backend, "SPEAKERS", NEUTRAL_SPEAKERS)
        self._speaker_resolver = patch.object(backend, "resolve_speaker", side_effect=neutral_resolve_speaker)
        self._speaker_registry.start()
        self._speaker_resolver.start()
        self.addCleanup(self._speaker_resolver.stop)
        self.addCleanup(self._speaker_registry.stop)

    def test_analysis_speaker_discovery_payload_rejects_invalid_modalities_before_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            not_a_folder = root / "not-a-folder.csv"
            not_a_folder.write_text("not a folder", encoding="utf-8")
            valid = {"modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(source)}]}
            invalid_payloads = (
                {"modalities": []},
                {"modalities": [{"name": "text", "sourceMethod": "run", "sourcePath": str(source)}]},
                {"modalities": [{"name": "audio", "sourceMethod": "unsupported", "sourcePath": str(source)}]},
                {"modalities": [valid["modalities"][0], valid["modalities"][0]]},
                {"modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": "  "}]},
                {"modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(root / "missing")}]},
                {"modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(not_a_folder)}]},
            )

            request = launcher.analysis_speaker_discovery_modalities_from_payload(valid)
            self.assertEqual(request, (backend.AnalysisModalityRunRequest("audio", "run", source),))
            for payload in invalid_payloads:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    launcher.analysis_speaker_discovery_modalities_from_payload(payload)

    def test_analysis_speaker_discovery_handler_returns_candidates_without_starting_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "audio"
            self._write_audio_csv(source / "Speaker B" / "speech" / "audio_analysis.csv", "Speaker B")
            handler = object.__new__(launcher.VideoStackUiHandler)
            responses: list[dict[str, object]] = []
            handler.send_json = responses.append

            with patch.object(launcher, "start_process", side_effect=AssertionError("speaker discovery must not start a process")):
                handler.handle_analysis_speakers(
                    {"modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(source)}]}
                )

        self.assertEqual(
            responses[0],
            {
                "speakers": [{"key": "speaker_b", "name": "Speaker B", "availableIn": ["audio"]}],
                "warnings": [],
            },
        )

    def test_analysis_speaker_discovery_handler_accepts_legacy_audio_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "audio"
            self._write_audio_csv(
                source / "Speaker B" / "speech" / "audio_analysis.csv",
                "Speaker B",
                AUDIO_REQUIRED_METRICS,
            )
            handler = object.__new__(launcher.VideoStackUiHandler)
            responses: list[dict[str, object]] = []
            handler.send_json = responses.append

            handler.handle_analysis_speakers(
                {
                    "modalities": [
                        {
                            "name": "audio",
                            "sourceMethod": "run",
                            "sourcePath": str(source),
                        }
                    ]
                }
            )

        self.assertEqual(responses[0]["speakers"][0]["key"], "speaker_b")
        self.assertEqual(responses[0]["warnings"], [])

    def test_analysis_speaker_discovery_handler_rejects_empty_and_malformed_sources_without_starting_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty = root / "empty"
            malformed_audio = root / "malformed-audio"
            empty_audio = root / "empty-audio"
            empty.mkdir()
            path = malformed_audio / "Speaker B" / "speech" / "audio_analysis.csv"
            path.parent.mkdir(parents=True)
            path.write_text("not,a,valid,audio,report\n", encoding="utf-8")
            empty_path = empty_audio / "Speaker B" / "speech" / "audio_analysis.csv"
            empty_path.parent.mkdir(parents=True)
            empty_path.touch()
            handler = object.__new__(launcher.VideoStackUiHandler)
            handler.send_json = Mock()

            invalid_payloads = (
                {"modalities": [{"name": "imotions", "sourceMethod": "run", "sourcePath": str(empty)}]},
                {"modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(malformed_audio)}]},
                {"modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(empty_audio)}]},
            )
            with patch.object(launcher, "start_process") as start_process:
                for payload in invalid_payloads:
                    with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, "usable|valid|missing"):
                        handler.handle_analysis_speakers(payload)

        start_process.assert_not_called()

    @staticmethod
    def _write_audio_csv(
        path: Path,
        speaker: str,
        metrics: tuple[str, ...] = AUDIO_METRICS,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        source_labels = ["Happiness" if metric == "Joy" else metric for metric in metrics]
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(
                [
                    ["#INFO"],
                    ["#SpeakerName", speaker],
                    ["#VideoTitle", "Speech"],
                    ["#DATA"],
                    [
                        "WindowIndex", "StartSeconds", "SpeakerName", *source_labels,
                    ],
                    ["1", "0", speaker, *("0.5" for _ in metrics)],
                ]
            )

    def test_progress_prefers_processed_counts(self) -> None:
        progress = launcher.parse_progress_line("Local procurement complete: 4 processed, 1 failed.")

        self.assertEqual(progress["current"], 5)
        self.assertEqual(progress["label"], "4 processed, 1 failed")

    def test_progress_reads_processing_video_lines(self) -> None:
        progress = launcher.parse_progress_line("Processing Speaker B/April 2022.mp4")

        self.assertEqual(progress["label"], "Processing Speaker B/April 2022.mp4")
        self.assertIsNone(progress["current"])

    def test_progress_reads_audio_batch_summary_lines(self) -> None:
        progress = launcher.parse_progress_line("Processed videos: 12")

        self.assertEqual(progress["current"], 12)
        self.assertEqual(progress["label"], "12 audio videos processed")

    def test_progress_reads_clean_speaker_beta_summary_lines(self) -> None:
        progress = launcher.parse_progress_line("Clean speaker beta complete: 7 processed, 2 failed.")

        self.assertEqual(progress["current"], 9)
        self.assertEqual(progress["label"], "7 clean speaker videos processed, 2 failed")

    def test_progress_reads_clean_speaker_beta_increment_lines(self) -> None:
        progress = launcher.parse_progress_line("Clean speaker beta processed videos: 3")

        self.assertEqual(progress["current"], 3)
        self.assertEqual(progress["label"], "3 clean speaker videos processed")

    def test_progress_reads_isolated_clean_speaker_start_lines(self) -> None:
        progress = launcher.parse_progress_line("Starting isolated child for global video 13/59: Speaker/Video")

        self.assertEqual(progress["current"], 12)
        self.assertEqual(progress["total"], 59)
        self.assertEqual(progress["label"], "Processing Speaker/Video")

    def test_progress_reads_isolated_clean_speaker_skip_lines(self) -> None:
        progress = launcher.parse_progress_line("Skipping completed global video 4/59: Speaker/Done")

        self.assertEqual(progress["current"], 4)
        self.assertEqual(progress["total"], 59)
        self.assertEqual(progress["label"], "Skipped completed Speaker/Done")

    def test_progress_reads_docx_pipeline_item_lines(self) -> None:
        progress = launcher.parse_progress_line("[2/9] mZBHkYWKE5M | Speaker E | standard_license_10_percent_sample")

        self.assertEqual(progress["current"], 1)
        self.assertEqual(progress["total"], 9)
        self.assertIn("Speaker E", progress["label"])

    def test_progress_reads_docx_pipeline_completion_line(self) -> None:
        progress = launcher.parse_progress_line("Pipeline complete.")

        self.assertEqual(progress["label"], "Pipeline complete")

    def test_progress_reads_combined_workflow_stages_and_completed_output_paths(self) -> None:
        starting = launcher.parse_progress_line("Starting Video / iMotions analysis")
        completed = launcher.parse_progress_line(
            r"Completed Video / iMotions analysis: C:\reports\video"
        )
        workbook = launcher.parse_progress_line("Starting combined workbook")

        self.assertEqual(starting["label"], "Analysing Video / iMotions")
        self.assertEqual(starting["stage"], "Video / iMotions analysis")
        self.assertEqual(completed["label"], "Video / iMotions analysis complete")
        self.assertEqual(
            completed["completedOutput"],
            {"modality": "video", "path": r"C:\reports\video"},
        )
        self.assertEqual(workbook["stage"], "combined workbook")

    def test_progress_reads_sanitized_workflow_failure_detail(self) -> None:
        progress = launcher.parse_progress_line(
            "WorkflowError [Audio analysis]: Audio analysis failed: model output is missing"
        )

        self.assertEqual(progress["failedStage"], "Audio analysis")
        self.assertEqual(progress["error"], "Audio analysis failed: model output is missing")
        self.assertEqual(progress["label"], "Audio analysis failed: model output is missing")

    def test_required_payload_text_rejects_blank_values(self) -> None:
        self.assertIsNone(launcher.required_payload_text({"sourcePath": "   "}, "sourcePath"))
        self.assertEqual(launcher.required_payload_text({"sourcePath": r"C:\videos"}, "sourcePath"), r"C:\videos")

    def test_required_payload_text_strips_wrapping_quotes_from_pasted_paths(self) -> None:
        self.assertEqual(
            launcher.required_payload_text({"sourcePath": '  "C:\\Users\\researcher\\Videos\\input.docx"  '}, "sourcePath"),
            r"C:\Users\researcher\Videos\input.docx",
        )

    def test_analysis_workflow_payload_requires_unique_valid_groups_and_modalities(self) -> None:
        payload = {
            "outputRoot": r"C:\reports",
            "writeCombinedWorkbook": True,
            "defaultReference": 0,
            "referenceOverrides": {"baseline": 1.5},
            "includeConstructComparison": True,
            "includeProbabilitySheets": True,
            "confidenceLevel": 0.95,
            "headlinePolicy": "weighted",
            "speakerGroups": [
                {"id": "group-1", "name": "Group 1", "speakerKeys": ["speaker_b", "speaker_a"]}
            ],
            "writeGraphs": True,
            "includeLogscale": False,
            "includeLandmarks": False,
            "includeTiming": False,
            "excludeGeometry": False,
            "modalities": [
                {"name": "audio", "sourceMethod": "run", "sourcePath": r"C:\audio"},
                {"name": "text", "sourceMethod": "import", "sourcePath": r"C:\text"},
            ],
        }

        request = launcher.analysis_workflow_request_from_payload(payload)

        self.assertEqual(request.modalities[0], backend.AnalysisModalityRunRequest("audio", "run", Path(r"C:\audio")))
        self.assertEqual(request.modalities[1], backend.AnalysisModalityRunRequest("text", "import", Path(r"C:\text")))
        self.assertEqual(request.speaker_groups[0].speaker_ids, ("speaker_b", "speaker_a"))
        self.assertEqual(request.reference_overrides, {"baseline": 1.5})
        self.assertTrue(request.include_construct_comparison)
        self.assertTrue(request.include_probability_sheets)
        self.assertEqual(request.confidence_level, 0.95)
        self.assertEqual(request.headline_policy, "weighted")

        invalid_payloads = (
            {**payload, "modalities": []},
            {**payload, "modalities": [{"name": "text", "sourceMethod": "run", "sourcePath": r"C:\text"}]},
            {**payload, "speakerGroups": [{"id": "group-1", "name": "Group 1", "speakerKeys": ["speaker_b"]}, {"id": "group-1", "name": "Group 2", "speakerKeys": ["speaker_a"]}]},
            {**payload, "speakerGroups": [{"id": "group-1", "name": "Group 1", "speakerKeys": ["speaker_b", "speaker_b"]}]},
            {**payload, "speakerGroups": [{"id": "group-1", "name": "Group 1", "speakerKeys": ["not-a-known-speaker"]}]},
            {**payload, "writeGraphs": "true"},
            {**payload, "confidenceLevel": 1.0},
            {**payload, "headlinePolicy": "mystery"},
            {**payload, "speakerGroups": [
                {"id": f"group-{index}", "name": f"Group {index}", "speakerKeys": [speaker]}
                for index, speaker in enumerate(
                    ("speaker_a", "speaker_b", "speaker_c", "speaker_d", "speaker_e"),
                    start=1,
                )
            ]},
        )
        for invalid_payload in invalid_payloads:
            with self.subTest(payload=invalid_payload), self.assertRaises(ValueError):
                launcher.analysis_workflow_request_from_payload(invalid_payload)

        with self.assertRaisesRegex(ValueError, "speaker group"):
            launcher.analysis_workflow_request_from_payload({**payload, "speakerGroups": []})

        analysis_only = launcher.analysis_workflow_request_from_payload(
            {**payload, "writeCombinedWorkbook": False, "speakerGroups": []}
        )
        self.assertFalse(analysis_only.write_combined_workbook)
        self.assertEqual(analysis_only.speaker_groups, ())

    def test_analysis_workflow_handler_starts_one_coordinator_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "audio"
            output = root / "reports"
            source.mkdir()
            payload = {
                "outputRoot": str(output),
                "writeCombinedWorkbook": True,
                "defaultReference": 0,
                "referenceOverrides": {},
                "includeConstructComparison": True,
                "includeProbabilitySheets": True,
                "confidenceLevel": 0.95,
                "headlinePolicy": "weighted",
                "speakerGroups": [
                    {"id": "group-1", "name": "Group 1", "speakerKeys": ["speaker_b"]}
                ],
                "writeGraphs": True,
                "includeLogscale": False,
                "includeLandmarks": False,
                "includeTiming": False,
                "excludeGeometry": False,
                "modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(source)}],
            }
            handler = object.__new__(launcher.VideoStackUiHandler)
            responses: list[dict[str, object]] = []
            handler.send_json = responses.append

            with patch.object(launcher, "start_process", return_value=37) as start_process, patch.object(launcher.APP_STATE, "log"):
                handler.handle_run_analysis_workflow(payload)

        start_process.assert_called_once()
        self.assertEqual(start_process.call_args.kwargs, {"mode": "analysis-workflow", "total": 0})
        self.assertTrue(responses[0]["started"])
        self.assertEqual(responses[0]["runId"], 37)

    def test_analysis_workflow_handler_rejects_existing_file_output_before_starting_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "audio"
            output = root / "reports.xlsx"
            source.mkdir()
            output.write_text("not a folder", encoding="utf-8")
            payload = {
                "outputRoot": str(output),
                "writeCombinedWorkbook": True,
                "defaultReference": 0,
                "referenceOverrides": {},
                "includeConstructComparison": True,
                "includeProbabilitySheets": True,
                "confidenceLevel": 0.95,
                "headlinePolicy": "weighted",
                "speakerGroups": [
                    {"id": "group-1", "name": "Group 1", "speakerKeys": ["speaker_b"]}
                ],
                "writeGraphs": True,
                "includeLogscale": False,
                "includeLandmarks": False,
                "includeTiming": False,
                "excludeGeometry": False,
                "modalities": [{"name": "audio", "sourceMethod": "run", "sourcePath": str(source)}],
            }
            handler = object.__new__(launcher.VideoStackUiHandler)
            handler.send_json = Mock()

            with patch.object(launcher, "start_process", return_value=37) as start_process, self.assertRaisesRegex(ValueError, "output must be a folder"):
                handler.handle_run_analysis_workflow(payload)

        start_process.assert_not_called()

    def test_launcher_token_accepts_header_or_query_only(self) -> None:
        self.assertTrue(launcher.launcher_token_is_valid("token", "", expected_token="token"))
        self.assertTrue(launcher.launcher_token_is_valid("", "token", expected_token="token"))
        self.assertFalse(launcher.launcher_token_is_valid("", "", expected_token="token"))
        self.assertFalse(launcher.launcher_token_is_valid("wrong", "", expected_token="token"))

    def test_allowed_media_paths_are_exact_resolved_paths(self) -> None:
        state = launcher.LauncherState()
        allowed = Path(r"C:\videos\clip.mp4")
        state.set_allowed_media_paths([allowed])

        self.assertTrue(state.is_allowed_media_path(allowed))
        self.assertFalse(state.is_allowed_media_path(Path(r"C:\videos\other.mp4")))

    def test_allowed_media_paths_are_case_insensitive_on_windows(self) -> None:
        state = launcher.LauncherState()
        state.set_allowed_media_paths([Path(r"C:\Videos\Clip.mp4")])

        self.assertTrue(state.is_allowed_media_path(Path(r"c:\videos\clip.mp4")))

    def test_focus_identity_rejects_blank_unknown_and_rewritten_docx_sources(self) -> None:
        state = launcher.LauncherState()
        catalog = Path(r"C:\research\source_catalog.docx")
        item = backend.VideoItem(
            id="docx:abcdefghijk:0:1",
            title="Interview",
            speaker="Speaker A",
            source_path=str(catalog),
            source_kind="docx",
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            video_id="abcdefghijk",
            duration_seconds=120,
        )
        state.set_allowed_media_items([item])

        valid = {
            "source_kind": "docx",
            "source_path": str(catalog),
            "youtube_url": item.youtube_url,
            "video_id": item.video_id,
        }
        self.assertTrue(state.is_allowed_segment_reference(valid))
        for invalid in (
            {**valid, "source_kind": ""},
            {**valid, "source_kind": "archive"},
            {**valid, "source_path": r"C:\research\other.docx"},
            {**valid, "source_path": r"C:\research\clip.mp4"},
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(state.is_allowed_segment_reference(invalid))
                self.assertIsNone(state.allowed_duration_for_segment(invalid))

    def test_focus_scan_retains_duration_for_bare_youtube_video_id(self) -> None:
        state = launcher.LauncherState()
        item = backend.VideoItem(
            id="youtube:abcdefghijk",
            title="Speech",
            speaker="YouTube",
            source_path="https://www.youtube.com/watch?v=abcdefghijk",
            source_kind="youtube",
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            video_id="abcdefghijk",
            duration_seconds=60,
        )
        segment = {
            "source_kind": "youtube",
            "source_path": item.source_path,
            "youtube_url": item.youtube_url,
            "video_id": item.video_id,
        }

        state.set_allowed_media_items([item])

        self.assertEqual(state.allowed_duration_for_segment(segment), 60.0)

    def test_http_byte_ranges_support_standard_open_and_suffix_forms(self) -> None:
        self.assertEqual(launcher.parse_http_byte_range("bytes=10-19", 100), (10, 19))
        self.assertEqual(launcher.parse_http_byte_range("bytes=90-", 100), (90, 99))
        self.assertEqual(launcher.parse_http_byte_range("bytes=-10", 100), (90, 99))
        self.assertEqual(launcher.parse_http_byte_range("bytes=-200", 100), (0, 99))

    def test_http_byte_ranges_reject_invalid_or_multiple_ranges(self) -> None:
        invalid_ranges = ["bytes=", "bytes=100-101", "bytes=20-10", "bytes=0-1,3-4", "items=0-1"]
        for value in invalid_ranges:
            with self.subTest(value=value), self.assertRaises(ValueError):
                launcher.parse_http_byte_range(value, 100)

    def test_focus_manifest_normalizes_lengths(self) -> None:
        normalized = launcher.validate_segment_manifest(
            {
                "max_segment_length_seconds": 30,
                "selected_segments": [
                    {
                        "source_kind": "file",
                        "source_path": r"C:\videos\clip.mp4",
                        "start_seconds": 1,
                        "end_seconds": 4.25,
                        "length_seconds": 999,
                    }
                ],
            }
        )

        self.assertEqual(normalized[0]["length_seconds"], 3.25)

    def test_focus_manifest_caps_segment_cardinality_before_iteration(self) -> None:
        segment = {
            "source_kind": "file",
            "source_path": r"C:\videos\clip.mp4",
            "start_seconds": 1,
            "end_seconds": 4.25,
        }
        with self.assertRaisesRegex(ValueError, "at most 10000"):
            launcher.validate_segment_manifest({"selected_segments": [segment] * 10001})

    def test_focus_manifest_has_no_maximum_segment_length(self) -> None:
        normalized = launcher.validate_segment_manifest(
            {
                "gap_seconds": 0.5,
                "selected_segments": [
                    {
                        "source_kind": "file",
                        "source_path": r"C:\videos\speech.mp4",
                        "start_seconds": 60,
                        "end_seconds": 3660,
                    }
                ],
            }
        )

        self.assertEqual(normalized[0]["length_seconds"], 3600.0)

    def test_focus_manifest_rejects_gap_above_sixty_seconds(self) -> None:
        with self.assertRaisesRegex(ValueError, "Focus gap"):
            launcher.validate_segment_manifest(
                {
                    "gap_seconds": 61,
                    "selected_segments": [
                        {
                            "source_kind": "file",
                            "source_path": r"C:\videos\speech.mp4",
                            "start_seconds": 0,
                            "end_seconds": 10,
                        }
                    ],
                }
            )

    def test_focus_manifest_rejects_overlapping_intervals(self) -> None:
        manifest = {
            "max_segment_length_seconds": 30,
            "selected_segments": [
                {
                    "source_kind": "file",
                    "source_path": r"C:\videos\clip.mp4",
                    "start_seconds": 1,
                    "end_seconds": 4,
                },
                {
                    "source_kind": "file",
                    "source_path": r"C:\videos\clip.mp4",
                    "start_seconds": 3,
                    "end_seconds": 6,
                },
            ],
        }

        with self.assertRaisesRegex(ValueError, "overlaps"):
            launcher.validate_segment_manifest(manifest)

    def test_focus_manifest_rejects_segments_for_unchecked_speakers(self) -> None:
        manifest = {
            "selected_segments": [
                {
                    "speaker": "Speaker F",
                    "source_kind": "file",
                    "source_path": r"C:\videos\clip.mp4",
                    "start_seconds": 0,
                    "end_seconds": 10,
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "unchecked speaker"):
            launcher.validate_segment_manifest(manifest, selected_speakers=["Speaker B"])

    def test_focus_source_comparison_accepts_equivalent_paths_and_youtube_urls(self) -> None:
        self.assertTrue(
            launcher.source_references_match(
                "https://youtu.be/abcdefghijk?t=30",
                "https://www.youtube.com/watch?v=abcdefghijk",
            )
        )
        self.assertTrue(launcher.source_references_match(r"C:\videos\..\videos\source.docx", r"C:\videos\source.docx"))
        self.assertFalse(launcher.source_references_match(r"C:\videos\one.docx", r"C:\videos\two.docx"))

    def test_direct_youtube_focus_command_accepts_launcher_materialized_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            output_root = root / "output"
            raw_source = "https://www.youtube.com/watch?v=abcdefghijk"
            item = backend.VideoItem(
                id="youtube:abcdefghijk",
                title="Speech",
                speaker="YouTube",
                source_path=raw_source,
                source_kind="youtube",
                youtube_url=raw_source,
                video_id="abcdefghijk",
                duration_seconds=60,
            )
            payload = {
                "sourcePath": raw_source,
                "outputRoot": str(output_root),
                "mode": "manual",
                "selectedSpeakers": ["YouTube"],
                "videoCount": 1,
                "segmentManifest": {
                    "source_path": raw_source,
                    "selected_segments": [
                        {
                            "speaker": "YouTube",
                            "source_kind": "youtube",
                            "source_path": raw_source,
                            "youtube_url": raw_source,
                            "video_id": "abcdefghijk",
                            "start_seconds": 0,
                            "end_seconds": 10,
                        }
                    ],
                },
            }
            state = launcher.LauncherState()
            state.set_allowed_media_items([item])
            handler = object.__new__(launcher.VideoStackUiHandler)
            responses: list[dict[str, object]] = []
            handler.send_json = responses.append

            with (
                patch.object(launcher, "REPO_ROOT", repo_root),
                patch.object(launcher, "APP_STATE", state),
                patch.object(launcher, "start_process", return_value=37),
            ):
                handler.handle_run(payload)

            command = responses[0]["command"]
            self.assertIsInstance(command, list)
            prepared_source = Path(command[command.index("--source") + 1])
            self.assertNotEqual(str(prepared_source), raw_source)
            observed: dict[str, object] = {}

            def process(source: Path, _run_folder: Path, manifest: dict[str, object]) -> dict[str, int]:
                observed["source"] = source
                observed["manifest_source"] = manifest.get("source_path")
                return {"processed": 1, "recorded_only": 0, "failed": 0}

            with (
                patch.object(sys, "argv", [str(command[2]), *command[3:]]),
                patch.object(manual_segments, "process_local_segments", side_effect=process),
            ):
                result = manual_segments.main()

        self.assertEqual(result, 0)
        self.assertEqual(observed["source"], prepared_source.resolve())
        self.assertEqual(observed["manifest_source"], raw_source)

    def test_external_docx_focus_command_accepts_launcher_cache_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            output_root = root / "output"
            raw_source = root / "external" / "source_catalog.docx"
            raw_source.parent.mkdir()
            document = Document()
            table = document.add_table(rows=2, cols=3)
            table.rows[0].cells[0].text = "Link"
            table.rows[0].cells[1].text = "Speaker"
            table.rows[0].cells[2].text = "Duration"
            table.rows[1].cells[0].text = "https://www.youtube.com/watch?v=abcdefghijk"
            table.rows[1].cells[1].text = "Speaker A"
            table.rows[1].cells[2].text = "00:01:00"
            document.save(raw_source)
            item = backend.VideoItem(
                id="docx:abcdefghijk:0:1",
                title="Speech",
                speaker="Speaker A",
                source_path=str(raw_source),
                source_kind="docx",
                youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
                video_id="abcdefghijk",
                duration_seconds=60,
            )
            payload = {
                "sourcePath": str(raw_source),
                "outputRoot": str(output_root),
                "mode": "manual",
                "selectedSpeakers": ["Speaker A"],
                "videoCount": 1,
                "segmentManifest": {
                    "source_path": str(raw_source),
                    "selected_segments": [
                        {
                            "speaker": "Speaker A",
                            "source_kind": "docx",
                            "source_path": str(raw_source),
                            "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
                            "video_id": "abcdefghijk",
                            "start_seconds": 0,
                            "end_seconds": 10,
                        }
                    ],
                },
            }
            state = launcher.LauncherState()
            state.set_allowed_media_items([item])
            handler = object.__new__(launcher.VideoStackUiHandler)
            responses: list[dict[str, object]] = []
            handler.send_json = responses.append

            with (
                patch.object(launcher, "REPO_ROOT", repo_root),
                patch.object(launcher, "APP_STATE", state),
                patch.object(launcher, "start_process", return_value=37),
            ):
                handler.handle_run(payload)

            command = responses[0]["command"]
            self.assertIsInstance(command, list)
            prepared_source = Path(command[command.index("--source") + 1])
            self.assertNotEqual(prepared_source.resolve(), raw_source.resolve())
            observed: dict[str, object] = {}

            def process(source: Path, _run_folder: Path, manifest: dict[str, object]) -> dict[str, int]:
                observed["source"] = source
                observed["manifest_source"] = manifest.get("source_path")
                return {"processed": 1, "recorded_only": 0, "failed": 0}

            with (
                patch.object(sys, "argv", [str(command[2]), *command[3:]]),
                patch.object(manual_segments, "process_local_segments", side_effect=process),
            ):
                result = manual_segments.main()

        self.assertEqual(result, 0)
        self.assertEqual(observed["source"], prepared_source.resolve())
        self.assertEqual(observed["manifest_source"], str(raw_source))

    def test_native_window_api_destroys_bound_window(self) -> None:
        window = Mock()
        api = launcher.NativeWindowApi()
        api.bind_window(window)

        self.assertTrue(api.close_window())
        window.destroy.assert_called_once_with()

    def test_native_window_api_supports_fullscreen_and_native_browse(self) -> None:
        window = Mock()
        window.create_file_dialog.return_value = (r"C:\videos",)
        api = launcher.NativeWindowApi()
        api.bind_window(window)

        self.assertTrue(api.toggle_fullscreen())
        self.assertEqual(
            api.browse_for_path("folder"),
            {"path": r"C:\videos", "cancelled": False},
        )
        window.toggle_fullscreen.assert_called_once_with()
        window.create_file_dialog.assert_called_once_with(dialog_type=20)
        self.assertFalse(hasattr(api, "window"))

    def test_native_window_api_uses_modern_file_dialog_for_source_files(self) -> None:
        window = Mock()
        window.create_file_dialog.return_value = (r"C:\videos\speaker-list.docx",)
        api = launcher.NativeWindowApi()
        api.bind_window(window)

        result = api.browse_for_path("source-file")

        self.assertEqual(
            result,
            {"path": r"C:\videos\speaker-list.docx", "cancelled": False},
        )
        window.create_file_dialog.assert_called_once_with(
            dialog_type=10,
            file_types=(
                "Supported sources (*.docx;*.mp4;*.mov;*.mkv;*.webm;*.avi)",
                "DOCX files (*.docx)",
                "Video files (*.mp4;*.mov;*.mkv;*.webm;*.avi)",
            ),
        )

    def test_native_window_defaults_are_resizable_maximized_and_not_aspect_locked(self) -> None:
        options = launcher.native_window_options()

        self.assertTrue(options["resizable"])
        self.assertTrue(options["maximized"])
        self.assertEqual(options["min_size"], (640, 480))
        self.assertNotIn("aspect_ratio", options)

    def test_launcher_http_workers_do_not_block_shutdown(self) -> None:
        self.assertTrue(launcher.LauncherHttpServer.daemon_threads)
        self.assertFalse(launcher.LauncherHttpServer.block_on_close)

    def test_native_webview_uses_persistent_profile_to_avoid_ui_thread_cleanup(self) -> None:
        options = launcher.native_webview_start_options()

        self.assertFalse(options["private_mode"])
        self.assertEqual(options["storage_path"], str(launcher.WEBVIEW_STORAGE_ROOT))

    def test_shutdown_request_prevents_new_process_reservations(self) -> None:
        state = launcher.LauncherState()
        state.request_shutdown()

        self.assertFalse(state.reserve_process(["python", "-V"], mode="test", total=1))

    def test_process_attached_during_shutdown_is_reported_for_termination(self) -> None:
        state = launcher.LauncherState()
        process = Mock()
        state.request_shutdown()

        self.assertTrue(state.attach_process(process))

    def test_child_credentials_are_scoped_to_the_command_that_needs_them(self) -> None:
        inherited = {
            "PATH": r"C:\Windows\System32",
            "YOUTUBE_API_KEY": "inherited-youtube",
            "HF_TOKEN": "inherited-hf",
            "HUGGINGFACE_TOKEN": "alias-hf",
        }
        with (
            patch.object(launcher.backend, "load_youtube_api_key", return_value="stored-youtube"),
            patch.object(launcher.backend, "load_huggingface_token", return_value="stored-hf"),
        ):
            manual = launcher.child_process_environment(
                ["python", "-m", "application.manual_segments"],
                base_environment=inherited,
            )
            pipeline = launcher.child_process_environment(
                ["python", "-m", "procurement.run_pipeline"],
                base_environment=inherited,
            )
            clean_speaker = launcher.child_process_environment(
                ["python", "-m", "procurement.procurement_beta.cli"],
                base_environment=inherited,
            )

        self.assertNotIn("YOUTUBE_API_KEY", manual)
        self.assertNotIn("HF_TOKEN", manual)
        self.assertEqual(pipeline["YOUTUBE_API_KEY"], "stored-youtube")
        self.assertNotIn("HF_TOKEN", pipeline)
        self.assertEqual(clean_speaker["HF_TOKEN"], "stored-hf")
        self.assertNotIn("YOUTUBE_API_KEY", clean_speaker)

    def test_stop_requested_while_starting_terminates_child_on_attach(self) -> None:
        state = launcher.LauncherState()
        run_id = state.reserve_process(["python", "-V"], mode="test", total=1)

        requested, attached_process = state.request_process_stop()
        should_terminate = state.attach_process(Mock(), run_id)

        self.assertTrue(requested)
        self.assertIsNone(attached_process)
        self.assertTrue(should_terminate)

    def test_stopped_process_is_finalized_once_even_if_reader_finishes_later(self) -> None:
        state = launcher.LauncherState()
        run_id = state.reserve_process(["python", "-V"], mode="test", total=1)
        process = Mock()
        process.poll.return_value = None
        state.attach_process(process, run_id)

        requested, attached_process = state.request_process_stop()
        first_finish = state.finish_process(-15, run_id)
        second_finish = state.finish_process(-15, run_id)

        self.assertTrue(requested)
        self.assertIs(attached_process, process)
        self.assertTrue(first_finish)
        self.assertFalse(second_finish)
        self.assertEqual(state.snapshot()["status"], "stopped")

    def test_exited_child_remains_logically_running_until_result_is_published(self) -> None:
        state = launcher.LauncherState()
        run_id = state.reserve_process(["python", "-V"], mode="test", total=1)
        process = Mock()
        process.poll.return_value = 0
        state.attach_process(process, run_id)

        pending_snapshot = state.snapshot()

        self.assertTrue(pending_snapshot["running"])
        self.assertEqual(pending_snapshot["status"], "running")
        self.assertIsNone(state.reserve_process(["python", "-V"], mode="test", total=1))

        self.assertTrue(state.finish_process(0, run_id))
        complete_snapshot = state.snapshot()
        self.assertFalse(complete_snapshot["running"])
        self.assertEqual(complete_snapshot["status"], "complete")

    def test_failed_workflow_keeps_stage_error_and_completed_outputs_in_state(self) -> None:
        state = launcher.LauncherState()
        run_id = state.reserve_process(["python", "-V"], mode="analysis-workflow", total=0)
        state.attach_process(Mock(), run_id)
        state.append_for_run("Completed Audio analysis: C:\\reports\\audio", run_id)
        state.append_for_run(
            "WorkflowError [combined workbook]: Unknown reference override: typo",
            run_id,
        )

        self.assertTrue(state.finish_process(1, run_id))

        snapshot = state.snapshot()
        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["progress"]["failedStage"], "combined workbook")
        self.assertEqual(snapshot["progress"]["error"], "Unknown reference override: typo")
        self.assertEqual(snapshot["progress"]["completedOutputs"], {"audio": r"C:\reports\audio"})
        self.assertEqual(snapshot["progress"]["label"], "Unknown reference override: typo")

    def test_snapshot_exposes_run_id_without_slow_configuration_by_default(self) -> None:
        state = launcher.LauncherState()
        run_id = state.reserve_process(["python", "-V"], mode="test", total=1)

        snapshot = state.snapshot()

        self.assertEqual(snapshot["runId"], run_id)
        self.assertNotIn("settings", snapshot)
        self.assertNotIn("access", snapshot)

    def test_validate_existing_path_requires_requested_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            file_path = folder / "video.mp4"
            file_path.write_bytes(b"video")

            self.assertEqual(launcher.validate_existing_path(folder, kind="folder"), folder.resolve())
            self.assertEqual(launcher.validate_existing_path(file_path, kind="file"), file_path.resolve())
            with self.assertRaisesRegex(ValueError, "must be a folder"):
                launcher.validate_existing_path(file_path, kind="folder")

    def test_progress_reads_focus_stitch_line(self) -> None:
        progress = launcher.parse_progress_line("Focus stitched output: C:\\outputs\\stitched_imotions.mp4")

        self.assertEqual(progress["label"], "Focus segments stitched")

    def test_cpu_affinity_converts_percent_to_core_count(self) -> None:
        self.assertEqual(launcher.cpu_affinity_indices(16, 50), list(range(8)))
        self.assertEqual(launcher.cpu_affinity_indices(16, 100), list(range(16)))
        self.assertEqual(launcher.cpu_affinity_indices(1, 10), [0])
        self.assertEqual(launcher.cpu_affinity_indices(16, 90, 4), list(range(4)))

    def test_payload_parsers_preserve_zero_and_reject_ambiguous_values(self) -> None:
        payload = {"gap": 0, "count": "0", "enabled": "false"}

        self.assertEqual(launcher.payload_float(payload, "gap", 0.5), 0.0)
        self.assertEqual(launcher.payload_int(payload, "count", 2), 0)
        self.assertFalse(launcher.payload_bool(payload, "enabled", True))
        with self.assertRaisesRegex(ValueError, "whole number"):
            launcher.payload_int({"count": 1.5}, "count", 2)
        with self.assertRaisesRegex(ValueError, "true or false"):
            launcher.payload_bool({"enabled": "definitely"}, "enabled", True)

    def test_resource_resume_threshold_includes_cpu_hysteresis(self) -> None:
        settings = {
            "ramLimitMode": "percent",
            "maxRamPercent": 90,
            "maxCpuPercent": 80,
            "maxGpuPercent": 90,
        }

        self.assertFalse(
            launcher.resource_levels_are_below_resume_threshold(
                settings,
                system_ram_percent=50,
                process_tree_rss_bytes=1,
                cpu_percent=78,
                gpu_percent=50,
            )
        )
        self.assertTrue(
            launcher.resource_levels_are_below_resume_threshold(
                settings,
                system_ram_percent=50,
                process_tree_rss_bytes=1,
                cpu_percent=70,
                gpu_percent=50,
            )
        )

    def test_ram_limit_supports_system_percent_and_pipeline_gigabytes(self) -> None:
        percent_high, _ = launcher.ram_limit_status(
            {"ramLimitMode": "percent", "maxRamPercent": 90},
            system_used_percent=91,
            process_tree_rss_bytes=1,
        )
        gb_high, _ = launcher.ram_limit_status(
            {"ramLimitMode": "gb", "maxRamGb": 4},
            system_used_percent=1,
            process_tree_rss_bytes=5 * 1024 ** 3,
        )

        self.assertTrue(percent_high)
        self.assertTrue(gb_high)

    def test_ensure_eula_accepted_writes_true_after_prompt_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)

            accepted = launcher.ensure_eula_accepted(repo_root, prompt_acceptance=lambda _path: True)
            eula_text = backend.eula_path(repo_root).read_text(encoding="utf-8")

        self.assertTrue(accepted)
        self.assertIn("terms_accepted=true", eula_text)
        self.assertIn("# data: accepted_at=", eula_text)

    def test_ensure_eula_accepted_keeps_false_after_prompt_decline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)

            accepted = launcher.ensure_eula_accepted(repo_root, prompt_acceptance=lambda _path: False)
            eula_text = backend.eula_path(repo_root).read_text(encoding="utf-8")

        self.assertFalse(accepted)
        self.assertIn("terms_accepted=false", eula_text)

    def test_ensure_eula_accepted_skips_prompt_when_already_true(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            backend.write_eula_state(repo_root, True, accepted_at="2026-06-23T12:00:00Z")

            accepted = launcher.ensure_eula_accepted(
                repo_root,
                prompt_acceptance=lambda _path: self.fail("Prompt should not be shown when EULA is accepted."),
            )

        self.assertTrue(accepted)


if __name__ == "__main__":
    unittest.main()
