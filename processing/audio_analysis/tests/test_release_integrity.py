"""Regressions for preserving results and consuming only complete current runs."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from analysis.audio import discover_audio_analysis_inputs
from audio_pipeline.batch import run_batch, write_manifest_csv
from audio_pipeline.emotion_models import (
    CategoricalWhisperEmotionModel,
    FallbackCategoricalEmotionModel,
    SkippedEmotionModels,
    VoxProfileWhisperEmotionModel,
)
from audio_pipeline.full_stack import export_batch_to_analysis_audio_outputs
from audio_pipeline.pipeline import run_single_video


def seed_video_result(root, name):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    for filename in ("audio_analysis.csv", "opensmile_features.csv"):
        (folder / filename).write_text("Row,Timestamp,Anger\n1,0,0.2\n", encoding="utf-8")
    (folder / "audio_analysis_manifest.json").write_text('{"window_count": 1}', encoding="utf-8")
    return {
        "status": "ok", "video_folder": name,
        "output_folder": str(folder),
        "audio_analysis_csv": str(folder / "audio_analysis.csv"),
        "opensmile_features_csv": str(folder / "opensmile_features.csv"),
        "per_video_manifest": str(folder / "audio_analysis_manifest.json"),
        "window_count": 1,
    }


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def fake_extract(_input, output):
    output.write_bytes(b"fixture wav")
    return output


@pytest.mark.parametrize("options", [
    {"window_seconds": 0}, {"stride_seconds": 0},
    {"window_seconds": float("nan")}, {"stride_seconds": float("inf")},
    {"opensmile_feature_set": "unknown"}, {"device": "invalid"},
    {"window_seconds": 20, "skip_emotion_models": False},
])
def test_invalid_single_settings_preserve_existing_result(tmp_path, options):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fixture")
    seed_video_result(tmp_path, "out")
    output = tmp_path / "out"
    before = snapshot(output)
    kwargs = {"skip_emotion_models": True, **options}
    with (
        patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=20.0),
        patch("audio_pipeline.pipeline.EmotionModelBundle.load", return_value=SkippedEmotionModels()),
        patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
        patch("audio_pipeline.pipeline.run_opensmile_windows"),
        patch("audio_pipeline.pipeline.tool_version", return_value="fixture"),
    ):
        with pytest.raises(ValueError):
            run_single_video(video, output, **kwargs)
    assert snapshot(output) == before


@pytest.mark.parametrize("missing", ["categorical", "dimensional", "both"])
def test_requested_unavailable_layers_preserve_existing_single_result(tmp_path, missing):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fixture")
    seed_video_result(tmp_path, "out")
    output = tmp_path / "out"
    before = snapshot(output)
    models = SimpleNamespace(
        skipped=False, device="cpu", errors=["fixture model unavailable"],
        categorical_available=missing == "dimensional",
        dimensional_available=missing == "categorical",
    )
    with (
        patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=3.0),
        patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
        patch("audio_pipeline.pipeline.run_opensmile_windows"),
    ):
        with pytest.raises(RuntimeError, match="model layer.*unavailable"):
            run_single_video(video, output, emotion_models=models)
    assert snapshot(output) == before


@pytest.mark.parametrize("model_class", [CategoricalWhisperEmotionModel, FallbackCategoricalEmotionModel, VoxProfileWhisperEmotionModel])
def test_oversized_categorical_input_is_rejected_without_silent_truncation(model_class):
    model = model_class(classifier=lambda *args, **kwargs: [], device="cpu", model_name="fixture", model_version="fixture")
    with patch("audio_pipeline.emotion_models.load_audio_array", return_value=np.zeros(20 * 16000, dtype=np.float32)):
        with pytest.raises(ValueError, match="15"):
            model.predict(Path("twenty_seconds.wav"))


def test_analysis_uses_manifest_and_preserves_unselected_archives(tmp_path):
    selected = seed_video_result(tmp_path, "current")
    seed_video_result(tmp_path, "archive")
    write_manifest_csv(tmp_path / "audio_analysis_manifest.csv", [selected])
    before = snapshot(tmp_path)
    model_csvs, feature_csvs, _ = discover_audio_analysis_inputs(tmp_path)
    assert [p.parent.name for p in model_csvs] == ["current"]
    assert [p.parent.name for p in feature_csvs] == ["current"]
    assert snapshot(tmp_path) == before


def test_parent_folder_discovery_honors_nested_batch_manifests(tmp_path):
    managed = tmp_path / "managed_run"
    row = seed_video_result(managed, "current")
    seed_video_result(managed, "archive")
    seed_video_result(tmp_path, "legacy")
    write_manifest_csv(managed / "audio_analysis_manifest.csv", [row])
    model_csvs, feature_csvs, _ = discover_audio_analysis_inputs(tmp_path)
    assert {p.parent.name for p in model_csvs} == {"current", "legacy"}
    assert {p.parent.name for p in feature_csvs} == {"current", "legacy"}


@pytest.mark.parametrize("corruption", ["running", "bad_hash", "bad_count", "missing_manifest"])
def test_run_completion_marker_is_authoritative(tmp_path, corruption):
    import hashlib
    row = seed_video_result(tmp_path, "current")
    manifest = tmp_path / "audio_analysis_manifest.csv"
    write_manifest_csv(manifest, [row])
    state = {
        "version": 1, "status": "complete", "expected_count": 1,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    if corruption == "running":
        state["status"] = "running"
    elif corruption == "bad_hash":
        state["manifest_sha256"] = "0" * 64
    elif corruption == "bad_count":
        state["expected_count"] = 2
    else:
        manifest.unlink()
    (tmp_path / ".audio_analysis_run.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="[Bb]atch"):
        discover_audio_analysis_inputs(tmp_path)


def test_manifest_supports_copied_archives_using_relative_video_folder(tmp_path):
    selected = seed_video_result(tmp_path, "speaker/current")
    for field in ("output_folder", "audio_analysis_csv", "opensmile_features_csv", "per_video_manifest"):
        selected[field] = selected[field].replace(str(tmp_path), "C:\\old-machine\\original-run")
    write_manifest_csv(tmp_path / "audio_analysis_manifest.csv", [selected])
    model_csvs, _, _ = discover_audio_analysis_inputs(tmp_path)
    assert model_csvs == [tmp_path / "speaker/current/audio_analysis.csv"]


@pytest.mark.parametrize("corruption", ["invalid_csv", "duplicate", "failed", "escape", "mismatch", "missing", "bad_json", "zero_windows", "unknown_status"])
def test_manifest_errors_never_fall_back_to_glob(tmp_path, corruption):
    row = seed_video_result(tmp_path, "current")
    seed_video_result(tmp_path, "archive")
    rows = [row]
    if corruption == "duplicate":
        rows.append(dict(row))
    elif corruption in {"failed", "unknown_status"}:
        row["status"] = "failed" if corruption == "failed" else "finished"
    elif corruption == "escape":
        row["video_folder"] = "../current"
    elif corruption == "mismatch":
        row["audio_analysis_csv"] = str(tmp_path / "archive/audio_analysis.csv")
    elif corruption == "missing":
        (tmp_path / "current/opensmile_features.csv").unlink()
    elif corruption == "bad_json":
        (tmp_path / "current/audio_analysis_manifest.json").write_text("{", encoding="utf-8")
    elif corruption == "zero_windows":
        row["window_count"] = 0
    write_manifest_csv(tmp_path / "audio_analysis_manifest.csv", rows)
    if corruption == "invalid_csv":
        (tmp_path / "audio_analysis_manifest.csv").write_text("unrelated\nvalue\n", encoding="utf-8")
    with pytest.raises(ValueError, match="[Mm]anifest|[Ii]ncomplete|[Bb]atch"):
        discover_audio_analysis_inputs(tmp_path)


def test_full_stack_exports_only_current_manifest_entries(tmp_path):
    source = tmp_path / "source"
    selected = seed_video_result(source, "current")
    seed_video_result(source, "archive")
    write_manifest_csv(source / "audio_analysis_manifest.csv", [selected])
    destination = export_batch_to_analysis_audio_outputs(source, repo_root=tmp_path / "repo")
    assert (destination / "current/audio_analysis.csv").is_file()
    assert not (destination / "archive").exists()
    assert (source / "archive/audio_analysis.csv").is_file()


@pytest.mark.parametrize("failure", [KeyboardInterrupt, RuntimeError])
def test_interrupted_or_stopped_batch_cannot_publish_previous_manifest(tmp_path, failure):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("a.mp4", "b.mp4"):
        (inputs / name).write_bytes(b"fixture")
    output = tmp_path / "out"
    old = seed_video_result(output, "previous")
    write_manifest_csv(output / "audio_analysis_manifest.csv", [old])
    with (
        patch("audio_pipeline.batch.EmotionModelBundle.load", return_value=SkippedEmotionModels()),
        patch("audio_pipeline.batch.run_single_video", side_effect=failure("fixture interruption")),
    ):
        if failure is KeyboardInterrupt:
            with pytest.raises(KeyboardInterrupt):
                run_batch(inputs, output, skip_emotion_models=True, continue_on_error=False)
        else:
            result = run_batch(inputs, output, skip_emotion_models=True, continue_on_error=False)
            assert result.failed_count == 1
    with pytest.raises(ValueError, match="[Ii]ncomplete|[Bb]atch"):
        discover_audio_analysis_inputs(output)
    assert (output / "previous/audio_analysis.csv").is_file()


def test_invalid_batch_settings_do_not_write_or_load_models(tmp_path):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fixture")
    output = tmp_path / "out"
    with patch("audio_pipeline.batch.run_single_video", side_effect=ValueError("window_seconds must be positive")):
        with pytest.raises(ValueError, match="window"):
            run_batch(video, output, window_seconds=0, skip_emotion_models=True)
    assert not output.exists()


def test_standalone_rerun_cannot_mix_new_single_result_into_completed_batch(tmp_path):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fixture")
    output = tmp_path / "out"
    row = seed_video_result(output, "current")
    write_manifest_csv(output / "audio_analysis_manifest.csv", [row])
    before = snapshot(output)
    with (
        patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=3.0),
        patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=RuntimeError("fixture processing started")),
    ):
        with pytest.raises(ValueError, match="batch"):
            run_single_video(video, output / "current", skip_emotion_models=True)
    assert snapshot(output) == before


@pytest.mark.parametrize("name", ["@speaker", "'=literal", "nested/@speaker"])
def test_manifest_path_mapping_preserves_spreadsheet_safe_folder_names(tmp_path, name):
    row = seed_video_result(tmp_path, name)
    write_manifest_csv(tmp_path / "audio_analysis_manifest.csv", [row])
    model_csvs, _, _ = discover_audio_analysis_inputs(tmp_path)
    assert model_csvs == [tmp_path / name / "audio_analysis.csv"]


def test_supported_categorical_window_passes_every_sample_to_inference():
    samples = np.arange(15 * 16000, dtype=np.float32)
    received = []

    def classifier(sample, **kwargs):
        received.append(sample["array"])
        return [{"label": "hap", "score": 1.0}]

    model = CategoricalWhisperEmotionModel(
        classifier=classifier, device="cpu", model_name="fixture", model_version="fixture",
    )
    with patch("audio_pipeline.emotion_models.load_audio_array", return_value=samples):
        result = model.predict(Path("fifteen_seconds.wav"))
    assert result["Happiness"] == 1.0
    np.testing.assert_array_equal(received[0], samples)
