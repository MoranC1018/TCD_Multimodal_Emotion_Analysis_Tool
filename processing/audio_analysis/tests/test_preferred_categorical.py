"""Preferred-model startup regressions; no downloads, production weights, or CUDA."""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import torch
from safetensors.torch import load_file, save_file

from audio_pipeline import emotion_models as models
from audio_pipeline.batch import run_batch
from audio_pipeline.pipeline import run_single_video


@pytest.fixture
def vendor_checkout(tmp_path, monkeypatch):
    """A tiny CPU-only stand-in for the author's custom checkpoint boundary."""
    source = tmp_path / "vendor" / "src" / "model" / "emotion" / "whisper_emotion.py"
    source.parent.mkdir(parents=True)
    source.write_text('''
import torch
from types import SimpleNamespace

class WhisperWrapper(torch.nn.Module):
    @classmethod
    def from_pretrained(cls, name, **kwargs):
        model = cls()
        model.load_request = (name, kwargs)
        return model

    def __init__(self):
        super().__init__()
        self.model_config = SimpleNamespace(_attn_implementation="sdpa")
        self.backbone_model = torch.nn.Module()
        encoder = self.backbone_model.encoder = torch.nn.Module()
        encoder.embed_positions = torch.nn.Embedding.from_pretrained(torch.ones(2, 4))
        self.embed_positions = torch.nn.Parameter(torch.zeros(2, 4), requires_grad=False)
        layer = torch.nn.Module()
        layer.self_attn = torch.nn.Module()
        layer.self_attn.config = None
        encoder.layers = torch.nn.ModuleList([layer])
        self.backbone_model.decoder = torch.nn.Linear(4, 4)
        for name in ("model_seq", "emotion_layer", "detailed_out_layer",
                     "arousal_layer", "valence_layer", "dominance_layer"):
            setattr(self, name, torch.nn.Linear(4, 4))
''', encoding="utf-8")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("test_vendor_fixture", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = module.WhisperWrapper().state_dict()
    del state["embed_positions"]
    checkpoint = source.parents[3] / "model.safetensors"
    save_file(state, str(checkpoint), metadata={"embed_positions": "backbone_model.encoder.embed_positions.weight"})
    monkeypatch.setattr("huggingface_hub.hf_hub_download", lambda **kwargs: str(checkpoint))
    return source.parents[3]


def test_missing_vendor_reports_actionable_error_without_generic_loader(monkeypatch):
    monkeypatch.delenv(models.VOX_PROFILE_DIR_ENV, raising=False)
    with patch.object(models, "import_transformers_pipeline", side_effect=AssertionError("generic loader used")):
        with pytest.raises(RuntimeError, match="VOX_PROFILE_RELEASE_DIR"):
            models.CategoricalWhisperEmotionModel.load(torch, "cpu")


def test_vendor_error_is_preserved_without_generic_loader(tmp_path, monkeypatch):
    monkeypatch.setenv(models.VOX_PROFILE_DIR_ENV, str(tmp_path / "missing"))
    with patch.object(models, "import_transformers_pipeline", side_effect=AssertionError("generic loader used")):
        with pytest.raises(RuntimeError, match="wrapper not found"):
            models.CategoricalWhisperEmotionModel.load(torch, "cpu")


def test_strict_bundle_stops_before_fallback_on_preferred_load_failure(monkeypatch):
    monkeypatch.delenv(models.VOX_PROFILE_DIR_ENV, raising=False)
    with patch.object(models.FallbackCategoricalEmotionModel, "load", side_effect=AssertionError("fallback used")):
        with pytest.raises(RuntimeError, match="VOX_PROFILE_RELEASE_DIR"):
            models.EmotionModelBundle.load(device="cpu", require_preferred_categorical=True)


def test_strict_bundle_rejects_skip_before_loading_torch():
    with patch.object(models, "import_torch", side_effect=AssertionError("torch imported")):
        with pytest.raises(ValueError, match="skip"):
            models.EmotionModelBundle.load(skip=True, require_preferred_categorical=True)


def test_vendor_loader_restores_checkpoint_positions_and_attention_config(vendor_checkout):
    adapter = models.VoxProfileWhisperEmotionModel.load(torch, "cpu", vendor_checkout)
    model = adapter.classifier
    assert torch.equal(model.embed_positions, torch.ones(2, 4))
    attention = model.backbone_model.encoder.layers[0].self_attn
    assert attention.config is model.model_config
    assert attention.config._attn_implementation == "eager"
    assert model.load_request == (
        models.CATEGORICAL_MODEL_NAME,
        {"revision": models.CATEGORICAL_MODEL_REVISION, "map_location": "cpu"},
    )
    assert not model.training


@pytest.mark.parametrize("invalid", ["shape", "nan"])
def test_invalid_checkpoint_positions_fail_before_placement(vendor_checkout, invalid):
    source = vendor_checkout / "src/model/emotion/whisper_emotion.py"
    replacement = "torch.zeros(3, 4)" if invalid == "shape" else "torch.full((2, 4), float('nan'))"
    original = "torch.zeros(2, 4)" if invalid == "shape" else "torch.ones(2, 4)"
    source.write_text(source.read_text(encoding="utf-8").replace(original, replacement), encoding="utf-8")
    with pytest.raises(RuntimeError, match="positional"):
        models.VoxProfileWhisperEmotionModel.load(torch, "cpu", vendor_checkout)


def test_cuda_placement_never_transfers_whole_wrapper_or_unused_decoder(vendor_checkout):
    transfers = []
    original_module_to = torch.nn.Module.to
    original_tensor_to = torch.Tensor.to

    def cpu_only_module_to(module, *args, **kwargs):
        device = kwargs.get("device", args[0] if args else None)
        transfers.append((module, str(device), kwargs.get("dtype")))
        if str(device) == "cuda":
            args = args[1:] if args else args
            kwargs = {**kwargs, "device": "cpu"}
        return original_module_to(module, *args, **kwargs)

    def cpu_only_tensor_to(tensor, *args, **kwargs):
        device = kwargs.get("device", args[0] if args else None)
        if str(device) == "cuda":
            args = args[1:] if args else args
            kwargs = {**kwargs, "device": "cpu"}
        return original_tensor_to(tensor, *args, **kwargs)

    with patch.object(torch.nn.Module, "to", cpu_only_module_to), patch.object(torch.Tensor, "to", cpu_only_tensor_to):
        model = models.VoxProfileWhisperEmotionModel.load(torch, "cuda", vendor_checkout).classifier

    moved = {id(module) for module, device, dtype in transfers if device == "cuda"}
    expected = {id(model.backbone_model.encoder)} | {
        id(getattr(model, name)) for name in
        ("model_seq", "emotion_layer", "detailed_out_layer", "arousal_layer", "valence_layer", "dominance_layer")
    }
    assert moved == expected
    assert all(dtype == torch.float32 for _, device, dtype in transfers if device == "cuda")
    assert model.backbone_model.decoder.weight.device.type == "cpu"


@pytest.mark.parametrize("corruption", ["missing_weight", "extra_weight", "wrong_shape", "missing_alias"])
def test_vendor_loader_rejects_incomplete_or_incompatible_checkpoint(vendor_checkout, corruption):
    checkpoint = vendor_checkout / "model.safetensors"
    state = load_file(str(checkpoint))
    metadata = {"embed_positions": "backbone_model.encoder.embed_positions.weight"}
    if corruption == "missing_weight":
        del state["emotion_layer.weight"]
    elif corruption == "extra_weight":
        state["unrecognised_layer.weight"] = torch.zeros(1)
    elif corruption == "wrong_shape":
        state["emotion_layer.weight"] = torch.zeros(2, 2)
    else:
        metadata = {}
    save_file(state, str(checkpoint), metadata=metadata)
    with pytest.raises(RuntimeError, match="checkpoint"):
        models.VoxProfileWhisperEmotionModel.load(torch, "cpu", vendor_checkout)


@pytest.mark.parametrize("logits", [
    torch.zeros(1, 8), torch.zeros(1, 10), torch.zeros(2, 9),
    torch.full((1, 9), float("nan")), torch.full((1, 9), float("inf")),
])
def test_preferred_predictions_reject_wrong_shape_or_nonfinite_logits(logits):
    adapter = models.VoxProfileWhisperEmotionModel(
        classifier=lambda *args, **kwargs: (logits,), device="cpu",
        model_name=models.CATEGORICAL_MODEL_NAME, model_version=models.CATEGORICAL_MODEL_REVISION,
    )
    with patch.object(models, "load_audio_array", return_value=torch.zeros(16000).numpy()):
        with pytest.raises(RuntimeError, match="categorical"):
            adapter.predict(Path("fixture.wav"))


def test_preferred_predictions_export_all_nine_finite_probabilities():
    adapter = models.VoxProfileWhisperEmotionModel(
        classifier=lambda *args, **kwargs: (torch.zeros(1, 9),), device="cpu",
        model_name=models.CATEGORICAL_MODEL_NAME, model_version=models.CATEGORICAL_MODEL_REVISION,
    )
    with patch.object(models, "load_audio_array", return_value=torch.zeros(16000).numpy()):
        result = adapter.predict(Path("fixture.wav"))
    assert list(result) == ["Anger", "Contempt", "Disgust", "Fear", "Happiness", "Neutral", "Sadness", "Surprise", "Other"]
    assert list(result.values()) == pytest.approx([1 / 9] * 9)


def test_preferred_predictions_reject_non_simplex_output():
    adapter = models.VoxProfileWhisperEmotionModel(
        classifier=lambda *args, **kwargs: (torch.zeros(1, 9),), device="cpu",
        model_name=models.CATEGORICAL_MODEL_NAME, model_version=models.CATEGORICAL_MODEL_REVISION,
    )
    with (
        patch.object(models, "load_audio_array", return_value=torch.zeros(16000).numpy()),
        patch("torch.nn.functional.softmax", return_value=torch.full((1, 9), 0.5)),
    ):
        with pytest.raises(RuntimeError, match="probabilit"):
            adapter.predict(Path("fixture.wav"))


@pytest.mark.parametrize("runner, injected", [(run_single_video, False), (run_batch, False), (run_single_video, True)])
@pytest.mark.parametrize("wrong_checkpoint", ["fallback", "unpinned"])
def test_strict_runs_preserve_previous_outputs_when_given_wrong_checkpoint(tmp_path, runner, injected, wrong_checkpoint):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fixture")
    output = tmp_path / "out"
    output.mkdir()
    saved = output / "audio_analysis.csv"
    saved.write_bytes(b"prior result")
    fallback_bundle = SimpleNamespace(
        skipped=False, categorical_available=True, dimensional_available=True,
        categorical_model_name=models.FALLBACK_CATEGORICAL_MODEL_NAME,
        categorical_model_version=models.FALLBACK_CATEGORICAL_MODEL_REVISION,
        errors=[], device="cpu",
    )
    if wrong_checkpoint == "unpinned":
        fallback_bundle.categorical_model_name = models.CATEGORICAL_MODEL_NAME
        fallback_bundle.categorical_model_version = "main"
    options = {"require_preferred_categorical": True}
    if injected:
        options["emotion_models"] = fallback_bundle
    with (
        patch.object(models.EmotionModelBundle, "load", return_value=fallback_bundle),
        patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=10.0),
        patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=AssertionError("strict guard allowed extraction")),
    ):
        with pytest.raises(RuntimeError, match="preferred"):
            runner(video, output, **options)
    assert saved.read_bytes() == b"prior result"
    assert {p.name for p in output.iterdir()} == {"audio_analysis.csv"}


def test_strict_bundle_accepts_successful_preferred_vendor_load(vendor_checkout, monkeypatch):
    monkeypatch.setenv(models.VOX_PROFILE_DIR_ENV, str(vendor_checkout))
    with patch.object(models.DimensionalAffectModel, "load", return_value=SimpleNamespace()):
        bundle = models.EmotionModelBundle.load(device="cpu", require_preferred_categorical=True)
    assert bundle.categorical_available
    assert bundle.categorical_model_name == models.CATEGORICAL_MODEL_NAME
    assert bundle.categorical_model_version == models.CATEGORICAL_MODEL_REVISION
    assert isinstance(bundle.categorical_model, models.VoxProfileWhisperEmotionModel)
    assert not bundle.errors


@pytest.mark.parametrize("module_name, prefix", [
    ("audio_pipeline.cli", ["single"]), ("audio_pipeline.cli", ["batch"]),
    ("audio_pipeline.run_single", []), ("audio_pipeline.run_batch", []),
])
def test_all_cli_entry_points_fail_clearly_in_strict_mode(tmp_path, monkeypatch, capsys, module_name, prefix):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fixture")
    output = tmp_path / "out"
    monkeypatch.delenv(models.VOX_PROFILE_DIR_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", [module_name, *prefix, str(video), "--output", str(output),
                                      "--require-preferred-categorical", "--device", "cpu"])
    module = importlib.import_module(module_name)
    with (
        patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=10.0),
        patch.object(module, "print_progress"),
    ):
        with pytest.raises(SystemExit) as exit_info:
            module.main()
    assert exit_info.value.code == 1
    assert "VOX_PROFILE_RELEASE_DIR" in capsys.readouterr().err
    assert not output.exists()


def test_cli_rejects_strict_and_skip_combination():
    from audio_pipeline.cli import build_parser
    with pytest.raises(SystemExit):
        build_parser().parse_args(["single", "input.mp4", "--skip-emotion-models",
                                  "--require-preferred-categorical"])


@pytest.mark.parametrize("runner", [run_single_video, run_batch])
def test_hardcoded_vendor_cuda_rejected_before_loading_or_output_cleanup(tmp_path, monkeypatch, runner):
    source = tmp_path / "vendor/src/model/emotion/whisper_emotion.py"
    source.parent.mkdir(parents=True)
    source.write_text('''
raise AssertionError("incompatible vendor was imported")
class WhisperWrapper:
    def forward(self, x):
        return x.cuda()
''', encoding="utf-8")
    monkeypatch.setenv(models.VOX_PROFILE_DIR_ENV, str(source.parents[3]))
    video = tmp_path / "input.mp4"
    video.write_bytes(b"fixture")
    output = tmp_path / "out"
    output.mkdir()
    previous = output / "audio_analysis.csv"
    previous.write_bytes(b"previous valid result")
    with patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=10.0):
        with pytest.raises(RuntimeError, match="hard-coded CUDA"):
            runner(video, output, device="cpu", require_preferred_categorical=True)
    assert previous.read_bytes() == b"previous valid result"
    assert {p.name for p in output.iterdir()} == {"audio_analysis.csv"}


@pytest.mark.parametrize("device, source", [
    ("cuda", "class WhisperWrapper:\n    def forward(self, x): return x.cuda()\n"),
    ("cpu", '"example: x.cuda()"\n# x.cuda()\nclass WhisperWrapper:\n    def forward(self, x): return x.to(x.device)\n'),
])
def test_vendor_device_preflight_allows_cuda_and_ignores_comments(tmp_path, device, source):
    path = tmp_path / "whisper_emotion.py"
    path.write_text(source, encoding="utf-8")
    models.validate_vox_profile_device_source(path, device)
