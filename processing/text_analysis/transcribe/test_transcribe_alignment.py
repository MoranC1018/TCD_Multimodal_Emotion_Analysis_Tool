from __future__ import annotations

import unittest
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from processing.text_analysis.contracts import file_sha256, source_fingerprint
from processing.io_utils import exclusive_process_lock
from processing.text_analysis.transcribe.provenance import build_output_provenance

from processing.text_analysis.transcribe.transcribe import (
    _align_segments,
    _build_transcription_jobs,
    _build_bilingual_outputs,
    _output_paths,
    _saved_pass_is_reusable,
    _write_json_set,
    collect_from_procurement,
    transcribe_bilingual_to_paths,
    transcription_artifact_set_is_reusable,
    main as transcribe_main,
)


def segment(start: float, end: float, text: str) -> dict[str, object]:
    return {"start": start, "end": end, "text": text}


def fake_provenance(task: str) -> dict[str, dict[str, object]]:
    execution = {
        "engine": {"distribution": "openai-whisper", "version": "test"},
        "checkpoint": {
            "requested_name": "small",
            "filename": "small.pt",
            "expected_sha256": "a" * 64,
            "hash_source": "openai_whisper_model_registry",
        },
        "runtime": {"torch_version": "test", "ffmpeg_version": "test"},
    }
    return build_output_provenance(
        execution,
        requested_task=task,
        device="cpu",
        requested_language=None,
    )


class BilingualAlignmentTests(unittest.TestCase):
    def test_alignment_failure_preserves_both_expensive_passes(self) -> None:
        class FakeModel:
            calls = []

            def transcribe(self, _path, *, task, **_kwargs):
                self.calls.append((task, _kwargs))
                if task == "transcribe":
                    return {"language": "fr", "segments": [{"id": 0, **segment(0, 5, "Original")}]}
                return {"language": "fr", "segments": [{"id": 0, **segment(10, 15, "English")}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {kind: root / kind / "video.json" for kind in ("original", "eng", "bilingual")}

            with self.assertRaisesRegex(ValueError, "No English time overlap"):
                transcribe_bilingual_to_paths(
                    Path("video.mp4"),
                    FakeModel(),
                    "cpu",
                    paths,
                    model_name="small",
                    provenance_by_kind=fake_provenance("bilingual"),
                )

            self.assertTrue(paths["original"].is_file())
            self.assertTrue(paths["eng"].is_file())
            self.assertFalse(paths["bilingual"].exists())

    def test_saved_passes_can_retry_alignment_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "video.mp4"
            video.write_bytes(b"media")
            paths = {kind: root / kind / "video.json" for kind in ("original", "eng", "bilingual")}
            provenance = {
                "schema_version": "2.0",
                "source": str(video.resolve()),
                "source_fingerprint": source_fingerprint(video),
                "source_sha256": file_sha256(video),
                "model": "small",
            }
            provenance_by_kind = fake_provenance("bilingual")
            original = {
                **provenance, "language": "fr", "task": "transcribe",
                "whisper_provenance": provenance_by_kind["original"],
                "segments": [{"id": 0, **segment(0, 5, "Original")}],
            }
            english = {
                **provenance, "language": "en", "task": "translate",
                "whisper_provenance": provenance_by_kind["eng"],
                "segments": [{"id": 0, **segment(0, 5, "English")}],
            }
            _write_json_set(
                {"original": original, "eng": english},
                {"original": paths["original"], "eng": paths["eng"]},
            )

            outputs = transcribe_bilingual_to_paths(
                video, None, "cpu", paths,
                model_name="small", reuse_existing=True,
                provenance_by_kind=provenance_by_kind,
            )

            self.assertTrue(paths["bilingual"].is_file())
            self.assertEqual(outputs["bilingual"]["segments"][0]["text_en"], "English")

    def test_procurement_identity_uses_real_speaker_video_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads = Path(temp_dir)
            video_dir = downloads / "Test Speaker" / "YouTubeti_[abc123]"
            video_dir.mkdir(parents=True)
            video = video_dir / "stitched_imotions.mp4"
            video.write_bytes(b"")

            pairs = collect_from_procurement(downloads)

            self.assertEqual(pairs, [(video, Path("Test Speaker/YouTubeti_[abc123]"))])

    def test_procurement_identity_does_not_infer_country_from_video_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads = Path(temp_dir)
            video_dir = downloads / "Different Person" / "001_Atlantis_Test_Speaker_20250101"
            video_dir.mkdir(parents=True)
            video = video_dir / "stitched_imotions.mp4"
            video.write_bytes(b"")

            self.assertEqual(
                collect_from_procurement(downloads),
                [(video, Path("Different Person/001_Atlantis_Test_Speaker_20250101"))],
            )

    def test_procurement_full_video_strips_transport_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads = Path(temp_dir)
            video_dir = downloads / "Test Speaker" / "YouTubeti_[abc123]_full_video"
            video_dir.mkdir(parents=True)
            video = video_dir / "Full title_[abc123].mkv"
            video.write_bytes(b"")

            self.assertEqual(
                collect_from_procurement(downloads),
                [(video, Path("Test Speaker/YouTubeti_[abc123]"))],
            )

    def test_equal_counts_still_use_time_overlap(self) -> None:
        original = [segment(0, 10, "O1"), segment(10, 20, "O2")]
        english = [segment(0, 6, "E1"), segment(6, 20, "E2")]

        aligned = _align_segments(original, english)

        self.assertEqual([row["text_en"] for row in aligned], ["E1", "E2"])
        self.assertGreater(aligned[1]["alignment_overlap_ratio"], 0.7)

    def test_one_original_to_many_english_merges_without_duplication(self) -> None:
        original = [segment(0, 10, "Original")]
        english = [segment(0, 4, "English one"), segment(4, 10, "English two")]

        aligned = _align_segments(original, english)

        self.assertEqual(len(aligned), 1)
        self.assertEqual(aligned[0]["text_en"], "English one English two")
        self.assertEqual(aligned[0]["alignment_en_segments"], 2)

    def test_many_original_to_one_english_merges_without_duplication(self) -> None:
        original = [segment(0, 4, "Original one"), segment(4, 10, "Original two")]
        english = [segment(0, 10, "English")]

        aligned = _align_segments(original, english)

        self.assertEqual(len(aligned), 1)
        self.assertEqual(aligned[0]["text_original"], "Original one Original two")
        self.assertEqual(aligned[0]["alignment_original_segments"], 2)

    def test_no_time_overlap_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "No English time overlap"):
            _align_segments(
                [segment(0, 5, "Original")],
                [segment(10, 15, "English")],
            )

    def test_low_overlap_quality_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Low bilingual alignment overlap"):
            _align_segments(
                [segment(0, 10, "Original")],
                [segment(9, 19, "English")],
            )

    def test_empty_pass_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no segments"):
            _align_segments([], [segment(0, 5, "English")])

    def test_bilingual_build_keeps_independent_passes_and_complete_audit(self) -> None:
        original = {"segments": [segment(0, 4, "O1"), segment(4, 10, "O2")]}
        english = {"segments": [segment(0, 10, "E1")]}

        outputs = _build_bilingual_outputs(Path("video.mp4"), "cpu", "fr", original, english)

        self.assertEqual(set(outputs), {"original", "eng", "bilingual"})
        self.assertEqual([row["text"] for row in outputs["original"]["segments"]], ["O1", "O2"])
        self.assertEqual([row["text"] for row in outputs["eng"]["segments"]], ["E1"])
        audit = outputs["bilingual"]["bilingual_alignment"]
        self.assertTrue(audit["original_segments_used_once"])
        self.assertTrue(audit["english_segments_used_once"])
        self.assertEqual(outputs["bilingual"]["segments"][0]["source_original_segment_ids"], [0, 1])
        self.assertEqual(outputs["bilingual"]["segments"][0]["source_en_segment_ids"], [0])
        self.assertEqual(outputs["bilingual"]["segments"][0]["source_original_segment_indexes"], [0, 1])

    def test_duplicate_whisper_ids_are_rejected(self) -> None:
        original = {"segments": [
            {"id": 7, **segment(0, 4, "O1")},
            {"id": 7, **segment(4, 10, "O2")},
        ]}
        english = {"segments": [{"id": 0, **segment(0, 10, "E1")}]}

        with self.assertRaisesRegex(ValueError, "duplicate segment IDs"):
            _build_bilingual_outputs(Path("video.mp4"), "cpu", "fr", original, english)

    def test_bilingual_outputs_use_separate_roots_without_changing_video_name(self) -> None:
        relative = Path("France") / "Speaker" / "001_France_Speaker_20250101.json"
        paths = _output_paths(Path("output"), relative, "bilingual")

        self.assertEqual(paths["original"], Path("output") / "original" / relative)
        self.assertEqual(paths["eng"], Path("output") / "eng" / relative)
        self.assertEqual(paths["bilingual"], Path("output") / "bilingual" / relative)

    def test_complete_json_set_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = {kind: root / kind / "video.json" for kind in ("original", "eng", "bilingual")}
            outputs = {kind: {"kind": kind, "segments": []} for kind in paths}

            _write_json_set(outputs, paths)

            self.assertEqual(
                {kind: json.loads(path.read_text(encoding="utf-8"))["kind"] for kind, path in paths.items()},
                {"original": "original", "eng": "eng", "bilingual": "bilingual"},
            )

    def test_saved_pass_reuse_checks_model_and_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "video.mp4"
            video.write_bytes(b"first")
            stat = video.stat()
            saved = root / "saved.json"
            saved.write_text(
                json.dumps(
                    {
                        "source": str(video),
                        "schema_version": "2.0",
                        "task": "transcribe",
                        "model": "small",
                        "source_fingerprint": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
                        "source_sha256": file_sha256(video),
                        "whisper_provenance": fake_provenance("transcribe")["transcribe"],
                        "segments": [{"id": 0, **segment(0, 1, "text")}],
                    }
                ),
                encoding="utf-8",
            )

            expected = fake_provenance("transcribe")["transcribe"]
            self.assertTrue(
                _saved_pass_is_reusable(
                    saved, "transcribe", "small", video, expected_provenance=expected
                )
            )
            self.assertFalse(_saved_pass_is_reusable(saved, "transcribe", "large-v3", video))
            original_stat = video.stat()
            video.write_bytes(b"other")
            os.utime(video, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            self.assertFalse(_saved_pass_is_reusable(saved, "transcribe", "small", video))

    def test_legacy_reuse_is_opt_in_and_empty_text_is_a_valid_v2_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "video.mp4"
            video.write_bytes(b"media")
            legacy = root / "legacy.json"
            legacy.write_text(
                json.dumps(
                    {
                        "source": str(video),
                        "task": "transcribe",
                        "model": "small",
                        "source_fingerprint": source_fingerprint(video),
                        "segments": [{"id": 0, **segment(0, 1, "text")}],
                    }
                ),
                encoding="utf-8",
            )
            self.assertFalse(_saved_pass_is_reusable(legacy, "transcribe", "small", video))
            self.assertTrue(
                _saved_pass_is_reusable(
                    legacy, "transcribe", "small", video, trust_legacy=True
                )
            )

            current = root / "current.json"
            current.write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "source": str(video.resolve()),
                        "task": "transcribe",
                        "model": "small",
                        "source_fingerprint": source_fingerprint(video),
                        "source_sha256": file_sha256(video),
                        "whisper_provenance": fake_provenance("transcribe")["transcribe"],
                        "segments": [{"id": 0, **segment(0, 1, "")}],
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                _saved_pass_is_reusable(
                    current,
                    "transcribe",
                    "small",
                    video,
                    expected_provenance=fake_provenance("transcribe")["transcribe"],
                )
            )

    def test_single_canonical_filename_derives_canonical_output_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "001_UK_Test_Speaker_20250101.mp4"
            video.write_bytes(b"media")

            invocation, source_root, jobs = _build_transcription_jobs(
                input_value=str(video), procurement_run=None, canonical_layout=True
            )

            self.assertEqual(invocation, video.resolve())
            self.assertEqual(source_root, video.parent.resolve())
            self.assertEqual(jobs[0].identity, "UK/Test Speaker/001_UK_Test_Speaker_20250101")
            self.assertEqual(jobs[0].source_relative, video.name)

    def test_parent_layout_accepts_arbitrary_recursive_media_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "custom"
            video = root / "run-with-timestamp" / "Research_Speaker" / "interview_stitched.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"media")

            invocation, source_root, jobs = _build_transcription_jobs(
                input_value=str(root),
                procurement_run=None,
                canonical_layout=False,
                speaker_parent_layout=True,
            )

            self.assertEqual(invocation, root.resolve())
            self.assertEqual(source_root, root.resolve())
            self.assertEqual(jobs[0].identity, "Research_Speaker/interview_stitched")
            self.assertEqual(
                jobs[0].source_relative,
                "run-with-timestamp/Research_Speaker/interview_stitched.mp4",
            )

    def test_parent_layout_rejects_two_media_mapping_to_same_speaker_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "custom"
            first = root / "run-one" / "Speaker" / "same.mp4"
            second = root / "run-two" / "Speaker" / "same.wav"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"video")
            second.write_bytes(b"audio")

            with self.assertRaisesRegex(ValueError, "Multiple media files map to the same transcript"):
                _build_transcription_jobs(
                    input_value=str(root),
                    procurement_run=None,
                    canonical_layout=False,
                    speaker_parent_layout=True,
                )

    def test_partial_transcription_failure_returns_nonzero_structured_manifest(self) -> None:
        class FakeModel:
            dims = SimpleNamespace(n_audio_ctx=1)

            def transcribe(self, path, **_kwargs):
                if "002_" in Path(path).name:
                    raise RuntimeError("simulated transcription failure")
                return {
                    "language": "en",
                    "segments": [{"id": 0, **segment(0, 1, "hello")}],
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "media"
            media.mkdir()
            first = media / "001_UK_Test_Speaker_20250101.mp4"
            second = media / "002_UK_Test_Speaker_20250102.mp4"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            output = root / "output"
            manifest = root / "transcription_manifest.json"

            with patch(
                "processing.text_analysis.transcribe.transcribe.configure_ffmpeg_shared_libraries"
            ), patch(
                "processing.text_analysis.transcribe.transcribe._load_whisper_model",
                return_value=FakeModel(),
            ), patch(
                "processing.text_analysis.transcribe.transcribe.collect_whisper_execution_identity",
                return_value={
                    "engine": {"distribution": "openai-whisper", "version": "test"},
                    "checkpoint": {
                        "requested_name": "tiny",
                        "filename": "tiny.pt",
                        "expected_sha256": "a" * 64,
                        "hash_source": "openai_whisper_model_registry",
                    },
                    "runtime": {"torch_version": "test", "ffmpeg_version": "test"},
                },
            ):
                return_code = transcribe_main(
                    [
                        str(media), "--task", "transcribe", "--model", "tiny",
                        "--output-dir", str(output), "--canonical-layout",
                        "--batch-manifest", str(manifest),
                    ]
                )

            self.assertEqual(return_code, 1)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["summary"]["completed"], 1)
            self.assertEqual(payload["summary"]["failed"], 1)
            completed = next(row for row in payload["videos"] if row["status"] == "completed")
            failed = next(row for row in payload["videos"] if row["status"] == "failed")
            self.assertEqual(completed["source_relative"], first.name)
            self.assertEqual(failed["source_relative"], second.name)
            self.assertEqual(len(completed["source_sha256"]), 64)
            self.assertEqual(len(completed["artifacts"]["transcribe"]["sha256"]), 64)

    def test_bilingual_reuse_requires_all_companions_to_match_batch_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "video.mp4"
            video.write_bytes(b"media")
            source_hash = file_sha256(video)
            provenance = fake_provenance("bilingual")
            paths = {
                kind: root / kind / "video.json"
                for kind in ("original", "eng", "bilingual")
            }
            common = {
                "schema_version": "2.0",
                "source": str(video.resolve()),
                "source_sha256": source_hash,
                "model": "small",
            }
            outputs = {
                "original": {
                    **common,
                    "task": "transcribe",
                    "whisper_provenance": provenance["original"],
                    "segments": [{"id": 0, **segment(0, 1, "original")}],
                },
                "eng": {
                    **common,
                    "task": "translate",
                    "whisper_provenance": provenance["eng"],
                    "segments": [{"id": 0, **segment(0, 1, "english")}],
                },
                "bilingual": {
                    **common,
                    "task": "bilingual",
                    "whisper_provenance": provenance["bilingual"],
                    "segments": [
                        {
                            "id": 0,
                            "start": 0,
                            "end": 1,
                            "text_original": "original",
                            "text_en": "english",
                        }
                    ],
                },
            }
            _write_json_set(outputs, paths)

            self.assertTrue(
                transcription_artifact_set_is_reusable(
                    paths,
                    model_name="small",
                    video_path=video,
                    provenance_by_kind=provenance,
                    source_sha256_value=source_hash,
                )
            )
            tampered = json.loads(paths["eng"].read_text(encoding="utf-8"))
            tampered["model"] = "large-v3"
            paths["eng"].write_text(json.dumps(tampered), encoding="utf-8")
            self.assertFalse(
                transcription_artifact_set_is_reusable(
                    paths,
                    model_name="small",
                    video_path=video,
                    provenance_by_kind=provenance,
                    source_sha256_value=source_hash,
                )
            )

    def test_standalone_transcribe_lock_blocks_a_second_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output"
            lock = output.parent / f".{output.name}.transcribe.lock"
            with exclusive_process_lock(lock, purpose="test transcription writer"):
                with self.assertRaisesRegex(RuntimeError, "Another process"):
                    transcribe_main(["missing.mp4", "--output-dir", str(output)])

    def test_keyboard_interrupt_marks_transcription_manifest_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "001_UK_Test_Speaker_20250101.mp4"
            video.write_bytes(b"media")
            output = root / "output"
            manifest = root / "manifest.json"
            execution = {
                "engine": {"distribution": "openai-whisper", "version": "test"},
                "checkpoint": {
                    "requested_name": "small",
                    "filename": "small.pt",
                    "expected_sha256": "a" * 64,
                    "hash_source": "openai_whisper_model_registry",
                },
                "runtime": {"torch_version": "test", "ffmpeg_version": "test"},
            }
            with patch(
                "processing.text_analysis.transcribe.transcribe.configure_ffmpeg_shared_libraries"
            ), patch(
                "processing.text_analysis.transcribe.transcribe.collect_whisper_execution_identity",
                return_value=execution,
            ), patch(
                "processing.text_analysis.transcribe.transcribe._load_whisper_model",
                side_effect=KeyboardInterrupt,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    transcribe_main(
                        [
                            str(video),
                            "--model",
                            "small",
                            "--output-dir",
                            str(output),
                            "--batch-manifest",
                            str(manifest),
                        ]
                    )

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "interrupted")
            self.assertFalse((output.parent / f".{output.name}.transcribe.lock").exists())


if __name__ == "__main__":
    unittest.main()
