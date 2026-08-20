import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from procurement.video_sampling import run_docx_extractions


class DocxCompletionTests(unittest.TestCase):
    def test_completion_marker_rejects_oversized_control_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            (output_folder / "_extraction_complete.json").write_text(
                '{"status":"success","skip_stitch":true,"padding":"'
                + ("x" * (64 * 1024))
                + '"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "completion marker JSON exceeds"):
                run_docx_extractions.folder_contains_completed_extraction(output_folder)

    def test_raw_clips_without_completion_marker_are_not_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            raw_folder = output_folder / "raw_clips"
            raw_folder.mkdir()
            (raw_folder / "001.mp4").write_bytes(b"clip")

            self.assertFalse(run_docx_extractions.folder_contains_completed_extraction(output_folder))

    def test_no_stitch_completion_marker_allows_raw_clip_reuse(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            raw_folder = output_folder / "raw_clips"
            raw_folder.mkdir()
            (raw_folder / "001.mp4").write_bytes(b"clip")
            (output_folder / "_extraction_complete.json").write_text(
                json.dumps({"status": "success", "skip_stitch": True}),
                encoding="utf-8",
            )

            self.assertTrue(run_docx_extractions.folder_contains_completed_extraction(output_folder))

    def test_stitched_completion_marker_requires_stitched_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            (output_folder / "_extraction_complete.json").write_text(
                json.dumps({"status": "success", "skip_stitch": False}),
                encoding="utf-8",
            )

            self.assertFalse(run_docx_extractions.folder_contains_completed_extraction(output_folder))

            (output_folder / "stitched_imotions.mp4").write_bytes(b"video")
            self.assertTrue(run_docx_extractions.folder_contains_completed_extraction(output_folder))

    def test_completed_extraction_requires_matching_request_fingerprint_when_supplied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            (output_folder / "_extraction_complete.json").write_text(
                json.dumps({"status": "success", "skip_stitch": False}),
                encoding="utf-8",
            )
            (output_folder / "stitched_imotions.mp4").write_bytes(b"video")
            request = {
                "video_id": "abc123",
                "url": "https://www.youtube.com/watch?v=abc123",
                "extractor": "extractor.py",
                "arguments": ["--percentage", "10", "--max-segment-length", "30"],
            }
            (output_folder / "_docx_extraction_request.json").write_text(
                json.dumps(request),
                encoding="utf-8",
            )

            self.assertTrue(
                run_docx_extractions.folder_contains_completed_extraction(output_folder, request)
            )
            changed = {**request, "arguments": ["--percentage", "20", "--max-segment-length", "30"]}
            self.assertFalse(
                run_docx_extractions.folder_contains_completed_extraction(output_folder, changed)
            )

    def test_folder_links_are_encoded_for_word_relationships(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            document = Document()
            table = document.add_table(rows=1, cols=2)
            output_docx = temp_path / "linked.docx"
            folder = temp_path / "downloads" / "Speaker" / "Title with accents é and marker 🔴_[abc123]"
            folder.mkdir(parents=True)

            run_docx_extractions.add_folder_link_to_row(table.rows[0], folder, output_docx)
            document.save(output_docx)

            with ZipFile(output_docx) as archive:
                relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")

        self.assertIn("%C3%A9", relationships)
        self.assertIn("%F0%9F%94%B4", relationships)
        self.assertNotIn("Title with accents", relationships)
        self.assertNotIn("🔴", relationships)


if __name__ == "__main__":
    unittest.main()
