"""PCM window exports must preserve the samples consumed by the models."""
from __future__ import annotations

import random
import subprocess
import wave

import pytest

from processing.audio_analysis.audio_pipeline import media
from processing.audio_analysis.audio_pipeline.windows import AudioWindow
from procurement.external_tools import credential_free_media_environment


def write_pcm(path, *, rate=16000, channels=1):
    with wave.open(str(path), "wb") as handle:
        handle.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        handle.writeframes(random.Random(3107).randbytes(rate * channels * 2 * 12))


def pcm(path):
    with wave.open(str(path), "rb") as handle:
        return (handle.getnchannels(), handle.getsampwidth(), handle.getframerate(),
                handle.readframes(handle.getnframes()))


def test_internal_pcm_windows_do_not_start_another_decoder(tmp_path, monkeypatch):
    source = tmp_path / "音声 source.wav"
    target = tmp_path / "nested output" / "slice.wav"
    write_pcm(source)
    def unexpected_process(*args, **kwargs):
        pytest.fail("Extracted16k mono PCM needs no second decoder process")
    monkeypatch.setattr(media.subprocess, "run", unexpected_process)
    media.export_window_wav(source, AudioWindow(1, 1.25, 4.75), target)
    with wave.open(str(source), "rb") as handle:
        handle.setpos(20000)
        expected = handle.readframes(56000)
    assert pcm(target) == (1, 2, 16000, expected)


@pytest.mark.parametrize("start,end", [
    (0, 10), (2, 12), (1.234567, 4.567891), (0.000030, 1.000030),
    (0.000031, 1.000031), (0.000032, 1.000032), (0.0000625, 1.0000625),
    (0.1234564, 10.1234564), (0.1234566, 10.1234566),
    (5.987654, 12), (11.5, 12.5), (1.000031, 2.000062),
    (1.000032, 2.000064), (0, 0.500031), (0, 0.500032),
    (0, 0.000001), (0, 0.000015), (0, 0.000031), (0, 0.0000001),
])
def test_fast_pcm_samples_equal_ffmpeg_reference(tmp_path, start, end):
    source, candidate, reference = (tmp_path / name for name in ("source.wav", "candidate.wav", "reference.wav"))
    write_pcm(source)
    window = AudioWindow(1, start, end)
    media.export_window_wav(source, window, candidate)
    subprocess.run([
        str(media.resolve_ffmpeg_binary()), "-v", "error", "-y", "-ss", f"{start:.6f}",
        "-t", f"{window.duration:.6f}", "-i", str(source), "-ac", "1", "-ar", "16000", str(reference),
    ], check=True, capture_output=True, timeout=30, env=credential_free_media_environment())
    assert pcm(candidate) == pcm(reference)


@pytest.mark.parametrize("hardlink", [False, True])
def test_window_output_cannot_replace_its_source(tmp_path, hardlink):
    source = tmp_path / "original.wav"
    write_pcm(source)
    original = source.read_bytes()
    target = source
    if hardlink:
        target = tmp_path / "same-bytes-same-file.wav"
        target.hardlink_to(source)
    with pytest.raises(ValueError, match="same file"):
        media.export_window_wav(source, AudioWindow(1, 1, 2), target)
    assert source.read_bytes() == original
    assert target.read_bytes() == original


def test_noncanonical_audio_still_uses_ffmpeg_conversion(tmp_path):
    source, target = tmp_path / "stereo8k.wav", tmp_path / "converted.wav"
    write_pcm(source, rate=8000, channels=2)
    media.export_window_wav(source, AudioWindow(1, 0, 1), target)
    channels, width, rate, samples = pcm(target)
    assert (channels, width, rate, len(samples)) == (1, 2, 16000, 32000)
