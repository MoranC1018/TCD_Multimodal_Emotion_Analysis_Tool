import csv
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_pipeline.opensmile_runner import add_window_metadata, run_opensmile_windows
from audio_pipeline.windows import AudioWindow


class OpenSmileRunnerTests(unittest.TestCase):
    def test_add_window_metadata_writes_standard_comma_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "egemaps.csv"
            path.write_text(
                "name;frameTime;loudness\n'row_0001';0.0;0.42\n",
                encoding="utf-8",
            )

            add_window_metadata(path, [AudioWindow(row=1, start=0.0, end=10.0)])

            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            first_line = path.read_text(encoding="utf-8").splitlines()[0]

        self.assertEqual(rows[0][:5], ["Row", "WindowStart", "WindowEnd", "name", "frameTime"])
        self.assertEqual(rows[1][:5], ["1", "0", "10", "'row_0001'", "0.0"])
        self.assertIn(",", first_line)

    def test_add_window_metadata_preserves_negative_numeric_features(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "egemaps.csv"
            path.write_text(
                "name;frameTime;spectralSlope\n'row_0001';0.0;-0.42\n",
                encoding="utf-8",
            )

            add_window_metadata(path, [AudioWindow(row=1, start=0.0, end=10.0)])

            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))

        self.assertEqual(rows[1][-1], "-0.42")
        self.assertEqual(float(rows[1][-1]), -0.42)

    def test_run_opensmile_uses_temp_csv_before_unicode_output_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_wav = root / "audio.wav"
            binary = root / "SMILExtract.exe"
            config = root / "eGeMAPSv01b.conf"
            output_csv = root / "Łódź_👇" / "opensmile_features.csv"
            for path in (source_wav, binary, config):
                path.write_text("", encoding="utf-8")

            csv_paths_seen: list[Path] = []

            def fake_run(command, check, capture_output, text, timeout, **_kwargs):
                self.assertTrue(check)
                self.assertTrue(capture_output)
                self.assertTrue(text)
                self.assertEqual(timeout, 600)
                csv_path = Path(command[command.index("-csvoutput") + 1])
                append = command[command.index("-appendcsv") + 1] == "1"
                csv_paths_seen.append(csv_path)
                with csv_path.open("a" if append else "w", encoding="utf-8") as handle:
                    if not append:
                        handle.write("name;frameTime;loudness\n")
                    handle.write("'row_0001';0.0;0.42\n")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("audio_pipeline.opensmile_runner.subprocess.run", side_effect=fake_run):
                run_opensmile_windows(
                    source_wav,
                    [AudioWindow(row=1, start=0.0, end=2.0)],
                    output_csv,
                    opensmile_binary=binary,
                    opensmile_config=config,
                )

            self.assertTrue(output_csv.exists())
            self.assertNotEqual(csv_paths_seen[0], output_csv)
            self.assertEqual(csv_paths_seen[0].name, "features.csv")
            self.assertIn(",", output_csv.read_text(encoding="utf-8").splitlines()[0])

    def test_run_opensmile_reports_short_failure_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_wav = root / "audio.wav"
            binary = root / "SMILExtract.exe"
            config = root / "eGeMAPSv01b.conf"
            output_csv = root / "opensmile_features.csv"
            for path in (source_wav, binary, config):
                path.write_text("", encoding="utf-8")

            failed = subprocess.CalledProcessError(4294967295, ["SMILExtract"], stderr="bad path")
            with patch("audio_pipeline.opensmile_runner.subprocess.run", side_effect=failed):
                with self.assertRaisesRegex(RuntimeError, "OpenSMILE failed on window 1 with exit code 4294967295"):
                    run_opensmile_windows(
                        source_wav,
                        [AudioWindow(row=1, start=0.0, end=2.0)],
                        output_csv,
                        opensmile_binary=binary,
                        opensmile_config=config,
                    )


if __name__ == "__main__":
    unittest.main()
