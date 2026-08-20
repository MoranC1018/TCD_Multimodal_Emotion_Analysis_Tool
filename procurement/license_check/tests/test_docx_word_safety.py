import csv
import os
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from docx import Document
from docx.oxml.ns import qn

from procurement.license_check import audit_docx, run_license_check, verify_audit


class DocxWordSafetyTests(unittest.TestCase):
    def test_license_audit_csv_exports_neutralize_web_controlled_labels(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            debug_values = {
                name: "ordinary" for name in audit_docx.DebugRow.__dataclass_fields__
            }
            debug_values.update(
                table_number=1,
                row_number=2,
                youtube_title="=1+1",
                youtube_channel="@channel",
            )
            debug_path = root / "debug.csv"
            audit_docx.write_debug_csv(
                [audit_docx.DebugRow(**debug_values)], debug_path
            )

            verification_values = {
                name: "ordinary"
                for name in verify_audit.VerificationRow.__dataclass_fields__
            }
            verification_values.update(
                table_number=1,
                row_number=2,
                document_title_or_first_col="+command",
                youtube_title="-hostile-title",
                youtube_channel="\tchannel",
            )
            verification_path = root / "verification.csv"
            verify_audit.write_csv(
                [verify_audit.VerificationRow(**verification_values)],
                verification_path,
            )

            with debug_path.open(encoding="utf-8-sig", newline="") as handle:
                debug_row = next(csv.DictReader(handle))
            with verification_path.open(encoding="utf-8-sig", newline="") as handle:
                verification_row = next(csv.DictReader(handle))

        self.assertEqual(debug_row["youtube_title"], "'=1+1")
        self.assertEqual(debug_row["youtube_channel"], "'@channel")
        self.assertEqual(verification_row["document_title_or_first_col"], "'+command")
        self.assertEqual(verification_row["youtube_title"], "'-hostile-title")
        self.assertEqual(verification_row["youtube_channel"], "'\tchannel")

    def test_audit_term_dictionary_rejects_oversized_control_json(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "terms.json"
            path.write_text(json.dumps({"category": ["x" * (1024 * 1024)]}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "licence term dictionary JSON exceeds"):
                audit_docx.load_term_dictionary(path)

    def test_audit_term_dictionary_rejects_excessive_pattern_count(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "terms.json"
            path.write_text(json.dumps({"category": ["x"] * 4_097}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "more than 4096 regex patterns"):
                audit_docx.load_term_dictionary(path)

    def test_verify_term_dictionary_rejects_oversized_control_json(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "terms.json"
            path.write_text(json.dumps({"category": ["x" * (1024 * 1024)]}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "licence term dictionary JSON exceeds"):
                verify_audit.load_dictionary(str(path))

    def test_verify_term_dictionary_rejects_excessive_pattern_length(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "terms.json"
            path.write_text(json.dumps({"category": ["x" * 2_049]}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "longer than 2048 characters"):
                verify_audit.load_dictionary(str(path))

    def test_insert_header_row_keeps_table_properties_before_rows(self):
        document = Document()
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "https://www.youtube.com/watch?v=abcdefghijk"

        audit_docx.insert_header_row(table)

        child_tags = [child.tag for child in table._tbl]
        first_row_index = child_tags.index(qn("w:tr"))
        self.assertGreater(first_row_index, 0)
        self.assertIn(qn("w:tblPr"), child_tags[:first_row_index])
        self.assertIn(qn("w:tblGrid"), child_tags[:first_row_index])
        self.assertEqual(table.rows[0].cells[0].text, "Link")

    def test_run_license_check_redacts_api_key_in_display_command(self):
        command = ["python", "audit_docx.py", "--api-key", "secret-key", "--output", "out.docx"]

        redacted = run_license_check.redact_command_for_console(command)

        self.assertEqual(redacted[3], "<redacted>")
        self.assertNotIn("secret-key", redacted)

    def test_preflight_does_not_accept_api_key_from_plaintext_config(self):
        with TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
            root = Path(temp_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            allowed, message = run_license_check.preflight(
                root,
                {"YOUTUBE_API_KEY": "plaintext-file-secret"},
                input_dir,
            )

        self.assertFalse(allowed)
        self.assertIn("environment", message.casefold())


if __name__ == "__main__":
    unittest.main()
