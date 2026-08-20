import csv
import tempfile
import unittest
from pathlib import Path

from audio_pipeline.full_stack import (
    export_batch_to_analysis_audio_outputs,
    find_project_root,
    write_manifest,
)


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
            source_manifest.write_text('{"model":"test"}', encoding="utf-8")

            exported_root = export_batch_to_analysis_audio_outputs(
                audio_output,
                repo_root=repo_root,
                run_name="Run_One",
            )

            copied_csv = exported_root / "Speaker_A" / "Video_One" / "audio_analysis.csv"
            copied_manifest = exported_root / "Speaker_A" / "Video_One" / "audio_analysis_manifest.json"
            manifest = exported_root / "audio_outputs_manifest.csv"
            self.assertEqual(exported_root, repo_root / "analysis" / "audio_outputs" / "Run_One")
            self.assertEqual(copied_csv.read_text(encoding="utf-8"), "WindowIndex,Neutral\n1,0.8\n")
            self.assertEqual(copied_manifest.read_text(encoding="utf-8"), '{"model":"test"}')
            self.assertTrue(manifest.exists())

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
