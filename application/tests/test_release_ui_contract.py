from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


UI_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = UI_ROOT.parent

NODE_OVERRIDE = "MEAP_TEST_NODE"
PLAYWRIGHT_OVERRIDE = "MEAP_TEST_PLAYWRIGHT"
BROWSER_OVERRIDE = "MEAP_TEST_BROWSER_EXECUTABLE"
STRICT_BROWSER_TESTS = "MEAP_STRICT_BROWSER_TESTS"


class BrowserAutomationUnavailable(RuntimeError):
    """Raised when an optional real-browser smoke dependency cannot be resolved."""


def _configured_file(value: str, *, which=shutil.which) -> str | None:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return str(candidate)
    resolved = which(value)
    return str(resolved) if resolved else None


def resolve_node_command(*, env=None, which=shutil.which, home=None) -> str:
    environment = os.environ if env is None else env
    profile = Path.home() if home is None else Path(home)
    override = environment.get(NODE_OVERRIDE, "").strip()
    if override:
        resolved = _configured_file(override, which=which)
        if resolved:
            return resolved
        raise BrowserAutomationUnavailable(
            f"{NODE_OVERRIDE} does not identify a Node executable: {override}"
        )

    resolved = which("node")
    if resolved:
        return str(resolved)

    runtime_root = (
        profile
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
    )
    for candidate in (
        runtime_root / "node.exe",
        runtime_root / "bin" / "node.exe",
        runtime_root / "bin" / "node",
    ):
        if candidate.is_file():
            return str(candidate)
    raise BrowserAutomationUnavailable(
        f"Node was not found. Install Node, add it to PATH, or set {NODE_OVERRIDE}."
    )


def _playwright_package(candidate: Path) -> Path | None:
    for package_root in (candidate, candidate / "playwright"):
        if (package_root / "package.json").is_file():
            return package_root
    return None


def resolve_playwright_root(
    *,
    env=None,
    project_root=None,
    home=None,
    which=shutil.which,
    run_command=subprocess.run,
) -> Path:
    environment = os.environ if env is None else env
    repository = PROJECT_ROOT if project_root is None else Path(project_root)
    profile = Path.home() if home is None else Path(home)
    override = environment.get(PLAYWRIGHT_OVERRIDE, "").strip()
    if override:
        package = _playwright_package(Path(override).expanduser())
        if package:
            return package
        raise BrowserAutomationUnavailable(
            f"{PLAYWRIGHT_OVERRIDE} must identify the Playwright package or its node_modules directory: {override}"
        )

    candidates = [repository / "node_modules" / "playwright"]
    candidates.extend(
        Path(entry.strip()).expanduser() / "playwright"
        for entry in environment.get("NODE_PATH", "").split(os.pathsep)
        if entry.strip()
    )

    npm_command = which("npm")
    if npm_command:
        try:
            completed = run_command(
                [npm_command, "root"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if completed and completed.returncode == 0 and completed.stdout.strip():
                candidates.append(Path(completed.stdout.strip()) / "playwright")
        except (OSError, subprocess.SubprocessError):
            pass

    candidates.append(
        profile
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "node_modules"
        / "playwright"
    )
    for candidate in candidates:
        package = _playwright_package(candidate)
        if package:
            return package
    raise BrowserAutomationUnavailable(
        "Playwright was not found. Install it in the project, expose it through NODE_PATH/npm root, "
        f"or set {PLAYWRIGHT_OVERRIDE}."
    )


def resolve_browser_launch_config(env=None) -> dict[str, str | bool]:
    environment = os.environ if env is None else env
    override = environment.get(BROWSER_OVERRIDE, "").strip()
    if override:
        executable = _configured_file(override)
        if not executable:
            raise BrowserAutomationUnavailable(
                f"{BROWSER_OVERRIDE} does not identify a browser executable: {override}"
            )
        return {"channel": "", "executablePath": executable, "explicitExecutable": True}

    executable = ""
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        install_root = environment.get(variable, "").strip()
        if not install_root:
            continue
        candidate = Path(install_root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if candidate.is_file():
            executable = str(candidate)
            break
    return {"channel": "msedge", "executablePath": executable, "explicitExecutable": False}


def strict_browser_tests_enabled(env=None) -> bool:
    environment = os.environ if env is None else env
    value = environment.get(STRICT_BROWSER_TESTS, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def resolve_node_for_harness(test_case: unittest.TestCase, harness_name: str) -> str:
    try:
        return resolve_node_command()
    except BrowserAutomationUnavailable as error:
        message = (
            f"Optional {harness_name} unavailable: {error} "
            f"Configure {NODE_OVERRIDE}; set {STRICT_BROWSER_TESTS}=1 to require "
            "Node-backed UI harnesses in release CI."
        )
        if strict_browser_tests_enabled():
            test_case.fail(message)
        test_case.skipTest(message)


class BrowserDependencyResolutionTests(unittest.TestCase):
    def test_node_resolution_finds_windows_bin_executable_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            node = (
                home
                / ".cache"
                / "codex-runtimes"
                / "codex-primary-runtime"
                / "dependencies"
                / "node"
                / "bin"
                / "node.exe"
            )
            node.parent.mkdir(parents=True)
            node.touch()

            self.assertEqual(
                resolve_node_command(env={}, which=lambda _name: None, home=home),
                str(node),
            )

    def test_node_resolution_uses_override_path_and_home_fallback_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            override = root / "override-node.exe"
            path_node = root / "path-node.exe"
            home_node = (
                root
                / "home"
                / ".cache"
                / "codex-runtimes"
                / "codex-primary-runtime"
                / "dependencies"
                / "node"
                / "node.exe"
            )
            for candidate in (override, path_node, home_node):
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.touch()

            self.assertEqual(
                resolve_node_command(
                    env={"MEAP_TEST_NODE": str(override)},
                    which=lambda _name: str(path_node),
                    home=root / "home",
                ),
                str(override),
            )
            self.assertEqual(
                resolve_node_command(
                    env={},
                    which=lambda _name: str(path_node),
                    home=root / "home",
                ),
                str(path_node),
            )
            self.assertEqual(
                resolve_node_command(env={}, which=lambda _name: None, home=root / "home"),
                str(home_node),
            )

    def test_playwright_resolution_checks_override_project_node_path_npm_and_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_roots = {
                name: root / name / "playwright"
                for name in ("override", "node-path", "npm")
            }
            package_roots["project"] = root / "project" / "node_modules" / "playwright"
            for package_root in package_roots.values():
                package_root.mkdir(parents=True)
                (package_root / "package.json").write_text("{}", encoding="utf-8")
            home_package = (
                root
                / "profile"
                / ".cache"
                / "codex-runtimes"
                / "codex-primary-runtime"
                / "dependencies"
                / "node"
                / "node_modules"
                / "playwright"
            )
            home_package.mkdir(parents=True)
            (home_package / "package.json").write_text("{}", encoding="utf-8")

            self.assertEqual(
                resolve_playwright_root(
                    env={"MEAP_TEST_PLAYWRIGHT": str(package_roots["override"])},
                    project_root=root / "missing-project",
                    home=root / "profile",
                    which=lambda _name: None,
                    run_command=lambda *_args, **_kwargs: None,
                ),
                package_roots["override"],
            )
            self.assertEqual(
                resolve_playwright_root(
                    env={},
                    project_root=root / "project",
                    home=root / "missing-home",
                    which=lambda _name: None,
                    run_command=lambda *_args, **_kwargs: None,
                ),
                package_roots["project"],
            )
            self.assertEqual(
                resolve_playwright_root(
                    env={"NODE_PATH": str(package_roots["node-path"].parent)},
                    project_root=root / "missing-project",
                    home=root / "missing-home",
                    which=lambda _name: None,
                    run_command=lambda *_args, **_kwargs: None,
                ),
                package_roots["node-path"],
            )
            self.assertEqual(
                resolve_playwright_root(
                    env={},
                    project_root=root / "missing-project",
                    home=root / "missing-home",
                    which=lambda name: "npm.cmd" if name == "npm" else None,
                    run_command=lambda *_args, **_kwargs: SimpleNamespace(
                        returncode=0,
                        stdout=str(package_roots["npm"].parent),
                    ),
                ),
                package_roots["npm"],
            )
            self.assertEqual(
                resolve_playwright_root(
                    env={},
                    project_root=root / "missing-project",
                    home=root / "profile",
                    which=lambda _name: None,
                    run_command=lambda *_args, **_kwargs: None,
                ),
                home_package,
            )

    def test_browser_configuration_supports_override_and_standard_edge_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            override = root / "custom" / "browser.exe"
            override.parent.mkdir()
            override.touch()
            config = resolve_browser_launch_config(
                {"MEAP_TEST_BROWSER_EXECUTABLE": str(override)},
            )
            self.assertEqual(config["executablePath"], str(override))
            self.assertTrue(config["explicitExecutable"])

            for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
                with self.subTest(variable=variable):
                    install_root = root / variable.replace("(", "_").replace(")", "")
                    edge = install_root / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                    edge.parent.mkdir(parents=True)
                    edge.touch()
                    discovered = resolve_browser_launch_config({variable: str(install_root)})
                    self.assertEqual(discovered["channel"], "msedge")
                    self.assertEqual(discovered["executablePath"], str(edge))
                    self.assertFalse(discovered["explicitExecutable"])
    def test_strict_browser_mode_accepts_common_truthy_values(self) -> None:
        for value in ("1", "true", "YES", "on"):
            with self.subTest(value=value):
                self.assertTrue(strict_browser_tests_enabled({"MEAP_STRICT_BROWSER_TESTS": value}))
        self.assertFalse(strict_browser_tests_enabled({}))
        self.assertFalse(strict_browser_tests_enabled({"MEAP_STRICT_BROWSER_TESTS": "0"}))

    def test_both_node_harnesses_use_override_with_constrained_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            node_override = root / "configured-node.exe"
            node_override.touch()
            commands = []

            def completed(command, *_args, **_kwargs):
                commands.append(command)
                output = (
                    "analysis UI behavior checks passed"
                    if len(command) == 4
                    else "analysis browser interaction checks passed"
                )
                return SimpleNamespace(returncode=0, stdout=output, stderr="")

            environment = {
                "PATH": str(root / "empty-path"),
                NODE_OVERRIDE: str(node_override),
                STRICT_BROWSER_TESTS: "",
            }
            with (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch(
                    f"{__name__}.resolve_playwright_root",
                    return_value=root / "playwright",
                ),
                mock.patch(
                    f"{__name__}.resolve_browser_launch_config",
                    return_value={
                        "channel": "msedge",
                        "executablePath": "",
                        "explicitExecutable": False,
                    },
                ),
                mock.patch(f"{__name__}.subprocess.run", side_effect=completed),
            ):
                ReleaseUiContractTests(
                    "test_analysis_behavior_contract_executes_production_logic"
                ).test_analysis_behavior_contract_executes_production_logic()
                ReleaseUiContractTests(
                    "test_analysis_browser_interactions_and_responsive_rendering"
                ).test_analysis_browser_interactions_and_responsive_rendering()

            self.assertEqual(len(commands), 2)
            self.assertTrue(all(command[0] == str(node_override) for command in commands))

    def test_node_harness_policy_skips_ordinary_and_fails_in_strict_mode(self) -> None:
        unavailable = BrowserAutomationUnavailable("Node is absent")
        probe = unittest.TestCase()
        with mock.patch(f"{__name__}.resolve_node_command", side_effect=unavailable):
            with mock.patch.dict(os.environ, {STRICT_BROWSER_TESTS: ""}, clear=False):
                with self.assertRaisesRegex(unittest.SkipTest, NODE_OVERRIDE):
                    resolve_node_for_harness(probe, "Analysis logic harness")
            with mock.patch.dict(os.environ, {STRICT_BROWSER_TESTS: "1"}, clear=False):
                with self.assertRaisesRegex(AssertionError, NODE_OVERRIDE):
                    resolve_node_for_harness(probe, "Analysis logic harness")


class CatalogUiLogicTests(unittest.TestCase):
    def test_catalog_filter_sort_and_visible_selection_logic(self) -> None:
        node_command = resolve_node_for_harness(self, "Catalog logic harness")
        completed = subprocess.run(
            [
                node_command,
                "-e",
                (UI_ROOT / "tests" / "catalog_ui_logic_harness.js").read_text(encoding="utf-8"),
                str(UI_ROOT / "static" / "app.js"),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class ReleaseUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (UI_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        cls.javascript = (UI_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        cls.styles = (UI_ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        cls.launcher = (UI_ROOT / "launcher.py").read_text(encoding="utf-8")

    def test_procurement_has_one_universal_search_control(self) -> None:
        self.assertEqual(self.html.count('id="scanButton"'), 1)
        self.assertNotIn('id="browseFolderButton"', self.html)

    def test_catalog_ui_exposes_metadata_visibility_and_explicit_source_selection(self) -> None:
        for control_id in (
            "catalogFilterField",
            "catalogFilterText",
            "catalogSortField",
            "catalogSortDirection",
            "selectVisibleSourcesButton",
            "clearVisibleSourcesButton",
        ):
            self.assertIn(f'id="{control_id}"', self.html)
        self.assertIn("CSV or DOCX catalog", self.html)
        self.assertIn("selectedSourceIds: getSelectedSourceIds()", self.javascript)
        self.assertIn("catalogSha256:", self.javascript)
        self.assertIn("source_id: video.source_id", self.javascript)
        self.assertIn("metadata: { ...(video.metadata || {}) }", self.javascript)
        self.assertIn('youtube_language: video.youtube_language || ""', self.javascript)
        self.assertNotIn('id="browseDocxButton"', self.html)
        self.assertNotIn('id="browseVideoButton"', self.html)
        self.assertIn('placeholder="Paste a YouTube URL or local path"', self.html)

    def test_audio_ui_reuses_catalog_metadata_filter_and_selected_source_ids(self) -> None:
        for control_id in (
            "audioCatalogSelection",
            "audioCatalogFilterField",
            "audioCatalogFilterText",
            "audioCatalogSortField",
            "audioCatalogSortDirection",
            "audioSelectVisibleSourcesButton",
            "audioClearVisibleSourcesButton",
            "audioCatalogSourceList",
        ):
            self.assertIn(f'id="{control_id}"', self.html)
        self.assertIn("function renderAudioCatalogSelection()", self.javascript)
        self.assertIn("selectedSourceIds: getAudioSelectedSourceIds()", self.javascript)
        self.assertIn('api("/api/audio-catalog"', self.javascript)
        self.assertIn("catalogSources(state.audioCatalog)", self.javascript)
        self.assertIn("state.audioSelectedSourceIds", self.javascript)
        self.assertIn('catalogSha256: selectedSourceIds.length && isCatalogScan(state.audioCatalog)', self.javascript)
        self.assertIn('audioSourcePathInput.addEventListener("input", clearAudioCatalogSelection)', self.javascript)

    def test_stage_tiles_use_research_workflow_wording(self) -> None:
        for title, subtitle in (
            ("Procurement", "Source collection and preprocessing"),
            ("Processing", "Generate or import modality results"),
            ("Analysis", "Postprocessing and reporting"),
        ):
            with self.subTest(title=title):
                self.assertIn(f'<strong class="stage-title">{title}</strong>', self.html)
                self.assertIn(f'<small class="stage-subtitle">{subtitle}</small>', self.html)

    def test_readme_does_not_reference_removed_real_data_captures(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("docs/images/user-manual/", readme)

    def test_blank_procurement_search_offers_modern_folder_or_file_pickers(self) -> None:
        self.assertIn('id="sourcePickerDialog"', self.html)
        self.assertIn('id="chooseSourceFolderButton"', self.html)
        self.assertIn('id="chooseSourceFileButton"', self.html)
        self.assertIn('chooseProcurementSource("folder")', self.javascript)
        self.assertIn('chooseProcurementSource("source-file")', self.javascript)
        self.assertIn("return selectedPath;", self.javascript)
        self.assertNotIn('setStatus("Enter a YouTube URL, local folder, DOCX list, or video file.");', self.javascript)

    def test_supported_formats_are_explicit_and_docx_wording_is_consistent(self) -> None:
        for expected in ("YouTube URL", "Folder tree", "CSV or DOCX catalog", "Local video"):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.html)
        for extension in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
            with self.subTest(extension=extension):
                self.assertIn(extension, self.html)
        self.assertNotIn("Word list", self.html)

    def test_focus_has_gap_only_and_synced_timecode_controls(self) -> None:
        self.assertIn('id="focusGapInput"', self.html)
        self.assertNotIn("focusMaxSegmentInput", self.html)
        self.assertIn('id="timelinePlayhead"', self.html)
        self.assertIn('id="playbackTimeLabel"', self.html)
        self.assertIn("Start (MM:SS)", self.html)
        self.assertIn("End (MM:SS)", self.html)
        self.assertIn("parseEditableTimecode", self.javascript)
        self.assertIn("loadYouTubeIframeAt", self.javascript)
        self.assertIn("gap_seconds:", self.javascript)
        self.assertNotIn("max_segment_length_seconds:", self.javascript)

    def test_focus_supports_selection_deletion_snapping_and_edge_resizing(self) -> None:
        self.assertIn('id="deleteSegmentButton"', self.html)
        self.assertIn("deleteSelectedSegment", self.javascript)
        self.assertIn("snapFocusTime", self.javascript)
        self.assertIn("beginSegmentResize", self.javascript)
        self.assertIn("nudgeSegmentEdge", self.javascript)
        self.assertIn("segmentDialog.addEventListener(\"close\", cleanupSegmentDialog)", self.javascript)
        self.assertIn("touch-action: none", self.styles)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('role="slider"', self.html)
        self.assertIn('timeline.addEventListener("keydown"', self.javascript)

    def test_focus_youtube_iframe_fills_the_sixteen_by_nine_player(self) -> None:
        self.assertRegex(
            self.styles,
            r"\.youtube-player iframe\s*\{[^}]*height:\s*100%;",
        )

    def test_focus_youtube_preview_executes_no_remote_parent_script(self) -> None:
        self.assertIn("https://www.youtube-nocookie.com/embed/", self.javascript)
        self.assertNotIn("youtube.com/iframe_api", self.javascript)
        self.assertNotIn("new YT.Player", self.javascript)
        self.assertNotIn("window.onYouTubeIframeAPIReady", self.javascript)

    def test_dialogs_have_accessible_names(self) -> None:
        self.assertIn('aria-labelledby="segmentDialogTitle"', self.html)
        self.assertIn('aria-labelledby="settingsDialogTitle"', self.html)
        self.assertIn('aria-labelledby="sourcePickerDialogTitle"', self.html)

    def test_guided_workflow_tracks_exact_runs_and_validates_imports(self) -> None:
        self.assertIn("advanceGuidedWorkflow", self.javascript)
        self.assertIn("state.activeRunIds", self.javascript)
        self.assertIn('api("/api/validate-path"', self.javascript)
        self.assertIn("runMatchesUi", self.javascript)

    def test_analysis_has_exactly_video_audio_and_text_cards(self) -> None:
        self.assertEqual(self.html.count('class="analysis-modality-card"'), 3)
        self.assertEqual(
            self.html.count('data-analysis-modality="video"'),
            1,
        )
        self.assertEqual(self.html.count('data-analysis-modality="audio"'), 1)
        self.assertEqual(self.html.count('data-analysis-modality="text"'), 1)
        for element_id in (
            "analysisVideoEnabled",
            "analysisVideoSourcePath",
            "browseAnalysisVideoSource",
            "analysisVideoProviderStatus",
            "analysisAudioEnabled",
            "analysisAudioSourcePath",
            "browseAnalysisAudioSource",
            "analysisTextEnabled",
            "analysisTextSourcePath",
            "browseAnalysisTextSource",
            "analysisTextImportMethod",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)
        self.assertNotIn('id="analysisTextEnabled" type="checkbox" disabled', self.html)
        self.assertNotIn('id="analysisTextRunMethod"', self.html)
        self.assertIn("Import completed transcript construct results.", self.html)
        self.assertNotIn('name="analysisMode"', self.html)
        self.assertNotIn('data-analysis-modality="imotions"', self.html.lower())
        self.assertNotIn('data-analysis-modality="native_face"', self.html.lower())
        self.assertNotIn('id="analysisImotions', self.html)
        self.assertNotIn('id="analysisNativeFace', self.html)

    def test_analysis_cards_have_independent_source_methods(self) -> None:
        for modality in ("Video", "Audio"):
            with self.subTest(modality=modality):
                self.assertIn(f'name="analysis{modality}SourceMethod"', self.html)
                self.assertIn(f'id="analysis{modality}RunMethod"', self.html)
                self.assertIn(f'id="analysis{modality}ImportMethod"', self.html)
        self.assertIn('name="analysisTextSourceMethod"', self.html)
        self.assertIn('id="analysisTextImportMethod"', self.html)
        self.assertNotIn('id="analysisTextRunMethod"', self.html)
        self.assertGreaterEqual(self.html.count('value="run"'), 2)
        self.assertGreaterEqual(self.html.count('value="import"'), 3)

    def test_analysis_sends_one_multi_modality_payload(self) -> None:
        self.assertIn('api("/api/run-analysis-workflow"', self.javascript)
        self.assertIn("buildAnalysisModalities", self.javascript)
        self.assertIn("buildAnalysisProfilePayload", self.javascript)
        self.assertIn("analysisProfile,", self.javascript)
        self.assertNotIn('api("/api/run-analysis"', self.javascript)
        self.assertNotIn("analysisModeInputs", self.javascript)

    def test_analysis_has_nested_metadata_customization_and_mixed_manual_groups(self) -> None:
        for element_id in (
            "analysisCustomizeScreen",
            "openAnalysisCustomizeButton",
            "discoverAnalysisSpeakersButton",
            "analysisSpeakerDiscoveryStatus",
            "analysisSortFields",
            "analysisAutomaticGroupField",
            "analysisMetadataFilters",
            "analysisSpeakerGroups",
            "addAnalysisSpeakerGroupButton",
            "analysisProfilePreview",
            "saveAnalysisCustomizationButton",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('api("/api/analysis-profile-context"', self.javascript)
        self.assertIn("discoverAnalysisSpeakers", self.javascript)
        self.assertIn("renderAnalysisSpeakerGroups", self.javascript)
        self.assertIn("assignAnalysisProfileMember", self.javascript)
        self.assertIn("whole speaker or individual source", self.html)
        self.assertIn("belongs to more than one manual group", self.javascript)

    def test_analysis_profile_defaults_keep_all_sources_without_fixed_caps(self) -> None:
        self.assertNotIn("HISTORICAL_ANALYSIS_GROUPS", self.javascript)
        self.assertNotIn("canUseHistoricalAnalysisGroups", self.javascript)
        self.assertIn("createAnalysisProfileDraft", self.javascript)
        self.assertNotIn("supports at most four speaker groups", self.javascript)
        self.assertNotIn("maximum of three speakers", self.javascript)

    def test_analysis_common_and_face_only_options_are_scoped(self) -> None:
        for element_id in (
            "analysisOutputRootInput",
            "analysisWriteCombinedToggle",
            "analysisWorkbookName",
            "analysisDefaultReferenceInput",
            "analysisReferenceOverridesInput",
            "analysisConstructComparisonToggle",
            "analysisProbabilitySheetsToggle",
            "analysisConfidenceLevelInput",
            "analysisHeadlinePolicySelect",
            "analysisGraphsToggle",
            "analysisLogscaleToggle",
            "analysisFaceAdvanced",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)
        self.assertRegex(
            self.html,
            r'<details id="analysisFaceAdvanced" class="advanced-options">',
        )
        self.assertIn("shouldShowAnalysisFaceOptions", self.javascript)
        self.assertIn(
            '<output id="analysisWorkbookName" class="fixed-value">combined_analysis.xlsx</output>',
            self.html,
        )
        self.assertIn("Audio|Arousal", self.html)
        self.assertIn('id="analysisConstructComparisonToggle" type="checkbox" checked', self.html)
        self.assertIn('id="analysisProbabilitySheetsToggle" type="checkbox" checked', self.html)
        self.assertIn('id="analysisConfidenceLevelInput" type="number"', self.html)
        self.assertIn('value="95"', self.html)
        self.assertIn('<option value="weighted" selected>', self.html)

    def test_analysis_guided_hydration_keeps_modalities_independent(self) -> None:
        self.assertIn("hydrateAnalysisModalitiesFromImports", self.javascript)
        self.assertIn("analysisVideoControls", self.javascript)
        self.assertNotIn("analysisNativeFaceControls", self.javascript)
        self.assertIn("hydrateAnalysisModality(analysisAudioControls", self.javascript)
        self.assertIn("hydrateAnalysisModality(analysisTextControls", self.javascript)
        self.assertIn("resetAnalysisForNewWorkflow", self.javascript)
        self.assertNotIn("hydrateAnalysisSourceFromImports", self.javascript)

    def test_analysis_guided_hydration_uses_new_audio_run_output(self) -> None:
        start = self.javascript.index("function hydrateAnalysisModalitiesFromImports()")
        end = self.javascript.index("function showAudioAnalysis()", start)
        hydration = self.javascript[start:end]
        self.assertIn("state.pendingAudioOutput", hydration)
        self.assertIn("audioOutputRootInput.value.trim()", hydration)

    def test_analysis_run_is_gated_and_text_import_is_submitted(self) -> None:
        self.assertIn("updateAnalysisForm", self.javascript)
        self.assertIn("hasCompleteAnalysisModality", self.javascript)
        self.assertIn("analysisProfileIssues", self.javascript)
        self.assertIn("runAnalysisButton.disabled", self.javascript)
        self.assertIn("Enable Video, Audio, or Text.", self.javascript)
        self.assertNotIn("Enable Video / iMotions, Audio, or Text.", self.javascript)
        self.assertIn(
            'const labels = { video: "Video", audio: "Audio", text: "Text" };',
            self.javascript,
        )
        self.assertNotIn('const labels = { imotions:', self.javascript)
        self.assertIn("String(analysisDefaultReferenceInput.value).trim()", self.javascript)
        self.assertIn("buildCanonicalAnalysisModalities(state.analysis)", self.javascript)

    def test_analysis_behavior_contract_executes_production_logic(self) -> None:
        """Run the logic harness through the shared portable Node resolver."""
        harness = UI_ROOT / "tests" / "analysis_ui_logic_harness.js"
        node_command = resolve_node_for_harness(self, "Analysis logic harness")
        completed = subprocess.run(
            [
                node_command,
                "-e",
                harness.read_text(encoding="utf-8"),
                str(UI_ROOT / "static" / "app.js"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"Analysis UI behavior harness failed:\n{completed.stdout}\n{completed.stderr}",
        )
        self.assertIn("analysis UI behavior checks passed", completed.stdout)

    def test_analysis_browser_interactions_and_responsive_rendering(self) -> None:
        """Run the optional real-browser smoke with portable dependency discovery.

        Overrides: MEAP_TEST_NODE, MEAP_TEST_PLAYWRIGHT, and
        MEAP_TEST_BROWSER_EXECUTABLE. Set MEAP_STRICT_BROWSER_TESTS=1 to turn
        unavailable browser automation from an actionable skip into a failure.
        """
        harness = UI_ROOT / "tests" / "analysis_ui_browser_harness.js"
        strict = strict_browser_tests_enabled()
        node_command = resolve_node_for_harness(self, "Analysis browser harness")
        try:
            playwright_root = resolve_playwright_root()
            browser_config = resolve_browser_launch_config()
        except BrowserAutomationUnavailable as error:
            message = (
                f"Optional Analysis browser smoke unavailable: {error} "
                f"Configure {NODE_OVERRIDE}, {PLAYWRIGHT_OVERRIDE}, or {BROWSER_OVERRIDE}; "
                f"set {STRICT_BROWSER_TESTS}=1 to require this smoke in release CI."
            )
            if strict:
                self.fail(message)
            self.skipTest(message)

        with tempfile.TemporaryDirectory() as screenshot_dir:
            completed = subprocess.run(
                [
                    node_command,
                    str(harness),
                    str(UI_ROOT),
                    str(playwright_root),
                    json.dumps(browser_config),
                    screenshot_dir,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        if completed.returncode == 77:
            message = (
                "Optional Analysis browser smoke could not launch Edge. "
                f"Set {BROWSER_OVERRIDE} to a Chromium-family browser executable or install Microsoft Edge; "
                f"set {STRICT_BROWSER_TESTS}=1 to require this smoke in release CI.\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
            if strict:
                self.fail(message)
            self.skipTest(message)
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"Analysis browser harness failed:\n{completed.stdout}\n{completed.stderr}",
        )
        self.assertIn("analysis browser interaction checks passed", completed.stdout)

    def test_analysis_gate_and_group_updates_are_announced(self) -> None:
        self.assertIn('id="analysisRunGateMessages"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn("aria-describedby", self.javascript)
        self.assertIn("data-analysis-focus", self.javascript)

    def test_import_only_run_options_have_independent_visibility_targets(self) -> None:
        self.assertIn('id="analysisGraphsOption"', self.html)
        self.assertIn('id="analysisLogscaleOption"', self.html)
        self.assertIn("hasAnalysisRunModality", self.javascript)

    def test_analysis_manual_group_warnings_report_source_overlap(self) -> None:
        self.assertIn("profileMemberConflict", self.javascript)
        self.assertIn("A source can belong to only one manual group", self.javascript)
        self.assertIn("analysisProfileIssues", self.javascript)

    def test_analysis_default_output_hydration_rechecks_run_gate(self) -> None:
        self.assertRegex(
            self.javascript,
            r"analysisOutputRootInput\.value = payload\.defaultAnalysisOutputRoot;\s+updateAnalysisForm\(\);",
        )

    def test_analysis_modality_grid_responds_three_two_one(self) -> None:
        self.assertRegex(
            self.styles,
            r"\.analysis-modality-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\);",
        )
        self.assertRegex(
            self.styles,
            r"@media \(max-width: 1100px\)[\s\S]*?\.analysis-modality-grid[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);",
        )
        self.assertRegex(
            self.styles,
            r"@media \(max-width: 700px\)[\s\S]*?\.analysis-modality-grid[^}]*grid-template-columns:\s*1fr;",
        )

    def test_analysis_workbook_name_cannot_overflow_its_grid_cell(self) -> None:
        self.assertRegex(
            self.styles,
            r"\.analysis-options-panel \.settings-pair\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(190px,\s*1fr\);",
        )
        self.assertRegex(self.styles, r"\.fixed-value\s*\{[^}]*overflow-wrap:\s*anywhere;")

    def test_analysis_avoids_decorative_cards_inside_cards(self) -> None:
        for pattern in (
            r"\.analysis-modality-head \.check-option\s*\{[^}]*border:\s*0;[^}]*background:\s*transparent;",
            r"\.analysis-options-panel > \.check-option\s*\{[^}]*border:\s*0;[^}]*background:\s*transparent;",
        ):
            with self.subTest(pattern=pattern):
                self.assertRegex(self.styles, pattern)

    def test_local_focus_preview_is_preferred_over_adjacent_youtube_metadata(self) -> None:
        self.assertIn("const hasLocalSource", self.javascript)
        self.assertIn("!hasLocalSource && (video.video_id || video.youtube_url)", self.javascript)

    def test_review_switches_layout_before_medium_width_overflow(self) -> None:
        self.assertIn("@media (max-width: 1279px)", self.styles)

    def test_review_has_speaker_level_selection_without_video_checkboxes(self) -> None:
        self.assertIn('id="toggleAllSpeakersButton"', self.html)
        self.assertIn('id="speakerSelectionSummary"', self.html)
        self.assertIn("selectedSpeakers: getSelectedSpeakers()", self.javascript)
        self.assertIn("Include ${group.speaker} in this run", self.javascript)
        self.assertNotIn("video-selection-checkbox", self.html)

    def test_review_removes_redundant_copyright_and_focus_length_copy(self) -> None:
        self.assertNotIn("Full video copyright warning", self.html)
        self.assertNotIn("Focus selections have no maximum length", self.html)

    def test_clean_speaker_mode_has_release_label_and_segmented_output_picker(self) -> None:
        self.assertIn("<strong>Clean speaker segments</strong>", self.html)
        self.assertNotIn("Clean speaker segments (Beta)", self.html)
        self.assertEqual(self.html.count('name="betaOutputMode"'), 2)
        self.assertIn('class="clean-output-options"', self.html)

    def test_settings_show_masked_secret_status_and_resource_limits(self) -> None:
        for element_id in (
            "youtubeApiKeyStatus",
            "huggingFaceTokenStatus",
            "resourceLimitsEnabledToggle",
            "maxCpuPercentInput",
            "maxCpuCoresInput",
            "maxGpuPercentInput",
            "ramLimitModeSelect",
            "maxRamPercentInput",
            "maxRamGbInput",
            "nativeThreadsInput",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)
        self.assertNotIn("settings.youtubeApiKey ||", self.javascript)
        self.assertNotIn("settings.huggingFaceToken ||", self.javascript)
        self.assertIn("System resources (all modes)", self.html)
        for clean_only_resource_id in (
            "betaMaxAffinityCoresInput",
            "betaNativeThreadsInput",
            "betaCpuHighInput",
            "betaCpuLowInput",
            "betaRamHighInput",
            "betaRamLowInput",
            "betaResourceGuardInput",
            "betaResourcePollInput",
            "betaResourceTimeoutInput",
        ):
            with self.subTest(clean_only_resource_id=clean_only_resource_id):
                self.assertNotIn(clean_only_resource_id, self.html)
                self.assertNotIn(clean_only_resource_id, self.javascript)

    def test_release_product_name_is_tool_not_pipeline(self) -> None:
        self.assertIn("Multimodal Emotion Analysis Tool", self.html)
        self.assertNotIn("Multimodal Emotion Analysis Pipeline", self.html)
        self.assertNotIn("MultimodalEmotionAnalysisPipeline", self.javascript)

    def test_authorized_trinity_branding_uses_the_compact_transparent_shield(self) -> None:
        expected_sha256 = {
            "trinity-main-logo.jpg": "640730cdb5df84408350754c71cc9176b3a3afebc7ea9719ae6fddff2eb3cf75",
            "trinity-shield.png": "c7f9c4e88db12c9dcc36a05fcd6e015d19590758a5ddbd4f2be2a07f3794a23e",
            "trinity-shield.ico": "cba770fa9cfa75d95435aac3c636bb025c4fe8ad329a52ced0cd799f4f315c3a",
        }
        for asset, expected_digest in expected_sha256.items():
            with self.subTest(asset=asset):
                asset_path = UI_ROOT / "static" / asset
                self.assertTrue(asset_path.is_file())
                self.assertEqual(hashlib.sha256(asset_path.read_bytes()).hexdigest(), expected_digest)
        self.assertIn('rel="icon" type="image/png" href="/static/trinity-shield.png"', self.html)
        self.assertIn('class="trinity-shield"', self.html)
        self.assertIn('src="/static/trinity-shield.png"', self.html)
        self.assertIn('alt="Trinity College Dublin crest"', self.html)
        self.assertNotIn('class="trinity-main-logo"', self.html)
        self.assertNotIn('src="/static/trinity-main-logo.jpg"', self.html)
        self.assertRegex(
            self.styles,
            r"\.mode-home-head\s*\{[^}]*display:\s*flex;[^}]*align-items:\s*center;",
        )
        self.assertRegex(
            self.styles,
            r"\.trinity-shield\s*\{[^}]*width:\s*[0-9]+px;[^}]*height:\s*auto;",
        )
        self.assertIn(
            "School of Computer Science, Trinity College Dublin, the University of Dublin",
            self.html,
        )
        self.assertIn('APP_ICON = STATIC_ROOT / "trinity-shield.ico"', self.launcher)

    def test_stage_and_face_headings_keep_explanations_in_semantic_subtitles(self) -> None:
        expected_stages = {
            "Procurement": "Source collection and preprocessing",
            "Processing": "Generate or import modality results",
            "Analysis": "Postprocessing and reporting",
        }
        for title, subtitle in expected_stages.items():
            with self.subTest(stage=title):
                self.assertGreaterEqual(
                    self.html.count(f'<strong class="stage-title">{title}</strong>'),
                    2,
                )
                self.assertGreaterEqual(
                    self.html.count(f'<small class="stage-subtitle">{subtitle}</small>'),
                    2,
                )
        self.assertIn('<h2>Face Processing</h2>', self.html)
        self.assertIn(
            '<p class="stage-subtitle">Run Py-Feat or import native Face outputs.',
            self.html,
        )
        em_dash = chr(0x2014)
        for combined_title in (
            f"Procurement {em_dash} source collection and preprocessing",
            f"Processing {em_dash} generate or import modality results",
            f"Analysis {em_dash} postprocessing and reporting",
            f"Face Processing {em_dash} Py-Feat / Native Face",
        ):
            with self.subTest(combined_title=combined_title):
                self.assertNotIn(combined_title, self.html)

    def test_native_shell_keeps_native_browse_and_fullscreen_controls(self) -> None:
        self.assertIn("window.pywebview?.api?.browse_for_path", self.javascript)
        self.assertIn('event.key !== "F11"', self.javascript)
        self.assertIn("window.pywebview?.api?.toggle_fullscreen", self.javascript)
        self.assertIn("window.setTimeout(pollStateLoop", self.javascript)
        self.assertNotIn("setInterval(pollState", self.javascript)
        self.assertIn("@media (max-width: 900px)", self.styles)
