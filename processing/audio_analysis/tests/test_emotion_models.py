import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

from audio_pipeline.emotion_models import (
    CATEGORICAL_MODEL_NAME,
    FALLBACK_CATEGORICAL_MODEL_NAME,
    VOX_PROFILE_DIR_ENV,
    CategoricalWhisperEmotionModel,
    DimensionalAffectModel,
    EmotionModelBundle,
    FallbackCategoricalEmotionModel,
    VoxProfileWhisperEmotionModel,
    normalise_dimension_scores,
    normalise_emotion_scores,
)


class FakeTorch:
    class cuda:
        @staticmethod
        def is_available():
            return False


class FakeDimensionalModel:
    def predict(self, _window_wav: Path):
        return {"Arousal": 0.1, "Dominance": 0.2, "Valence": 0.3}


class FakeCategoricalModel:
    model_name = FALLBACK_CATEGORICAL_MODEL_NAME
    model_version = "main+main-fallback"

    def predict(self, _window_wav: Path):
        return {"Happiness": 0.7, "Neutral": 0.2, "Other": 0.1}


class FakeAudioClassificationPipeline:
    def __init__(self):
        self.calls = []

    def __call__(self, sample, top_k=None):
        self.calls.append((sample, top_k))
        return [
            {"label": "Happiness", "score": 0.7},
            {"label": "Neutral", "score": 0.2},
            {"label": "Other", "score": 0.1},
        ]


class EmotionModelNormalisationTests(unittest.TestCase):
    def test_label_ids_map_to_requested_emotion_columns(self):
        scores = normalise_emotion_scores(
            [
                {"label": "LABEL_0", "score": 0.1},
                {"label": "LABEL_4", "score": 0.7},
                {"label": "LABEL_8", "score": 0.2},
            ]
        )

        self.assertEqual(scores["Anger"], 0.1)
        self.assertEqual(scores["Happiness"], 0.7)
        self.assertEqual(scores["Other"], 0.2)

    def test_missing_emotion_classes_are_blank_not_zero(self):
        scores = normalise_emotion_scores(
            [
                {"label": "ang", "score": 0.25},
                {"label": "hap", "score": 0.75},
            ]
        )

        self.assertEqual(scores["Anger"], 0.25)
        self.assertEqual(scores["Happiness"], 0.75)
        self.assertEqual(scores["Contempt"], "")
        self.assertEqual(scores["Disgust"], "")
        self.assertEqual(scores["Fear"], "")

    def test_dimensional_label_ids_map_to_arousal_dominance_valence(self):
        scores = normalise_dimension_scores(
            [
                {"label": "LABEL_0", "score": 0.6},
                {"label": "LABEL_1", "score": 0.5},
                {"label": "LABEL_2", "score": 0.4},
            ]
        )

        self.assertEqual(scores["Arousal"], 0.6)
        self.assertEqual(scores["Dominance"], 0.5)
        self.assertEqual(scores["Valence"], 0.4)

    def test_bundle_uses_fallback_categorical_model_when_preferred_is_unavailable(self):
        with (
            patch("audio_pipeline.emotion_models.import_torch", return_value=FakeTorch),
            patch("audio_pipeline.emotion_models.CategoricalWhisperEmotionModel.load", side_effect=RuntimeError("missing model")),
            patch("audio_pipeline.emotion_models.FallbackCategoricalEmotionModel.load", return_value=FakeCategoricalModel()),
            patch("audio_pipeline.emotion_models.DimensionalAffectModel.load", return_value=FakeDimensionalModel()),
        ):
            bundle = EmotionModelBundle.load(device="cpu")

        result = bundle.predict_window(Path("window.wav"))

        self.assertFalse(bundle.skipped)
        self.assertTrue(bundle.categorical_available)
        self.assertTrue(bundle.dimensional_available)
        self.assertEqual(bundle.categorical_model_name, FALLBACK_CATEGORICAL_MODEL_NAME)
        self.assertEqual(result.probabilities["Happiness"], 0.7)
        self.assertEqual(result.arousal, 0.1)
        self.assertEqual(
            bundle.errors,
            [
                "preferred categorical model unavailable; using fallback categorical model "
                f"{FALLBACK_CATEGORICAL_MODEL_NAME}. Preferred error: missing model"
            ],
        )

    def test_bundle_keeps_dimensional_outputs_when_all_categorical_models_are_unavailable(self):
        with (
            patch("audio_pipeline.emotion_models.import_torch", return_value=FakeTorch),
            patch("audio_pipeline.emotion_models.CategoricalWhisperEmotionModel.load", side_effect=RuntimeError("missing model")),
            patch("audio_pipeline.emotion_models.FallbackCategoricalEmotionModel.load", side_effect=RuntimeError("fallback missing")),
            patch("audio_pipeline.emotion_models.DimensionalAffectModel.load", return_value=FakeDimensionalModel()),
        ):
            bundle = EmotionModelBundle.load(device="cpu")

        result = bundle.predict_window(Path("window.wav"))

        self.assertFalse(bundle.skipped)
        self.assertFalse(bundle.categorical_available)
        self.assertTrue(bundle.dimensional_available)
        self.assertEqual(result.probabilities["Anger"], "")
        self.assertEqual(result.arousal, 0.1)
        self.assertEqual(
            bundle.errors,
            [
                "categorical model unavailable: preferred and fallback categorical models could not be loaded; "
                "main categorical columns will be blank. Preferred error: missing model; "
                "fallback error: fallback missing"
            ],
        )

    def test_transformers_traceback_is_not_written_as_categorical_warning(self):
        noisy_error = (
            "Could not load model tiantiaf/whisper-large-v3-msp-podcast-emotion with any of the "
            "following classes. See the original errors: Traceback (most recent call last): "
            "File transformers/pipelines/base.py ..."
        )

        with (
            patch("audio_pipeline.emotion_models.import_torch", return_value=FakeTorch),
            patch("audio_pipeline.emotion_models.CategoricalWhisperEmotionModel.load", side_effect=RuntimeError(noisy_error)),
            patch("audio_pipeline.emotion_models.FallbackCategoricalEmotionModel.load", return_value=FakeCategoricalModel()),
            patch("audio_pipeline.emotion_models.DimensionalAffectModel.load", return_value=FakeDimensionalModel()),
        ):
            bundle = EmotionModelBundle.load(device="cpu")

        self.assertEqual(
            bundle.errors,
            [
                "preferred categorical model unavailable; using fallback categorical model "
                f"{FALLBACK_CATEGORICAL_MODEL_NAME}. Preferred error: preferred categorical model could not be loaded"
            ],
        )

    def test_categorical_model_uses_standard_transformers_pipeline(self):
        fake_classifier = FakeAudioClassificationPipeline()
        pipeline_calls = []

        def fake_pipeline(*args, **kwargs):
            pipeline_calls.append((args, kwargs))
            return fake_classifier

        with (
            patch.dict(os.environ, {VOX_PROFILE_DIR_ENV: ""}),
            patch("audio_pipeline.emotion_models.import_transformers_pipeline", return_value=fake_pipeline),
            patch("audio_pipeline.emotion_models.load_audio_array", return_value=np.array([0.1, 0.2], dtype="float32")),
        ):
            model = CategoricalWhisperEmotionModel.load(FakeTorch, "cpu")
            probabilities = model.predict(Path("window.wav"))

        self.assertEqual(pipeline_calls[0][1]["task"], "audio-classification")
        self.assertEqual(pipeline_calls[0][1]["model"], CATEGORICAL_MODEL_NAME)
        self.assertEqual(pipeline_calls[0][1]["revision"], "b92dab65151206a603810ec8b72eb528b9dd983c")
        self.assertEqual(pipeline_calls[0][1]["device"], -1)
        self.assertEqual(fake_classifier.calls[0][1], None)
        self.assertEqual(probabilities["Happiness"], 0.7)
        self.assertEqual(probabilities["Neutral"], 0.2)
        self.assertEqual(probabilities["Other"], 0.1)

    def test_fallback_and_dimensional_models_use_their_immutable_revisions(self):
        pipeline_calls = []

        def fake_pipeline(*args, **kwargs):
            pipeline_calls.append((args, kwargs))
            return FakeAudioClassificationPipeline()

        processor_calls = []
        model_calls = []

        class FakeProcessor:
            @classmethod
            def from_pretrained(cls, name, **kwargs):
                processor_calls.append((name, kwargs))
                return cls()

        class FakeDimensionalLoadedModel:
            @classmethod
            def from_pretrained(cls, name, **kwargs):
                model_calls.append((name, kwargs))
                return cls()

            def to(self, _device):
                return self

            def eval(self):
                return None

        with (
            patch("audio_pipeline.emotion_models.import_transformers_pipeline", return_value=fake_pipeline),
            patch.dict(sys.modules, {"transformers": type("FakeTransformers", (), {"Wav2Vec2Processor": FakeProcessor})}),
            patch("audio_pipeline.emotion_models.build_dimensional_model_class", return_value=FakeDimensionalLoadedModel),
        ):
            fallback = FallbackCategoricalEmotionModel.load(FakeTorch, "cpu", purpose="test")
            DimensionalAffectModel.load(FakeTorch, "cpu")

        self.assertEqual(pipeline_calls[0][1]["revision"], "441a7599c3b22107314dcbd9166621c5c83f2cc5")
        self.assertEqual(fallback.model_version, "441a7599c3b22107314dcbd9166621c5c83f2cc5")
        self.assertEqual(processor_calls[0][1]["revision"], "6eba34a2485ea31cb03600241787c3a5edab8626")
        self.assertEqual(model_calls[0][1]["revision"], "6eba34a2485ea31cb03600241787c3a5edab8626")

    def test_configured_vox_profile_backend_is_tried_before_transformers(self):
        class FakeVoxProfileModel:
            model_name = CATEGORICAL_MODEL_NAME
            model_version = "main+vox-profile-release"
            load_warnings = []

            def predict(self, _window_wav: Path):
                return {"Happiness": 1.0}

        fake_model = FakeVoxProfileModel()
        with (
            patch.dict(os.environ, {VOX_PROFILE_DIR_ENV: "C:/vox-profile-release"}),
            patch("audio_pipeline.emotion_models.VoxProfileWhisperEmotionModel.load", return_value=fake_model) as load_vox,
            patch("audio_pipeline.emotion_models.import_transformers_pipeline") as load_transformers,
        ):
            model = CategoricalWhisperEmotionModel.load(FakeTorch, "cpu")

        self.assertIs(model, fake_model)
        load_vox.assert_called_once()
        load_transformers.assert_not_called()

    def test_vox_profile_loader_suppresses_torchvision_before_importing_wrapper(self):
        import tempfile
        from types import SimpleNamespace

        events = []
        model_calls = []

        class FakeLoader:
            def exec_module(self, module):
                events.append("exec_module")

                class WhisperWrapper:
                    @classmethod
                    def from_pretrained(cls, name, **kwargs):
                        model_calls.append((name, kwargs))
                        return cls()

                    def to(self, _device):
                        return self

                    def eval(self):
                        return None

                module.WhisperWrapper = WhisperWrapper

        with tempfile.TemporaryDirectory() as temp_dir:
            checkout = Path(temp_dir)
            module_path = checkout / "src" / "model" / "emotion" / "whisper_emotion.py"
            module_path.parent.mkdir(parents=True)
            module_path.write_text("# fake wrapper\n", encoding="utf-8")

            def fake_suppress():
                events.append("suppress")

            with (
                patch("audio_pipeline.emotion_models.suppress_transformers_torchvision", side_effect=fake_suppress),
                patch("audio_pipeline.emotion_models.importlib.util.spec_from_file_location", return_value=SimpleNamespace(loader=FakeLoader())),
                patch("audio_pipeline.emotion_models.importlib.util.module_from_spec", return_value=SimpleNamespace()),
            ):
                VoxProfileWhisperEmotionModel.load(FakeTorch, "cpu", checkout)

        self.assertEqual(events[:2], ["suppress", "exec_module"])
        self.assertEqual(model_calls[0][1]["revision"], "b92dab65151206a603810ec8b72eb528b9dd983c")

    def test_preferred_categorical_model_failure_does_not_auto_load_fallback(self):
        fake_classifier = FakeAudioClassificationPipeline()
        attempted_models = []

        def fake_pipeline(*args, **kwargs):
            attempted_models.append(kwargs["model"])
            if kwargs["model"] == CATEGORICAL_MODEL_NAME:
                raise ValueError("preferred model has incompatible weights")
            return fake_classifier

        with (
            patch.dict(os.environ, {VOX_PROFILE_DIR_ENV: ""}),
            patch("audio_pipeline.emotion_models.import_transformers_pipeline", return_value=fake_pipeline),
        ):
            with self.assertRaises(RuntimeError):
                CategoricalWhisperEmotionModel.load(FakeTorch, "cpu")

        self.assertEqual(attempted_models, [CATEGORICAL_MODEL_NAME])


if __name__ == "__main__":
    unittest.main()
