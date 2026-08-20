import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_pipeline.full_stack import (
    export_batch_to_analysis_audio_outputs,
    find_project_root,
    safe_folder_name,
    write_manifest,
)


def catalog_entry_and_context(
    root: Path,
    *,
    source_id: str,
    speaker: str,
    metadata: dict[str, str],
) -> tuple[dict[str, object], dict[str, object]]:
    procurement_root = root / "procurement_run"
    mapped_directory = procurement_root / source_id
    entry: dict[str, object] = {
        "source_id": source_id,
        "selected": True,
        "speaker": speaker,
        "speaker_display": speaker or "Pooled (no speaker)",
        "source_kind": "local",
        "resolved_link": str((root / f"{source_id}.mp4").resolve()),
        "user_metadata": metadata,
        "system_metadata": {"title": "Source"},
        "output_mapping": {"video_directory": str(mapped_directory.resolve())},
        "local_identity": {
            "canonical_path": str((root / f"{source_id}.mp4").resolve()),
            "sha256": "b" * 64,
            "size_bytes": 1,
        },
    }
    context = {
        **{key: entry[key] for key in (
            "source_id",
            "speaker",
            "speaker_display",
            "source_kind",
            "resolved_link",
            "user_metadata",
            "system_metadata",
            "output_mapping",
            "local_identity",
        )},
        "run_root": str(procurement_root.resolve()),
        "catalog_sha256": "a" * 64,
    }
    return entry, context


class FullStackExportTests(unittest.TestCase):
    def test_full_stack_manifest_neutralizes_user_controlled_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.csv"
            write_manifest(
                path,
                [
                    {
                        "relative_path": "@speaker/video",
                        "source_audio_analysis_csv": "=source.csv",
                        "analysis_audio_analysis_csv": "+output.csv",
                        "analysis_audio_manifest_json": "-manifest.json",
                    }
                ],
            )
            with path.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["relative_path"], "'@speaker/video")
        self.assertEqual(row["source_audio_analysis_csv"], "'=source.csv")
        self.assertEqual(row["analysis_audio_analysis_csv"], "'+output.csv")
        self.assertEqual(row["analysis_audio_manifest_json"], "'-manifest.json")

    def test_exports_audio_analysis_csvs_to_analysis_audio_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "project"
            audio_output = root / "audio_output"
            source_csv = audio_output / "Speaker_A" / "Video_One" / "audio_analysis.csv"
            source_csv.parent.mkdir(parents=True)
            source_csv.write_text("WindowIndex,Neutral\n1,0.8\n", encoding="utf-8")
            source_manifest = source_csv.parent / "audio_analysis_manifest.json"
            source_manifest.write_text('{"model":"test","source_id":"source-0007"}', encoding="utf-8")
            source_context = source_csv.parent / "source_context.json"
            entry, context = catalog_entry_and_context(
                root,
                source_id="source-0007",
                speaker="Speaker A",
                metadata={"Country": "Ireland"},
            )
            source_context.write_text(json.dumps(context), encoding="utf-8")
            top_manifest = (
                json.dumps({"format_version": 1, "catalog": {"sha256": "a" * 64}, "sources": [entry]})
                + "\n"
            ).encode("utf-8")
            top_metadata = b"\xef\xbb\xbfSourceID\r\nsource-0007\r\n"
            (audio_output / "source_manifest.json").write_bytes(top_manifest)
            (audio_output / "source_metadata.csv").write_bytes(top_metadata)

            real_copy2 = __import__("shutil").copy2

            def copy_only_noncontrols(source, destination):
                if Path(source).suffix == ".json":
                    raise AssertionError("validated control snapshots must not be reopened through copy2")
                return real_copy2(source, destination)

            with patch("audio_pipeline.full_stack.shutil.copy2", side_effect=copy_only_noncontrols):
                exported_root = export_batch_to_analysis_audio_outputs(
                    audio_output,
                    repo_root=repo_root,
                    run_name="Run_One",
                )

            copied_csv = exported_root / "Speaker_A" / "Video_One" / "audio_analysis.csv"
            copied_manifest = exported_root / "Speaker_A" / "Video_One" / "audio_analysis_manifest.json"
            copied_context = exported_root / "Speaker_A" / "Video_One" / "source_context.json"
            manifest = exported_root / "audio_outputs_manifest.csv"
            self.assertEqual(exported_root, repo_root / "analysis" / "audio_outputs" / "Run_One")
            self.assertEqual(copied_csv.read_text(encoding="utf-8"), "WindowIndex,Neutral\n1,0.8\n")
            self.assertEqual(copied_manifest.read_text(encoding="utf-8"), '{"model":"test","source_id":"source-0007"}')
            self.assertEqual(json.loads(copied_context.read_text(encoding="utf-8"))["source_id"], "source-0007")
            self.assertEqual((exported_root / "source_manifest.json").read_bytes(), top_manifest)
            self.assertEqual((exported_root / "source_metadata.csv").read_bytes(), top_metadata)
            self.assertTrue(manifest.exists())
            with manifest.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["source_id"], "source-0007")
            self.assertEqual(row["source_speaker"], "Speaker A")
            self.assertEqual(json.loads(row["source_metadata"]), {"Country": "Ireland"})

    def test_export_clears_stale_audio_outputs_for_same_run_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "project"
            stale_csv = repo_root / "analysis" / "audio_outputs" / "Run_One" / "Old_Speaker" / "Old_Video" / "audio_analysis.csv"
            stale_csv.parent.mkdir(parents=True)
            stale_csv.write_text("stale", encoding="utf-8")

            audio_output = root / "audio_output"
            source_csv = audio_output / "Speaker_A" / "Video_One" / "audio_analysis.csv"
            source_csv.parent.mkdir(parents=True)
            source_csv.write_text("WindowIndex,Neutral\n1,0.8\n", encoding="utf-8")

            exported_root = export_batch_to_analysis_audio_outputs(
                audio_output,
                repo_root=repo_root,
                run_name="Run_One",
            )

            self.assertFalse(stale_csv.exists())
            self.assertTrue((exported_root / "Speaker_A" / "Video_One" / "audio_analysis.csv").exists())

    def test_conflicting_reused_destination_sidecars_fail_before_any_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "project"
            audio_output = root / "audio_output"
            audio_output.mkdir()
            (audio_output / "source_manifest.json").write_bytes(b'{"catalog":{},"sources":[]}\n')
            (audio_output / "source_metadata.csv").write_bytes(b"SourceID\r\n")
            destination = repo_root / "analysis" / "audio_outputs" / "Run_One"
            stale = destination / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("keep", encoding="utf-8")
            conflicting_manifest = b'{"sources":[{"source_id":"other"}]}\n'
            (destination / "source_manifest.json").write_bytes(conflicting_manifest)
            (destination / "source_metadata.csv").write_bytes(b"SourceID\r\nother\r\n")

            with self.assertRaises(FileExistsError):
                export_batch_to_analysis_audio_outputs(
                    audio_output,
                    repo_root=repo_root,
                    run_name="Run_One",
                )

            self.assertEqual((destination / "source_manifest.json").read_bytes(), conflicting_manifest)
            self.assertEqual(stale.read_text(encoding="utf-8"), "keep")

    def test_full_stack_accepts_source_context_over_legacy_one_mib_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "project"
            audio_output = root / "audio_output"
            source_csv = audio_output / "source-0001" / "audio_analysis.csv"
            source_csv.parent.mkdir(parents=True)
            source_csv.write_text("WindowIndex\n1\n", encoding="utf-8")
            notes = "x" * (1024 * 1024 + 32)
            entry, context = catalog_entry_and_context(
                root,
                source_id="source-0001",
                speaker="",
                metadata={"Notes": notes},
            )
            (source_csv.parent / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
            (audio_output / "source_manifest.json").write_text(
                json.dumps({"catalog": {"sha256": "a" * 64}, "sources": [entry]}),
                encoding="utf-8",
            )
            (audio_output / "source_metadata.csv").write_text("SourceID\nsource-0001\n", encoding="utf-8")

            exported = export_batch_to_analysis_audio_outputs(
                audio_output,
                repo_root=repo_root,
                run_name="large-context",
            )

            copied = json.loads((exported / "source-0001" / "source_context.json").read_text(encoding="utf-8"))
            self.assertEqual(copied["user_metadata"]["Notes"], notes)

    def test_full_stack_rejects_tampered_catalog_context_before_cleaning_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "project"
            audio_output = root / "audio_output"
            source_root = audio_output / "source-0001"
            source_root.mkdir(parents=True)
            (source_root / "audio_analysis.csv").write_text("WindowIndex\n1\n", encoding="utf-8")
            procurement_root = root / "procurement_run"
            mapped_directory = procurement_root / "source-0001"
            mapped_directory.mkdir(parents=True)
            entry = {
                "source_id": "source-0001",
                "selected": True,
                "speaker": "",
                "speaker_display": "Pooled (no speaker)",
                "source_kind": "local",
                "resolved_link": str((root / "source.mp4").resolve()),
                "user_metadata": {"Country": "Ireland"},
                "system_metadata": {"title": "Source"},
                "output_mapping": {"video_directory": str(mapped_directory.resolve())},
                "local_identity": {
                    "canonical_path": str((root / "source.mp4").resolve()),
                    "sha256": "b" * 64,
                    "size_bytes": 1,
                },
            }
            (audio_output / "source_manifest.json").write_text(
                json.dumps({"catalog": {"sha256": "a" * 64}, "sources": [entry]}),
                encoding="utf-8",
            )
            (audio_output / "source_metadata.csv").write_text("SourceID\nsource-0001\n", encoding="utf-8")
            context = {
                **{key: entry[key] for key in (
                    "source_id",
                    "speaker",
                    "speaker_display",
                    "source_kind",
                    "resolved_link",
                    "user_metadata",
                    "system_metadata",
                    "output_mapping",
                    "local_identity",
                )},
                "run_root": str(procurement_root.resolve()),
                "catalog_sha256": "a" * 64,
            }
            context["user_metadata"] = {"Country": "Tampered"}
            (source_root / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
            destination = repo_root / "analysis" / "audio_outputs" / "Run_One"
            stale = destination / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "metadata does not match"):
                export_batch_to_analysis_audio_outputs(audio_output, repo_root=repo_root, run_name="Run_One")

            self.assertEqual(stale.read_text(encoding="utf-8"), "keep")
            self.assertFalse((destination / "source_manifest.json").exists())

    def test_full_stack_rejects_missing_or_duplicate_catalog_context_before_cleanup(self):
        for case in ("missing", "duplicate"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                repo_root = root / "project"
                audio_output = root / "audio_output"
                first = audio_output / "first" / "audio_analysis.csv"
                first.parent.mkdir(parents=True)
                first.write_text("WindowIndex\n1\n", encoding="utf-8")
                entry, context = catalog_entry_and_context(
                    root,
                    source_id="source-0001",
                    speaker="",
                    metadata={"Country": "Ireland"},
                )
                if case != "missing":
                    (first.parent / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
                    second = audio_output / "second" / "audio_analysis.csv"
                    second.parent.mkdir()
                    second.write_text("WindowIndex\n2\n", encoding="utf-8")
                    (second.parent / "source_context.json").write_text(json.dumps(context), encoding="utf-8")
                (audio_output / "source_manifest.json").write_text(
                    json.dumps({"catalog": {"sha256": "a" * 64}, "sources": [entry]}),
                    encoding="utf-8",
                )
                (audio_output / "source_metadata.csv").write_text("SourceID\nsource-0001\n", encoding="utf-8")
                destination = repo_root / "analysis" / "audio_outputs" / "Run_One"
                stale = destination / "stale.txt"
                stale.parent.mkdir(parents=True)
                stale.write_text("keep", encoding="utf-8")

                with self.assertRaises(ValueError):
                    export_batch_to_analysis_audio_outputs(
                        audio_output,
                        repo_root=repo_root,
                        run_name="Run_One",
                    )

                self.assertEqual(stale.read_text(encoding="utf-8"), "keep")
                self.assertFalse((destination / "source_manifest.json").exists())

    def test_full_stack_rejects_an_orphan_context_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "project"
            audio_output = root / "audio_output"
            orphan = audio_output / "orphan" / "source_context.json"
            orphan.parent.mkdir(parents=True)
            _entry, context = catalog_entry_and_context(
                root,
                source_id="source-0001",
                speaker="",
                metadata={},
            )
            orphan.write_text(json.dumps(context), encoding="utf-8")
            destination = repo_root / "analysis" / "audio_outputs" / "Run_One"
            stale = destination / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Orphan"):
                export_batch_to_analysis_audio_outputs(
                    audio_output,
                    repo_root=repo_root,
                    run_name="Run_One",
                )

            self.assertEqual(stale.read_text(encoding="utf-8"), "keep")

    def test_full_stack_rejects_reparse_destination_before_copying_sidecars(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "project"
            audio_output = root / "audio_output"
            audio_output.mkdir()
            (audio_output / "source_manifest.json").write_text('{"sources":[]}', encoding="utf-8")
            (audio_output / "source_metadata.csv").write_text("SourceID\n", encoding="utf-8")
            external = root / "external"
            external.mkdir()
            marker = external / "marker.txt"
            marker.write_text("keep", encoding="utf-8")
            destination = repo_root / "analysis" / "audio_outputs" / "Run_One"
            destination.parent.mkdir(parents=True)
            try:
                destination.symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Directory symlinks are unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "reparse|symlink"):
                export_batch_to_analysis_audio_outputs(audio_output, repo_root=repo_root, run_name="Run_One")

            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((external / "source_manifest.json").exists())
            self.assertFalse((external / "source_metadata.csv").exists())

    def test_full_stack_uses_a_non_reserved_windows_run_segment(self):
        self.assertEqual(safe_folder_name("CON.txt"), "_CON.txt")

    def test_project_root_helper_and_error_are_study_neutral(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            for name in ("procurement", "processing", "analysis"):
                (root / name).mkdir(parents=True)

            self.assertEqual(find_project_root(root / "processing"), root)
            with self.assertRaisesRegex(FileNotFoundError, "project root") as raised:
                find_project_root(Path(temp_dir) / "outside")

        self.assertNotIn("feeling", str(raised.exception).casefold())


if __name__ == "__main__":
    unittest.main()
