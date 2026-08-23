from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from application import backend, launcher


REPO_ROOT = Path(__file__).resolve().parents[2]


class NativeProcessingBackendTests(unittest.TestCase):
    def test_face_command_binds_every_native_and_catalog_option(self) -> None:
        command = backend.build_face_processing_command(
            backend.FaceProcessingRunRequest(
                source_path=Path(r"C:\sources"),
                output_root=Path(r"C:\face-output"),
                sample_fps=7.5,
                confidence_threshold=0.82,
                batch_size=12,
                device="cuda",
                recursive=False,
                overwrite=True,
                debug=True,
                selected_source_ids=("source-0002", "source-0001"),
                catalog_sha256="a" * 64,
            ),
            repo_root=Path(r"C:\repo"),
            python_executable=Path(r"C:\Python312\python.exe"),
        )

        self.assertEqual(command[:3], [r"C:\Python312\python.exe", "-m", "processing.face_analysis"])
        self.assertEqual(command[command.index("--sample-fps") + 1], "7.5")
        self.assertEqual(command[command.index("--face-threshold") + 1], "0.82")
        self.assertEqual(command[command.index("--batch-size") + 1], "12")
        self.assertIn("--no-recursive", command)
        self.assertIn("--overwrite", command)
        self.assertIn("--debug", command)
        self.assertEqual(
            [command[index + 1] for index, value in enumerate(command) if value == "--source-id"],
            ["source-0002", "source-0001"],
        )
        self.assertEqual(command[command.index("--catalog-sha256") + 1], "a" * 64)

    def test_face_readiness_and_model_preparation_are_separate_commands(self) -> None:
        check = backend.build_face_readiness_command(
            device="cpu", python_executable=Path("python.exe")
        )
        prepare = backend.build_face_readiness_command(
            device="cuda", prepare_models=True, python_executable=Path("python.exe")
        )

        self.assertEqual(check, ["python.exe", "-m", "processing.face_analysis", "--check", "--device", "cpu"])
        self.assertEqual(
            prepare,
            ["python.exe", "-m", "processing.face_analysis", "--prepare-models", "--device", "cuda"],
        )

    def test_text_command_binds_repeated_dictionary_category_and_catalog_flags(self) -> None:
        command = backend.build_text_processing_command(
            backend.TextProcessingRunRequest(
                source_path=Path(r"C:\sources"),
                output_root=Path(r"C:\text-output"),
                whisper_model="medium",
                whisper_device="cpu",
                whisper_language="ga",
                default_language_variant="eng",
                dictionaries=("embedded:LIWC", r"file:C:\custom\words.dic"),
                dictionary_combination="override",
                categories=("Positive", "Negative"),
                threads=3,
                force_rocksteady=True,
                write_graphs=False,
                debug=True,
                selected_source_ids=("source-0007",),
                catalog_sha256="b" * 64,
            ),
            repo_root=Path(r"C:\repo"),
            python_executable=Path("python.exe"),
        )

        self.assertEqual(command[:3], ["python.exe", "-m", "processing.text_analysis"])
        self.assertEqual(command[command.index("--whisper-language") + 1], "ga")
        self.assertEqual(
            [command[index + 1] for index, value in enumerate(command) if value == "--dictionary"],
            ["embedded:LIWC", r"file:C:\custom\words.dic"],
        )
        self.assertEqual(
            [command[index + 1] for index, value in enumerate(command) if value == "--category"],
            ["Positive", "Negative"],
        )
        for flag in ("--force-rocksteady", "--no-graphs", "--debug"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--source-id") + 1], "source-0007")
        self.assertEqual(command[command.index("--catalog-sha256") + 1], "b" * 64)

    def test_text_all_categories_is_mutually_exclusive_with_named_categories(self) -> None:
        command = backend.build_text_processing_command(
            backend.TextProcessingRunRequest(
                source_path=Path("sources"),
                output_root=Path("text-output"),
                all_categories=True,
            ),
            repo_root=Path("repo"),
            python_executable=Path("python.exe"),
        )
        self.assertIn("--all-categories", command)
        self.assertNotIn("--category", command)

        with self.assertRaisesRegex(ValueError, "all categories"):
            backend.build_text_processing_command(
                backend.TextProcessingRunRequest(
                    source_path=Path("sources"),
                    output_root=Path("text-output"),
                    all_categories=True,
                    categories=("Positive",),
                ),
                repo_root=Path("repo"),
            )

    def test_analysis_payload_normalizes_native_face_alias_to_video(self) -> None:
        modalities = launcher._analysis_modalities_from_payload(
            [{"name": "native_face", "sourceMethod": "import", "sourcePath": r"C:\face-output"}]
        )

        self.assertEqual(
            modalities,
            (backend.AnalysisModalityRunRequest("video", "import", Path(r"C:\face-output")),),
        )

    def test_launcher_parses_native_payloads_without_coercing_credentials(self) -> None:
        face = launcher.face_processing_request_from_payload(
            {
                "sourcePath": r"C:\sources",
                "outputRoot": r"C:\face-output",
                "sampleFps": 6,
                "confidenceThreshold": 0.8,
                "batchSize": 4,
                "device": "cpu",
                "recursive": True,
                "overwrite": False,
                "debug": False,
                "selectedSourceIds": ["source-0001"],
                "catalogSha256": "c" * 64,
            }
        )
        text = launcher.text_processing_request_from_payload(
            {
                "sourcePath": r"C:\sources",
                "outputRoot": r"C:\text-output",
                "whisperModel": "small",
                "whisperDevice": "auto",
                "whisperLanguage": "",
                "defaultLanguageVariant": "original",
                "dictionaries": ["embedded:LIWC"],
                "dictionaryCombination": "merge",
                "categories": ["Positive"],
                "allCategories": False,
                "threads": 2,
                "forceRocksteady": False,
                "writeGraphs": True,
                "debug": False,
                "selectedSourceIds": ["source-0001"],
                "catalogSha256": "d" * 64,
            }
        )

        self.assertEqual(face.selected_source_ids, ("source-0001",))
        self.assertEqual(text.dictionaries, ("embedded:LIWC",))
        self.assertEqual(text.categories, ("Positive",))

    def test_only_explicit_face_model_preparation_receives_huggingface_token(self) -> None:
        base = {
            "PATH": r"C:\Windows\System32",
            "SYSTEMROOT": r"C:\Windows",
            "MULTIMODAL_EMOTION_ROCKSTEADY_HOME": r"C:\RockSteady",
            "OPENSMILE_HOME": r"C:\OpenSMILE",
            "OPENSMILE_BINARY": r"C:\OpenSMILE\bin\SMILExtract.exe",
            "VOX_PROFILE_RELEASE_DIR": r"C:\VoxProfile",
            "FEAT_ARCFACE_R50_PATH": r"C:\models\arcface.pth",
            "FEAT_MULTITASK_WEIGHTS": r"C:\models\multitask.pth",
            "YOUTUBE_API_KEY": "youtube-secret",
            "HF_TOKEN": "old-token",
            "HUGGINGFACE_TOKEN": "old-token-2",
            "OPENAI_API_KEY": "unrelated-openai-secret",
            "AWS_SECRET_ACCESS_KEY": "unrelated-aws-secret",
            "AZURE_CLIENT_SECRET": "unrelated-azure-secret",
            "SECRET_ALIAS": "unrelated-secret-alias",
        }
        with patch.object(backend, "load_huggingface_token", return_value="fresh-token"):
            face_run = launcher.child_process_environment(
                ["python", "-m", "processing.face_analysis", "input"],
                base_environment=base,
            )
            face_check = launcher.child_process_environment(
                ["python", "-m", "processing.face_analysis", "--check"],
                base_environment=base,
            )
            face_prepare = launcher.child_process_environment(
                ["python", "-m", "processing.face_analysis", "--prepare-models"],
                base_environment=base,
            )
            text_run = launcher.child_process_environment(
                ["python", "-m", "processing.text_analysis", "input"],
                base_environment=base,
            )

        for environment in (face_run, face_check, text_run):
            self.assertNotIn("YOUTUBE_API_KEY", environment)
            self.assertNotIn("HF_TOKEN", environment)
            self.assertNotIn("HUGGINGFACE_TOKEN", environment)
            self.assertEqual(environment["PATH"], base["PATH"])
            self.assertEqual(environment["SYSTEMROOT"], base["SYSTEMROOT"])
        self.assertEqual(
            text_run["MULTIMODAL_EMOTION_ROCKSTEADY_HOME"],
            base["MULTIMODAL_EMOTION_ROCKSTEADY_HOME"],
        )
        self.assertEqual(face_run["FEAT_ARCFACE_R50_PATH"], base["FEAT_ARCFACE_R50_PATH"])
        audio_run = launcher.child_process_environment(
            ["python", "-m", "processing.audio_analysis", "input"],
            base_environment=base,
        )
        self.assertEqual(audio_run["OPENSMILE_HOME"], base["OPENSMILE_HOME"])
        self.assertEqual(audio_run["OPENSMILE_BINARY"], base["OPENSMILE_BINARY"])
        self.assertEqual(audio_run["VOX_PROFILE_RELEASE_DIR"], base["VOX_PROFILE_RELEASE_DIR"])
        for environment in (face_run, face_check, face_prepare, text_run):
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)
            self.assertNotIn("AZURE_CLIENT_SECRET", environment)
            self.assertNotIn("SECRET_ALIAS", environment)
        self.assertEqual(face_prepare["HF_TOKEN"], "fresh-token")
        self.assertNotIn("YOUTUBE_API_KEY", face_prepare)

    def test_readiness_handlers_return_structured_results_without_using_the_run_slot(self) -> None:
        handler = object.__new__(launcher.VideoStackUiHandler)
        responses: list[dict[str, object]] = []
        handler.send_json = responses.append
        text_payload = {
            "whisperModel": "small",
            "whisperDevice": "auto",
            "whisperLanguage": "",
            "defaultLanguageVariant": "eng",
            "dictionaries": [],
            "dictionaryCombination": "merge",
            "categories": [],
            "allCategories": True,
            "threads": 1,
            "forceRocksteady": False,
            "writeGraphs": True,
            "debug": False,
            "selectedSourceIds": [],
            "catalogSha256": "",
        }
        with (
            patch.object(backend, "face_processing_readiness", return_value={"kind": "face-processing-readiness", "ready": False}),
            patch.object(backend, "text_processing_readiness", return_value={"kind": "text-processing-readiness", "status": "not_ready"}),
            patch.object(launcher, "start_process") as start_process,
        ):
            handler.handle_face_readiness({"device": "cpu"}, prepare_models=False)
            handler.handle_text_readiness(text_payload)

        self.assertEqual(responses[0]["kind"], "face-processing-readiness")
        self.assertEqual(responses[1]["kind"], "text-processing-readiness")
        start_process.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows junction regression")
    def test_http_handlers_preserve_face_and_text_output_junctions_for_child_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "sample.mp4").write_bytes(b"not-media")
            redirect = root / "outside"
            redirect.mkdir()
            parent_junction = root / "selected-output-parent"
            linked = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(parent_junction), str(redirect)],
                check=False,
                capture_output=True,
                text=True,
            )
            if linked.returncode != 0:
                self.skipTest(f"Could not create test junction: {linked.stderr.strip()}")

            handler = object.__new__(launcher.VideoStackUiHandler)
            responses: list[dict[str, object]] = []
            handler.send_json = responses.append
            child_results: list[subprocess.CompletedProcess[str]] = []

            def run_child(command, **_kwargs):
                completed = subprocess.run(
                    command,
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                child_results.append(completed)
                return 43

            face_output = parent_junction / "face"
            text_output = parent_junction / "text"
            face_payload = {
                "sourcePath": str(source),
                "outputRoot": str(face_output),
                "sampleFps": 5,
                "confidenceThreshold": 0.7,
                "batchSize": 4,
                "device": "cpu",
                "recursive": True,
                "overwrite": False,
                "debug": False,
                "selectedSourceIds": [],
                "catalogSha256": "",
            }
            text_payload = {
                "sourcePath": str(source),
                "outputRoot": str(text_output),
                "whisperModel": "small",
                "whisperDevice": "cpu",
                "whisperLanguage": "",
                "defaultLanguageVariant": "eng",
                "dictionaries": [],
                "dictionaryCombination": "merge",
                "categories": [],
                "allCategories": True,
                "threads": 1,
                "forceRocksteady": False,
                "writeGraphs": False,
                "debug": False,
                "selectedSourceIds": [],
                "catalogSha256": "",
            }

            with (
                patch.object(launcher, "start_process", side_effect=run_child),
                patch.object(launcher.APP_STATE, "log"),
            ):
                handler.handle_run_face(face_payload)
                handler.handle_run_text(text_payload)

            self.assertEqual(len(child_results), 2)
            for response, selected_output, child in zip(
                responses,
                (face_output, text_output),
                child_results,
                strict=True,
            ):
                command = response["command"]
                self.assertEqual(
                    command[command.index("--output-root") + 1],
                    str(Path(os.path.abspath(selected_output))),
                )
                self.assertNotEqual(child.returncode, 0)
                self.assertRegex(child.stderr + child.stdout, "reparse|junction")
            self.assertEqual(tuple(redirect.iterdir()), ())


class NativeProcessingUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (REPO_ROOT / "application/static/index.html").read_text(encoding="utf-8")
        cls.javascript = (REPO_ROOT / "application/static/app.js").read_text(encoding="utf-8")

    def test_face_and_text_processing_tiles_are_enabled_nested_screens(self) -> None:
        self.assertNotIn('id="openFaceProcessingButton" class="mode-tile unavailable"', self.html)
        self.assertNotIn('id="openTextProcessingButton" class="mode-tile unavailable"', self.html)
        for element_id in (
            "faceInputScreen",
            "faceRunScreen",
            "faceSourcePathInput",
            "faceCatalogSelection",
            "checkFaceReadinessButton",
            "prepareFaceModelsButton",
            "runFaceButton",
            "faceToAnalysisButton",
            "textInputScreen",
            "textRunScreen",
            "textSourcePathInput",
            "textCatalogSelection",
            "checkTextReadinessButton",
            "runTextButton",
            "textDictionaryInput",
            "textCategorySearchInput",
            "textAllCategoriesToggle",
            "textToAnalysisButton",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)

    def test_face_text_endpoints_and_safe_dynamic_rendering_are_wired(self) -> None:
        for endpoint in (
            "/api/run-face",
            "/api/face-readiness",
            "/api/prepare-face-models",
            "/api/run-text",
            "/api/text-readiness",
            "/api/processing-catalog",
            "/api/open-output",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, self.javascript)
        self.assertIn('name: "video"', self.javascript)
        self.assertNotIn('name: "native_face"', self.javascript)
        self.assertIn("textContent", self.javascript)

    def test_completed_face_processing_hands_off_to_the_single_video_analysis_source(self) -> None:
        self.assertNotIn('data-analysis-modality="native_face"', self.html)
        self.assertEqual(self.html.count('data-analysis-modality="video"'), 1)
        self.assertIn('id="analysisVideoEnabled"', self.html)
        self.assertIn('id="analysisVideoSourcePath"', self.html)
        self.assertNotIn('id="analysisImotions', self.html)
        handoff = self.javascript.split(
            "async function importNativeFaceIntoAnalysis()", 1
        )[1].split("async function importNativeTextIntoAnalysis()", 1)[0]
        self.assertIn("analysisVideoEnabled.checked = true", handoff)
        self.assertIn(
            "analysisVideoSourcePath.value = state.pendingFaceOutput || faceOutputRootInput.value.trim()",
            handoff,
        )
        self.assertIn('setAnalysisSourceMethod(analysisVideoControls, "run")', handoff)
        self.assertNotIn("analysisNativeFace", handoff)

    def test_starting_audio_does_not_discard_completed_native_handoffs(self) -> None:
        audio_function = self.javascript.split(
            "async function runAudioProcessing()", 1
        )[1].split("async function runAnalysis()", 1)[0]
        self.assertNotIn("state.pendingFaceOutput =", audio_function)
        self.assertNotIn("state.pendingTextOutput =", audio_function)


if __name__ == "__main__":
    unittest.main()
