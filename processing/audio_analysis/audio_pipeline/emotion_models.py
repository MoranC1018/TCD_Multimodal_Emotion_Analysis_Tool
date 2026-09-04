from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


CATEGORICAL_MODEL_NAME = "tiantiaf/whisper-large-v3-msp-podcast-emotion"
FALLBACK_CATEGORICAL_MODEL_NAME = "superb/wav2vec2-base-superb-er"
DIMENSIONAL_MODEL_NAME = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
CATEGORICAL_MODEL_REVISION = "b92dab65151206a603810ec8b72eb528b9dd983c"
FALLBACK_CATEGORICAL_MODEL_REVISION = "441a7599c3b22107314dcbd9166621c5c83f2cc5"
DIMENSIONAL_MODEL_REVISION = "6eba34a2485ea31cb03600241787c3a5edab8626"
VOX_PROFILE_DIR_ENV = "VOX_PROFILE_RELEASE_DIR"

EMOTION_COLUMNS = [
    "Anger",
    "Contempt",
    "Disgust",
    "Fear",
    "Happiness",
    "Neutral",
    "Sadness",
    "Surprise",
    "Other",
]

EMOTION_ALIASES = {
    "anger": "Anger",
    "angry": "Anger",
    "ang": "Anger",
    "contempt": "Contempt",
    "disgust": "Disgust",
    "disgusted": "Disgust",
    "fear": "Fear",
    "fearful": "Fear",
    "happiness": "Happiness",
    "happy": "Happiness",
    "hap": "Happiness",
    "joy": "Happiness",
    "neutral": "Neutral",
    "neu": "Neutral",
    "sadness": "Sadness",
    "sad": "Sadness",
    "surprise": "Surprise",
    "surprised": "Surprise",
    "other": "Other",
    "label_0": "Anger",
    "0": "Anger",
    "label_1": "Contempt",
    "1": "Contempt",
    "label_2": "Disgust",
    "2": "Disgust",
    "label_3": "Fear",
    "3": "Fear",
    "label_4": "Happiness",
    "4": "Happiness",
    "label_5": "Neutral",
    "5": "Neutral",
    "label_6": "Sadness",
    "6": "Sadness",
    "label_7": "Surprise",
    "7": "Surprise",
    "label_8": "Other",
    "8": "Other",
}

DIMENSION_ALIASES = {
    "arousal": "Arousal",
    "aro": "Arousal",
    "label_0": "Arousal",
    "0": "Arousal",
    "dominance": "Dominance",
    "dom": "Dominance",
    "label_1": "Dominance",
    "1": "Dominance",
    "valence": "Valence",
    "val": "Valence",
    "label_2": "Valence",
    "2": "Valence",
}


@dataclass(frozen=True)
class EmotionModelResult:
    probabilities: dict[str, float | str | None]
    arousal: float | str | None = None
    dominance: float | str | None = None
    valence: float | str | None = None

    @classmethod
    def empty(cls) -> "EmotionModelResult":
        return cls(probabilities={emotion: "" for emotion in EMOTION_COLUMNS}, arousal="", dominance="", valence="")


class EmotionModels(Protocol):
    categorical_model_name: str
    categorical_model_version: str
    dimensional_model_name: str
    dimensional_model_version: str
    device: str
    skipped: bool
    categorical_available: bool
    dimensional_available: bool
    errors: list[str]

    def predict_window(self, window_wav: Path) -> EmotionModelResult:
        ...


@dataclass
class SkippedEmotionModels:
    categorical_model_name: str = ""
    categorical_model_version: str = ""
    dimensional_model_name: str = ""
    dimensional_model_version: str = ""
    device: str = ""
    skipped: bool = True
    categorical_available: bool = False
    dimensional_available: bool = False
    errors: list[str] | None = None

    def predict_window(self, _window_wav: Path) -> EmotionModelResult:
        return EmotionModelResult.empty()


class EmotionModelBundle:
    """Reusable model bundle loaded once per single run or batch run."""

    def __init__(
        self,
        *,
        categorical_model,
        dimensional_model,
        device: str,
        categorical_model_name: str = CATEGORICAL_MODEL_NAME,
        categorical_model_version: str = CATEGORICAL_MODEL_REVISION,
        dimensional_model_name: str = DIMENSIONAL_MODEL_NAME,
        dimensional_model_version: str = DIMENSIONAL_MODEL_REVISION,
        categorical_available: bool = True,
        dimensional_available: bool = True,
        errors: list[str] | None = None,
    ) -> None:
        self.categorical_model = categorical_model
        self.dimensional_model = dimensional_model
        self.device = device
        self.categorical_model_name = categorical_model_name
        self.categorical_model_version = categorical_model_version
        self.dimensional_model_name = dimensional_model_name
        self.dimensional_model_version = dimensional_model_version
        self.categorical_available = categorical_available
        self.dimensional_available = dimensional_available
        self.errors = errors or []
        self.skipped = False

    @classmethod
    def load(cls, *, skip: bool = False, device: str = "auto") -> EmotionModels:
        if skip:
            return SkippedEmotionModels()

        torch = import_torch()
        resolved_device = resolve_device(device, torch)

        errors: list[str] = []
        try:
            categorical_model = CategoricalWhisperEmotionModel.load(torch, resolved_device)
        except Exception as exc:
            preferred_error = exc
            try:
                categorical_model = FallbackCategoricalEmotionModel.load(torch, resolved_device, purpose="main-fallback")
            except Exception as fallback_exc:
                errors.append(categorical_unavailable_message(preferred_error, fallback_exc))
                categorical_model = UnavailableCategoricalModel()
            else:
                errors.append(categorical_fallback_message(preferred_error))
        else:
            errors.extend(getattr(categorical_model, "load_warnings", []))

        try:
            dimensional_model = DimensionalAffectModel.load(torch, resolved_device)
        except Exception as exc:
            errors.append(f"dimensional model unavailable: {compact_error(exc)}")
            dimensional_model = UnavailableDimensionalModel()

        return cls(
            categorical_model=categorical_model,
            dimensional_model=dimensional_model,
            device=resolved_device,
            categorical_model_name=getattr(categorical_model, "model_name", CATEGORICAL_MODEL_NAME),
            categorical_model_version=getattr(categorical_model, "model_version", CATEGORICAL_MODEL_REVISION),
            categorical_available=not isinstance(categorical_model, UnavailableCategoricalModel),
            dimensional_available=not isinstance(dimensional_model, UnavailableDimensionalModel),
            errors=errors,
        )

    def predict_window(self, window_wav: Path) -> EmotionModelResult:
        probabilities = self.categorical_model.predict(window_wav)
        dimensions = self.dimensional_model.predict(window_wav)
        return EmotionModelResult(
            probabilities=probabilities,
            arousal=dimensions.get("Arousal", ""),
            dominance=dimensions.get("Dominance", ""),
            valence=dimensions.get("Valence", ""),
        )


def load_debug_fallback_emotion_models(*, device: str = "auto") -> EmotionModelBundle:
    """Load the categorical fallback model for explicit debug comparison only."""

    torch = import_torch()
    resolved_device = resolve_device(device, torch)
    fallback_model = FallbackCategoricalEmotionModel.load(torch, resolved_device, purpose="debug-fallback")
    return EmotionModelBundle(
        categorical_model=fallback_model,
        dimensional_model=UnavailableDimensionalModel(),
        device=resolved_device,
        categorical_model_name=fallback_model.model_name,
        categorical_model_version=fallback_model.model_version,
        dimensional_model_name="",
        dimensional_model_version="",
        categorical_available=True,
        dimensional_available=False,
        errors=["debug fallback output only; not used in main audio_analysis.csv"],
    )


class UnavailableCategoricalModel:
    model_name = ""
    model_version = ""

    def predict(self, _window_wav: Path) -> dict[str, str]:
        return {emotion: "" for emotion in EMOTION_COLUMNS}


class UnavailableDimensionalModel:
    model_name = ""
    model_version = ""

    def predict(self, _window_wav: Path) -> dict[str, str]:
        return {"Arousal": "", "Dominance": "", "Valence": ""}


def import_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "The emotion model dependencies are not installed. Run pip install -r requirements.txt "
            "or use --skip-emotion-models for OpenSMILE-only extraction."
        ) from exc
    return torch


def resolve_device(requested: str, torch_module) -> str:
    value = requested.lower()
    if value not in {"auto", "cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    if value == "auto":
        return "cuda" if torch_module.cuda.is_available() else "cpu"
    if value == "cuda" and not torch_module.cuda.is_available():
        raise RuntimeError("CUDA was requested, but torch.cuda.is_available() is false. Use --device cpu or --device auto.")
    return value


def normalise_emotion_scores(raw_scores: list[dict[str, object]]) -> dict[str, float | str]:
    probabilities: dict[str, float | str] = {emotion: "" for emotion in EMOTION_COLUMNS}
    for item in raw_scores:
        label = canonical_emotion_label(str(item.get("label", "")))
        score = float(item.get("score", 0.0))
        current = probabilities[label]
        probabilities[label] = score if current == "" else float(current) + score
    return probabilities


def normalise_dimension_scores(raw_scores: list[dict[str, object]]) -> dict[str, float]:
    dimensions: dict[str, float] = {}
    for item in raw_scores:
        label = canonical_dimension_label(str(item.get("label", "")))
        if label:
            dimensions[label] = float(item.get("score", 0.0))
    return dimensions


def canonical_emotion_label(label: str) -> str:
    cleaned = label.strip().lower().replace("-", "_").replace(" ", "_")
    return EMOTION_ALIASES.get(cleaned, "Other")


def canonical_dimension_label(label: str) -> str | None:
    cleaned = label.strip().lower().replace("-", "_").replace(" ", "_")
    return DIMENSION_ALIASES.get(cleaned)


def compact_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if len(text) > 500:
        return f"{text[:500]}..."
    return text


def preferred_categorical_failure_summary(exc: Exception) -> str:
    """Return a compact, privacy-safe explanation for preferred model failures."""

    text = str(exc)
    if "Traceback" in text or "Could not load model" in text or "AutoModelForAudioClassification" in text:
        return "preferred categorical model could not be loaded"
    return compact_error(exc)


def categorical_fallback_message(preferred_exc: Exception) -> str:
    """Explain that the runtime used the supported fallback instead of blank outputs."""

    return (
        f"preferred categorical model unavailable; using fallback categorical model "
        f"{FALLBACK_CATEGORICAL_MODEL_NAME}. Preferred error: "
        f"{preferred_categorical_failure_summary(preferred_exc)}"
    )


def categorical_unavailable_message(preferred_exc: Exception, fallback_exc: Exception | None = None) -> str:
    """Return a stable console/manifest warning when no categorical layer can run."""

    message = (
        "categorical model unavailable: preferred and fallback categorical models could not be loaded; "
        "main categorical columns will be blank. Preferred error: "
        f"{preferred_categorical_failure_summary(preferred_exc)}"
    )
    if fallback_exc is not None:
        message += f"; fallback error: {compact_error(fallback_exc)}"
    return message


def suppress_transformers_torchvision() -> None:
    """Keep broken optional torchvision installs from blocking audio-only models."""

    try:
        from transformers.utils import import_utils
    except Exception:
        return
    import_utils._torchvision_available = False
    import_utils._torchvision_version = "unavailable-for-audio-pipeline"


# The preferred model author's documented input limit is 15 seconds at 16 kHz.
# Keep the same bound across categorical backends so fallback does not change the protocol.
MAX_CATEGORICAL_WINDOW_SECONDS = 15


def validate_categorical_sample_count(samples) -> None:
    if len(samples) > MAX_CATEGORICAL_WINDOW_SECONDS * 16000:
        raise ValueError(
            f"Categorical emotion input exceeds {MAX_CATEGORICAL_WINDOW_SECONDS} seconds; "
            "use a supported analysis window instead of truncating audio."
        )


class CategoricalWhisperEmotionModel:
    """Adapter for the preferred MSP-Podcast categorical Whisper model."""

    def __init__(self, *, classifier, device: str, model_name: str, model_version: str, load_warnings: list[str] | None = None) -> None:
        self.classifier = classifier
        self.device = device
        self.model_name = model_name
        self.model_version = model_version
        self.load_warnings = load_warnings or []

    @classmethod
    def load(cls, torch_module, device: str) -> "CategoricalWhisperEmotionModel":
        vox_profile_checkout = configured_vox_profile_checkout()
        vox_profile_error = ""
        if vox_profile_checkout is not None:
            try:
                return VoxProfileWhisperEmotionModel.load(torch_module, device, vox_profile_checkout)
            except Exception as exc:
                vox_profile_error = compact_error(exc)

        suppress_transformers_torchvision()
        pipeline = import_transformers_pipeline()
        pipeline_device = 0 if device == "cuda" else -1
        try:
            classifier = pipeline(
                task="audio-classification",
                model=CATEGORICAL_MODEL_NAME,
                revision=CATEGORICAL_MODEL_REVISION,
                device=pipeline_device,
            )
        except Exception as exc:
            details = compact_error(exc)
            if vox_profile_error:
                details = (
                    "configured vox-profile-release categorical backend unavailable: "
                    f"{vox_profile_error}; Transformers load failed: {details}"
                )
            raise RuntimeError(details) from exc

        warnings = []
        if vox_profile_error:
            warnings.append(
                "configured vox-profile-release categorical backend unavailable; "
                f"using Transformers backend: {vox_profile_error}"
            )
        return cls(
            classifier=classifier,
            device=device,
            model_name=CATEGORICAL_MODEL_NAME,
            model_version=CATEGORICAL_MODEL_REVISION,
            load_warnings=warnings,
        )

    def predict(self, window_wav: Path) -> dict[str, float | str]:
        samples = load_audio_array(window_wav)
        validate_categorical_sample_count(samples)
        raw_scores = self.classifier({"array": samples, "sampling_rate": 16000}, top_k=None)
        if raw_scores and isinstance(raw_scores[0], list):
            raw_scores = raw_scores[0]
        return normalise_emotion_scores(raw_scores)


class FallbackCategoricalEmotionModel(CategoricalWhisperEmotionModel):
    """Adapter for the SUPERB categorical model used when the preferred model is unavailable."""

    @classmethod
    def load(cls, torch_module, device: str, *, purpose: str = "fallback") -> "FallbackCategoricalEmotionModel":
        suppress_transformers_torchvision()
        pipeline = import_transformers_pipeline()
        pipeline_device = 0 if device == "cuda" else -1
        classifier = pipeline(
            task="audio-classification",
            model=FALLBACK_CATEGORICAL_MODEL_NAME,
            revision=FALLBACK_CATEGORICAL_MODEL_REVISION,
            device=pipeline_device,
        )
        return cls(
            classifier=classifier,
            device=device,
            model_name=FALLBACK_CATEGORICAL_MODEL_NAME,
            model_version=FALLBACK_CATEGORICAL_MODEL_REVISION,
        )


class VoxProfileWhisperEmotionModel(CategoricalWhisperEmotionModel):
    """Optional adapter for the model author's vox-profile-release wrapper."""

    @classmethod
    def load(
        cls,
        torch_module,
        device: str,
        checkout: Path,
    ) -> "VoxProfileWhisperEmotionModel":
        module_path = checkout / "src" / "model" / "emotion" / "whisper_emotion.py"
        if not module_path.exists():
            raise RuntimeError(f"vox-profile-release wrapper not found: {module_path}")

        src_path = checkout / "src"
        emotion_path = src_path / "model" / "emotion"
        for path in (src_path, emotion_path):
            path_text = str(path)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)

        suppress_transformers_torchvision()
        spec = importlib.util.spec_from_file_location("vox_profile_whisper_emotion", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load vox-profile-release wrapper: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        wrapper_class = getattr(module, "WhisperWrapper")
        model = wrapper_class.from_pretrained(
            CATEGORICAL_MODEL_NAME,
            revision=CATEGORICAL_MODEL_REVISION,
        ).to(device)
        model.eval()
        return cls(
            classifier=model,
            device=device,
            model_name=CATEGORICAL_MODEL_NAME,
            model_version=CATEGORICAL_MODEL_REVISION,
        )

    def predict(self, window_wav: Path) -> dict[str, float | str]:
        samples = load_audio_array(window_wav)
        validate_categorical_sample_count(samples)
        torch = import_torch()
        tensor = torch.from_numpy(samples).float().reshape(1, -1).to(self.device)
        with torch.no_grad():
            outputs = self.classifier(tensor, return_feature=True)
        logits = outputs[0]
        probabilities = torch.nn.functional.softmax(logits, dim=1).detach().cpu().numpy()[0]
        return {emotion: float(probabilities[index]) for index, emotion in enumerate(EMOTION_COLUMNS)}


def configured_vox_profile_checkout() -> Path | None:
    configured = os.environ.get(VOX_PROFILE_DIR_ENV, "").strip()
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


def import_transformers_pipeline():
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise RuntimeError(
            "transformers is not installed. Run pip install -r requirements.txt "
            "or use --skip-emotion-models for OpenSMILE-only extraction."
        ) from exc
    return pipeline


class DimensionalAffectModel:
    """Adapter for audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim."""

    def __init__(self, *, processor, model, torch_module, device: str) -> None:
        self.processor = processor
        self.model = model
        self.torch = torch_module
        self.device = device

    @classmethod
    def load(cls, torch_module, device: str) -> "DimensionalAffectModel":
        try:
            from transformers import Wav2Vec2Processor
        except ImportError as exc:
            raise RuntimeError(
                "transformers is not installed. Run pip install -r requirements.txt "
                "or use --skip-emotion-models for OpenSMILE-only extraction."
            ) from exc

        model_class = build_dimensional_model_class(torch_module)
        processor = Wav2Vec2Processor.from_pretrained(DIMENSIONAL_MODEL_NAME, revision=DIMENSIONAL_MODEL_REVISION)
        model = model_class.from_pretrained(DIMENSIONAL_MODEL_NAME, revision=DIMENSIONAL_MODEL_REVISION).to(device)
        model.eval()
        return cls(processor=processor, model=model, torch_module=torch_module, device=device)

    def predict(self, window_wav: Path) -> dict[str, float]:
        signal = load_audio_array(window_wav)
        processed = self.processor(signal, sampling_rate=16000)
        input_values = self.torch.from_numpy(processed["input_values"][0]).reshape(1, -1).to(self.device)
        with self.torch.no_grad():
            _hidden_states, logits = self.model(input_values)
        values = logits.detach().cpu().numpy()[0]
        return {"Arousal": float(values[0]), "Dominance": float(values[1]), "Valence": float(values[2])}


def build_dimensional_model_class(torch_module):
    from transformers.models.wav2vec2.modeling_wav2vec2 import Wav2Vec2Model, Wav2Vec2PreTrainedModel

    class RegressionHead(torch_module.nn.Module):
        def __init__(self, config):
            super().__init__()
            self.dense = torch_module.nn.Linear(config.hidden_size, config.hidden_size)
            self.dropout = torch_module.nn.Dropout(config.final_dropout)
            self.out_proj = torch_module.nn.Linear(config.hidden_size, config.num_labels)

        def forward(self, features):
            output = self.dropout(features)
            output = self.dense(output)
            output = torch_module.tanh(output)
            output = self.dropout(output)
            return self.out_proj(output)

    class Wav2Vec2DimensionalEmotionModel(Wav2Vec2PreTrainedModel):
        all_tied_weights_keys = {}

        def __init__(self, config):
            super().__init__(config)
            self.wav2vec2 = Wav2Vec2Model(config)
            self.classifier = RegressionHead(config)
            self.init_weights()

        def forward(self, input_values):
            outputs = self.wav2vec2(input_values)
            hidden_states = torch_module.mean(outputs[0], dim=1)
            logits = self.classifier(hidden_states)
            return hidden_states, logits

    return Wav2Vec2DimensionalEmotionModel


def load_audio_tensor(window_wav: Path, torch_module, device: str, max_samples: int):
    samples = load_audio_array(window_wav)
    if len(samples) > max_samples:
        samples = samples[:max_samples]
    return torch_module.from_numpy(samples).float().reshape(1, -1).to(device)


def load_audio_array(window_wav: Path):
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("soundfile and numpy are required for emotion model audio loading.") from exc

    samples, sample_rate = sf.read(str(window_wav), dtype="float32", always_2d=False)
    if getattr(samples, "ndim", 1) > 1:
        samples = np.mean(samples, axis=1)
    if sample_rate != 16000:
        try:
            import librosa
        except ImportError as exc:
            raise RuntimeError("librosa is required to resample audio for the emotion models.") from exc
        samples = librosa.resample(samples, orig_sr=sample_rate, target_sr=16000)
    if len(samples) == 0:
        samples = np.zeros(16000, dtype="float32")
    return samples.astype("float32", copy=False)
