import os
import tempfile
import unittest
from unittest.mock import call, patch
from pathlib import Path

from audio_pipeline.config import resolve_ffmpeg_binary, resolve_opensmile_binary
from audio_pipeline.media import extract_mono_wav, export_window_wav, probe_duration_seconds
from audio_pipeline.windows import AudioWindow


class PathResolutionTests(unittest.TestCase):
    def test_resolves_default_opensmile_binary_from_project_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "opensmile-3.0-win-x64" / "bin" / "SMILExtract.exe"
            binary.parent.mkdir(parents=True)
            binary.write_text("", encoding="utf-8")

            resolved = resolve_opensmile_binary(root)

        self.assertEqual(resolved, binary)

    def test_resolves_opensmile_binary_from_opensmile_home_environment_variable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "opensmile"
            binary = home / "bin" / "SMILExtract.exe"
            binary.parent.mkdir(parents=True)
            binary.write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"OPENSMILE_HOME": str(home)}):
                resolved = resolve_opensmile_binary(Path(temp_dir) / "project")

        self.assertEqual(resolved, binary)

    def test_ffmpeg_resolution_skips_decoy_in_selected_output_and_current_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "selected-output"
            trusted_dir = root / "trusted-tools"
            output_dir.mkdir()
            trusted_dir.mkdir()
            (output_dir / "ffmpeg.exe").write_bytes(b"decoy")
            trusted = trusted_dir / "ffmpeg.exe"
            trusted.write_bytes(b"trusted")
            previous_cwd = Path.cwd()
            try:
                os.chdir(output_dir)
                resolved = resolve_ffmpeg_binary(
                    excluded_roots=(output_dir,),
                    search_path=os.pathsep.join((str(output_dir), str(trusted_dir))),
                )
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(resolved, trusted.resolve())

    def test_media_commands_exclude_selected_input_and_output_directories(self):
        source = Path("C:/selected-input/video.mp4")
        extracted = Path("C:/selected-output/audio.wav")
        window = Path("C:/selected-output/window.wav")
        with (
            patch("audio_pipeline.media.resolve_ffmpeg_binary", return_value=Path("C:/trusted/ffmpeg.exe")) as ffmpeg,
            patch("audio_pipeline.media.resolve_ffprobe_binary", return_value=Path("C:/trusted/ffprobe.exe")) as ffprobe,
            patch("audio_pipeline.media.subprocess.run") as run,
        ):
            run.return_value.stdout = "12.5\n"
            extract_mono_wav(source, extracted)
            export_window_wav(extracted, AudioWindow(row=1, start=0.0, end=1.0), window)
            self.assertEqual(probe_duration_seconds(source), 12.5)

        self.assertEqual(
            ffmpeg.call_args_list,
            [
                call(excluded_roots=(source.parent, extracted.parent)),
                call(excluded_roots=(extracted.parent, window.parent)),
            ],
        )
        ffprobe.assert_called_once_with(excluded_roots=(source.parent,))


if __name__ == "__main__":
    unittest.main()
