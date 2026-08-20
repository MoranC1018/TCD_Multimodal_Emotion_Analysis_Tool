from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from procurement import catalog_runner as runner_module
from procurement.catalog import read_catalog
from procurement.catalog_runner import CatalogRunOptions, resolve_youtube_language, run_catalog
from procurement.procurement_beta import cli as beta_cli
from processing.audio_analysis.audio_pipeline.batch import discover_videos, validate_source_context_coverage
from processing.audio_analysis.audio_pipeline.source_context import snapshot_run_sidecars


def write_catalog(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Link", "Speaker", "Country", "Language"])
        writer.writerows(rows)


def test_youtube_language_precedence_is_separate_and_blank_when_unavailable() -> None:
    assert resolve_youtube_language({"defaultAudioLanguage": "ga", "defaultLanguage": "en"}) == "ga"
    assert resolve_youtube_language({"defaultAudioLanguage": "", "defaultLanguage": "en"}) == "en"
    assert resolve_youtube_language({}) == ""
    assert resolve_youtube_language({"youtube_language": "cy"}) == "cy"


def test_selected_local_processor_consumes_the_sealed_snapshot(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    sealed_bytes = b"sealed local media"
    local_video.write_bytes(sealed_bytes)
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", "Irish"]])
    observed: dict[str, object] = {}

    def processor(source, _output_directory: Path, _options):
        local_video.write_bytes(b"replacement after identity preflight")
        processor_path = Path(source.resolved_link)
        observed["path"] = processor_path
        observed["bytes"] = processor_path.read_bytes()
        return {}

    result = run_catalog(catalog_path, tmp_path / "run", processor=processor)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    context_path = Path(manifest["sources"][0]["output_mapping"]["video_directory"]) / "source_context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))

    assert observed["bytes"] == sealed_bytes
    assert observed["path"] != local_video.resolve()
    assert manifest["sources"][0]["local_identity"]["sha256"] == hashlib.sha256(sealed_bytes).hexdigest()
    assert context["local_identity"] == manifest["sources"][0]["local_identity"]


def test_clean_speaker_local_catalog_publishes_audio_input_from_sealed_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original = tmp_path / "local.mp4"
    sealed_bytes = b"sealed local media"
    original.write_bytes(sealed_bytes)
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", "Irish"]])
    run_root = tmp_path / "run"
    observed: dict[str, Path] = {}

    def fake_child(command: list[str], *, args) -> int:
        item_path = Path(command[command.index("--single-video-json") + 1])
        result_path = Path(command[command.index("--child-result-json") + 1])
        cache_root = Path(command[command.index("--child-run-root") + 1])
        item = json.loads(item_path.read_text(encoding="utf-8"))
        snapshot = Path(item["source_path"])
        assert snapshot != original.resolve()
        assert snapshot.read_bytes() == sealed_bytes
        observed["snapshot"] = snapshot
        cached_output = cache_root / "pooled" / "source-0001" / "stitched_imotions.mp4"
        cached_output.parent.mkdir(parents=True, exist_ok=True)
        cached_output.write_bytes(b"clean speaker output")
        beta_cli.write_json(
            result_path,
            {
                "ok": True,
                "result": {
                    "status": "ok",
                    "input_video": str(snapshot),
                    "output_dir": str(cached_output.parent),
                    "output_video": str(cached_output),
                    "message": "Synthetic clean result",
                },
            },
        )
        return 0

    def fake_nested_process(command: list[str], **_kwargs):
        snapshot = Path(command[command.index("--source") + 1])
        assert snapshot.read_bytes() == sealed_bytes
        original.write_bytes(b"mutated after catalog snapshot")
        returncode = beta_cli.main(command[3:])
        assert returncode == 0
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(beta_cli, "apply_runtime_limits", lambda _args: None)
    monkeypatch.setattr(beta_cli, "run_child_process", fake_child)
    monkeypatch.setattr(beta_cli, "video_file_is_usable", lambda _path: True)
    monkeypatch.setattr(runner_module.subprocess, "run", fake_nested_process)

    result = run_catalog(
        catalog_path,
        run_root,
        mode="clean-speaker-beta",
        options=CatalogRunOptions(
            mode="clean-speaker-beta",
            isolated_video_processes=True,
            video_cooldown_seconds=0,
        ),
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    output_directory = Path(manifest["sources"][0]["output_mapping"]["video_directory"])
    canonical_video = output_directory / "stitched_imotions.mp4"
    cached_video = output_directory / "_clean_speaker_beta_cache" / "pooled" / "source-0001" / "stitched_imotions.mp4"
    jobs = discover_videos(run_root)
    validate_source_context_coverage(run_root, jobs)
    pair = snapshot_run_sidecars(
        run_root,
        expected_source_ids={"source-0001"},
        source_bindings=[(job.input_video, job.source_context) for job in jobs],
    )

    assert original.read_bytes() == b"mutated after catalog snapshot"
    assert observed["snapshot"] != original.resolve()
    assert canonical_video.read_bytes() == b"clean speaker output"
    assert cached_video.read_bytes() == b"clean speaker output"
    assert [job.input_video for job in jobs] == [canonical_video]
    assert jobs[0].source_context["source_id"] == "source-0001"
    assert pair is not None


def test_catalog_routes_reserved_speaker_names_safely(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"media")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "CON.txt", "Ireland", "Irish"]])

    result = run_catalog(catalog_path, tmp_path / "run", selected_source_ids=[])
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    output_directory = Path(manifest["sources"][0]["output_mapping"]["video_directory"])

    assert output_directory.parent.name == "_CON.txt"
    assert len(output_directory.parent.name) <= 80


def test_catalog_rejects_an_existing_in_root_speaker_symlink_before_sidecars(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"media")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "Alias", "Ireland", "Irish"]])
    run_root = tmp_path / "run"
    real_folder = run_root / "Real"
    real_folder.mkdir(parents=True)
    alias = run_root / "Alias"
    try:
        alias.symlink_to(real_folder, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="reparse|symlink"):
        run_catalog(catalog_path, run_root, processor=lambda *_args: {})

    assert not (run_root / "source_manifest.json").exists()
    assert not (run_root / "source_metadata.csv").exists()


def test_catalog_preflights_every_source_context_conflict_before_top_sidecars(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"media")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "Speaker A", "Ireland", "Irish"]])
    run_root = tmp_path / "run"
    output_directory = run_root / "Speaker_A" / "source-0001_local"
    output_directory.mkdir(parents=True)
    conflict = output_directory / "source_context.json"
    conflict.write_bytes(b"existing researcher content")

    with pytest.raises(FileExistsError, match="source_context"):
        run_catalog(catalog_path, run_root, processor=lambda *_args: {})

    assert conflict.read_bytes() == b"existing researcher content"
    assert not (run_root / "source_manifest.json").exists()
    assert not (run_root / "source_metadata.csv").exists()


def test_runner_preserves_mixed_order_routes_only_by_speaker_and_writes_immutable_sidecars_first(
    tmp_path: Path,
) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    youtube = "https://www.youtube.com/watch?v=abcdefghijk"
    write_catalog(
        catalog_path,
        [
            ["local.mp4", "", "=Ireland", "Irish"],
            [youtube, "Speaker A", "Canada", "Researcher language"],
            [youtube, "Speaker A", "Japan", ""],
        ],
    )
    run_root = tmp_path / "run"
    processor_calls: list[tuple[str, Path]] = []
    first_manifest_bytes: list[bytes] = []
    first_metadata_bytes: list[bytes] = []

    def metadata_fetcher(video_ids: list[str]) -> dict[str, dict[str, object]]:
        assert video_ids == ["abcdefghijk"]
        return {
            "abcdefghijk": {
                "title": "A shared title",
                "duration_seconds": 42,
                "defaultAudioLanguage": "fr-CA",
                "defaultLanguage": "fr",
            }
        }

    def processor(source, output_directory: Path, _options):
        manifest_path = run_root / "source_manifest.json"
        metadata_path = run_root / "source_metadata.csv"
        assert manifest_path.exists() and metadata_path.exists(), "sidecars must exist before processing"
        context = json.loads((output_directory / "source_context.json").read_text(encoding="utf-8"))
        assert context["source_id"] == source.source_id
        assert context["catalog_sha256"] == hashlib.sha256(catalog_path.read_bytes()).hexdigest()
        assert context["run_root"] == str(run_root.resolve())
        if not first_manifest_bytes:
            first_manifest_bytes.append(manifest_path.read_bytes())
            first_metadata_bytes.append(metadata_path.read_bytes())
        processor_calls.append((source.source_id, output_directory))
        output_directory.mkdir(parents=True, exist_ok=True)
        output_video = output_directory / "stitched_imotions.mp4"
        output_video.write_bytes(b"processed")
        return {"video": str(output_video)}

    result = run_catalog(
        catalog_path,
        run_root,
        mode="standard",
        selected_source_ids=["source-0001", "source-0003"],
        metadata_fetcher=metadata_fetcher,
        processor=processor,
    )

    manifest_path = run_root / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path.read_bytes() == first_manifest_bytes[0]
    assert (run_root / "source_metadata.csv").read_bytes() == first_metadata_bytes[0]
    assert result.processed_source_ids == ("source-0001", "source-0003")
    assert [source_id for source_id, _path in processor_calls] == ["source-0001", "source-0003"]
    assert [entry["source_id"] for entry in manifest["sources"]] == [
        "source-0001",
        "source-0002",
        "source-0003",
    ]
    assert [entry["selected"] for entry in manifest["sources"]] == [True, False, True]
    assert [entry["status"] for entry in manifest["sources"]] == ["selected", "not_selected", "selected"]
    assert manifest["catalog"]["format"] == "csv"
    assert manifest["procurement_options"]["mode"] == "standard"
    assert manifest["procurement_options"]["percentage"] == 0.10
    assert manifest["procurement_options"]["max_segment_seconds"] == 30
    assert manifest["sources"][0]["system_metadata"]["youtube_language"] == ""
    assert manifest["sources"][0]["user_metadata"]["Country"] == "=Ireland"
    assert manifest["sources"][1]["system_metadata"]["youtube_language"] == "fr-CA"
    assert manifest["sources"][1]["youtube"] == {
        "video_id": "abcdefghijk",
        "url": "https://www.youtube.com/watch?v=abcdefghijk",
    }
    assert manifest["sources"][1]["user_metadata"]["Language"] == "Researcher language"

    pooled_directory = Path(manifest["sources"][0]["output_mapping"]["video_directory"])
    named_directory = Path(manifest["sources"][2]["output_mapping"]["video_directory"])
    repeated_directory = Path(manifest["sources"][1]["output_mapping"]["video_directory"])
    assert pooled_directory.parent == run_root
    assert named_directory.parent == run_root / "Speaker_A"
    assert repeated_directory.parent == run_root / "Speaker_A"
    assert named_directory != repeated_directory
    assert not (run_root / "=Ireland").exists(), "metadata must never create folders"

    with (run_root / "source_metadata.csv").open(encoding="utf-8-sig", newline="") as handle:
        metadata_rows = list(csv.DictReader(handle))
    assert [row["SourceID"] for row in metadata_rows] == ["source-0001", "source-0002", "source-0003"]
    assert metadata_rows[0]["Country"] == "'=Ireland"
    assert metadata_rows[1]["Language"] == "Researcher language"
    assert metadata_rows[1]["YouTubeLanguage"] == "fr-CA"


def test_manifest_records_complete_mode_options_and_source_context(tmp_path: Path) -> None:
    catalog_path = tmp_path / "sources.csv"
    write_catalog(
        catalog_path,
        [["https://www.youtube.com/watch?v=abcdefghijk", "Speaker A", "Ireland", "Irish"]],
    )
    segments = tmp_path / "segments.json"
    segments.write_text("{}", encoding="utf-8")
    options = CatalogRunOptions(
        mode="clean-speaker-beta",
        percentage=0.25,
        max_segment_seconds=45,
        output_mode="percentage",
        min_clean_seconds=12.0,
        only_video_ids=("abcdefghijk",),
        random_one=True,
        keep_debug=True,
    )

    run_catalog(
        catalog_path,
        tmp_path / "run",
        selected_source_ids=["source-0001"],
        options=options,
        processor=lambda *_args: {},
    )

    manifest = json.loads((tmp_path / "run" / "source_manifest.json").read_text(encoding="utf-8"))
    assert manifest["procurement_options"]["mode"] == "clean-speaker-beta"
    assert manifest["procurement_options"]["percentage"] == 0.25
    assert manifest["procurement_options"]["max_segment_seconds"] == 45
    assert manifest["procurement_options"]["output_mode"] == "percentage"
    assert manifest["procurement_options"]["only_video_ids"] == ["abcdefghijk"]
    assert manifest["procurement_options"]["random_one"] is True
    context_path = Path(manifest["sources"][0]["output_mapping"]["video_directory"]) / "source_context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["source_id"] == "source-0001"
    assert context["speaker"] == "Speaker A"
    assert context["user_metadata"] == {"Country": "Ireland", "Language": "Irish"}


def test_default_processor_dispatches_local_standard_and_full_to_existing_adapters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    source = read_catalog(catalog_path).sources[0]
    calls: list[tuple[str, Path, Path, float, int]] = []

    def standard(video: Path, target: Path, percentage: float, maximum: int) -> None:
        calls.append(("standard", video, target, percentage, maximum))

    def full(video: Path, target: Path) -> None:
        calls.append(("full", video, target, 0.0, 0))

    monkeypatch.setattr("application.local_videos.create_standard_sample", standard)
    monkeypatch.setattr("application.local_videos.create_full_video", full)
    output = tmp_path / "run" / "source-0001_local"
    output.mkdir(parents=True)

    runner_module._default_source_processor(
        source,
        output,
        CatalogRunOptions(mode="standard", percentage=0.3, max_segment_seconds=55),
    )
    runner_module._default_source_processor(source, output, CatalogRunOptions(mode="full"))

    assert calls == [
        ("standard", local_video.resolve(), output / "stitched_imotions.mp4", 0.3, 55),
        ("full", local_video.resolve(), output / "stitched_imotions.mp4", 0.0, 0),
    ]


def test_default_processor_routes_youtube_standard_full_and_clean_through_existing_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog_path = tmp_path / "sources.csv"
    youtube = "https://www.youtube.com/watch?v=abcdefghijk"
    write_catalog(catalog_path, [[youtube, "", "Ireland", ""]])
    source = read_catalog(catalog_path).sources[0]
    output = tmp_path / "run" / "source-0001_video"
    output.mkdir(parents=True)
    calls: list[tuple[str, object]] = []

    def extract(**kwargs):
        calls.append(("standard", kwargs))
        return output / "downloaded"

    def full(**kwargs):
        calls.append(("full", kwargs))
        return output / "downloaded-full"

    def run(command, **kwargs):
        calls.append(("clean", (command, kwargs)))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        "procurement.video_sampling.run_docx_extractions.extract_or_reuse_folder",
        extract,
    )
    monkeypatch.setattr("procurement.run_pipeline.run_full_video_download", full)
    monkeypatch.setattr(runner_module.subprocess, "run", run)

    runner_module._default_source_processor(source, output, CatalogRunOptions(mode="standard"))
    runner_module._default_source_processor(source, output, CatalogRunOptions(mode="full"))
    runner_module._default_source_processor(
        source,
        output,
        CatalogRunOptions(
            mode="clean-speaker-beta",
            output_mode="percentage",
            percentage=0.2,
            max_segment_seconds=40,
            only_video_ids=("abcdefghijk",),
            keep_debug=True,
        ),
    )

    assert [kind for kind, _details in calls] == ["standard", "full", "clean"]
    standard = calls[0][1]
    assert standard["video_id"] == "abcdefghijk"
    assert standard["working_folder"] == output
    full = calls[1][1]
    assert full["item"].video_id == "abcdefghijk"
    assert full["speaker_folder"] == output
    clean_command = calls[2][1][0]
    assert clean_command[clean_command.index("--source") + 1] == youtube
    assert clean_command[clean_command.index("--output-root") + 1] == str(output)
    assert clean_command[clean_command.index("--output-mode") + 1] == "percentage"
    assert "--keep-debug" in clean_command


def test_clean_speaker_nested_child_receives_only_huggingface_credential(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["https://www.youtube.com/watch?v=abcdefghijk", "", "", ""]])
    source = read_catalog(catalog_path).sources[0]
    output = tmp_path / "run" / "source-0001_video"
    output.mkdir(parents=True)
    captured: dict[str, object] = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setenv("YOUTUBE_API_KEY", "youtube-secret")
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "alias-secret")
    monkeypatch.setattr(runner_module.subprocess, "run", run)

    runner_module._default_source_processor(
        source,
        output,
        CatalogRunOptions(mode="clean-speaker-beta"),
    )

    child_environment = captured["kwargs"]["env"]
    assert child_environment["HF_TOKEN"] == "hf-secret"
    assert "YOUTUBE_API_KEY" not in child_environment
    assert "HUGGINGFACE_TOKEN" not in child_environment


def test_manual_processor_authorizes_segments_by_source_id_and_exact_source(tmp_path: Path, monkeypatch) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    source = read_catalog(catalog_path).sources[0]
    payload = {
        "source_path": str(catalog_path.resolve()),
        "processing_source_path": str(catalog_path.resolve()),
        "gap_seconds": 0.5,
        "selected_segments": [
            {
                "source_id": "source-0001",
                "source_kind": "file",
                "source_path": str(local_video.resolve()),
                "speaker": "Pooled (no speaker)",
                "start_seconds": 1,
                "end_seconds": 2,
            },
            {
                "source_id": "source-9999",
                "source_kind": "file",
                "source_path": str(local_video.resolve()),
                "start_seconds": 3,
                "end_seconds": 4,
            },
        ],
    }
    raw = (json.dumps(payload) + "\n").encode("utf-8")
    manifest_path = tmp_path / "segments.json"
    manifest_path.write_bytes(raw)
    observed: dict[str, object] = {}

    def process(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs

    monkeypatch.setattr("application.manual_segments.process_one_video", process)
    options = CatalogRunOptions(
        mode="manual",
        segments_json=str(manifest_path),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        expected_source=str(catalog_path.resolve()),
        catalog_path=str(catalog_path.resolve()),
        focus_payload=payload,
    )
    output = tmp_path / "run" / "source-0001_local"
    output.mkdir(parents=True)

    runner_module._default_source_processor(source, output, options)

    assert observed["args"][2] == local_video.resolve()
    assert [item["source_id"] for item in observed["args"][3]] == ["source-0001"]
    assert observed["kwargs"]["target_directory"] == output


def test_cli_constructs_complete_options_for_focus_and_clean_speaker_flags(tmp_path: Path) -> None:
    manifest = tmp_path / "segments.json"
    manifest.write_text("{}", encoding="utf-8")
    args = runner_module.build_parser().parse_args(
        [
            str(tmp_path / "sources.csv"),
            "--run-root",
            str(tmp_path / "run"),
            "--mode",
            "clean-speaker-beta",
            "--percentage",
            "0.25",
            "--max-segment-seconds",
            "45",
            "--segments-json",
            str(manifest),
            "--manifest-sha256",
            "b" * 64,
            "--expected-source",
            str(tmp_path / "sources.csv"),
            "--output-mode",
            "percentage",
            "--min-clean-seconds",
            "12",
            "--only-video-id",
            "abcdefghijk",
            "--random-one",
            "--keep-debug",
            "--parallel-detectors",
        ]
    )

    options = runner_module._options_from_args(args)

    assert options.mode == "clean-speaker-beta"
    assert options.percentage == 0.25
    assert options.max_segment_seconds == 45
    assert options.segments_json == str(manifest.resolve())
    assert options.manifest_sha256 == "b" * 64
    assert options.output_mode == "percentage"
    assert options.min_clean_seconds == 12
    assert options.only_video_ids == ("abcdefghijk",)
    assert options.random_one is True
    assert options.keep_debug is True
    assert options.parallel_detectors is True


def test_runner_rejects_unknown_or_duplicate_selected_source_ids(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])

    for selected in (["missing"], ["source-0001", "source-0001"]):
        try:
            run_catalog(catalog_path, tmp_path / "run", selected_source_ids=selected, processor=lambda *_: {})
        except ValueError as error:
            assert "selected source" in str(error).casefold()
        else:
            raise AssertionError(f"selection {selected!r} should be rejected")


def test_runner_binds_source_ids_to_the_scanned_catalog_digest(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"version one")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    scanned_digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    write_catalog(catalog_path, [["local.mp4", "Speaker Changed", "Ireland", ""]])

    with pytest.raises(ValueError, match="changed since it was scanned"):
        run_catalog(
            catalog_path,
            tmp_path / "run",
            selected_source_ids=["source-0001"],
            expected_catalog_sha256=scanned_digest,
            processor=lambda *_args: {},
        )
    assert not (tmp_path / "run" / "source_manifest.json").exists()
    assert not (tmp_path / "run" / "source_metadata.csv").exists()


def test_runner_records_canonical_local_file_identity(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"version one")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])

    run_catalog(catalog_path, tmp_path / "run", selected_source_ids=[], processor=lambda *_args: {})
    entry = json.loads((tmp_path / "run" / "source_manifest.json").read_text(encoding="utf-8"))["sources"][0]

    assert entry["local_identity"] == {
        "canonical_path": str(local_video.resolve()),
        "sha256": hashlib.sha256(b"version one").hexdigest(),
        "size_bytes": len(b"version one"),
    }


def test_runner_rejects_preexisting_output_symlink_that_escapes_run_root(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "Speaker A", "Ireland", ""]])
    run_root = tmp_path / "run"
    run_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, run_root / "Speaker_A", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="escapes the selected run root"):
        run_catalog(catalog_path, run_root, selected_source_ids=[], processor=lambda *_args: {})
    assert not (run_root / "source_manifest.json").exists()
    assert not (run_root / "source_metadata.csv").exists()


def test_sidecar_pair_preflight_never_writes_only_one_file(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    run_root = tmp_path / "run"
    run_root.mkdir()
    metadata_path = run_root / "source_metadata.csv"
    metadata_path.write_bytes(b"conflicting existing metadata")

    with pytest.raises(FileExistsError, match="Immutable source sidecar"):
        run_catalog(catalog_path, run_root, selected_source_ids=[], processor=lambda *_args: {})
    assert not (run_root / "source_manifest.json").exists()
    assert metadata_path.read_bytes() == b"conflicting existing metadata"


def test_sidecar_existing_content_comparison_is_size_preflighted_and_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "source_manifest.json").write_bytes(b"x" * (2 * 1024 * 1024))
    original_read_bytes = Path.read_bytes

    def reject_unbounded_read(path: Path) -> bytes:
        if path.name in {"source_manifest.json", "source_metadata.csv"}:
            raise AssertionError("immutable sidecars must never use unbounded read_bytes")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_read)
    with pytest.raises(FileExistsError, match="different content"):
        run_catalog(catalog_path, run_root, selected_source_ids=[], processor=lambda *_args: {})


@pytest.mark.parametrize(
    "options",
    [
        CatalogRunOptions(mode="standard", percentage=float("nan")),
        CatalogRunOptions(mode="standard", percentage=float("inf")),
        CatalogRunOptions(mode="standard", max_segment_seconds=0),
        CatalogRunOptions(mode="clean-speaker-beta", scan_fps=float("nan")),
        CatalogRunOptions(mode="clean-speaker-beta", face_confidence=1.1),
        CatalogRunOptions(
            mode="clean-speaker-beta",
            cpu_throttle_low_percent=96,
            cpu_throttle_high_percent=95,
        ),
    ],
)
def test_invalid_options_are_rejected_before_sidecar_seal(
    tmp_path: Path,
    options: CatalogRunOptions,
) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    run_root = tmp_path / "run"

    with pytest.raises(ValueError):
        run_catalog(
            catalog_path,
            run_root,
            selected_source_ids=[],
            options=options,
            processor=lambda *_args: {},
        )

    assert not (run_root / "source_manifest.json").exists()
    assert not (run_root / "source_metadata.csv").exists()


def test_focus_preflight_derives_only_segment_bearing_source_ids_in_catalog_order(
    tmp_path: Path,
) -> None:
    youtube = "https://www.youtube.com/watch?v=abcdefghijk"
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [[youtube, "", "First", ""], [youtube, "", "Second", ""]])
    payload = {
        "source_path": str(catalog_path.resolve()),
        "processing_source_path": str(catalog_path.resolve()),
        "gap_seconds": 0.5,
        "selected_segments": [
            {
                "source_id": "source-0002",
                "source_kind": "youtube",
                "source_path": youtube,
                "youtube_url": youtube,
                "video_id": "abcdefghijk",
                "speaker": "Pooled (no speaker)",
                "start_seconds": 2,
                "end_seconds": 6,
            }
        ],
    }
    raw = (json.dumps(payload) + "\n").encode("utf-8")
    focus_path = tmp_path / "focus.json"
    focus_path.write_bytes(raw)
    processed: list[str] = []
    options = CatalogRunOptions(
        mode="manual",
        segments_json=str(focus_path),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        expected_source=str(catalog_path.resolve()),
    )

    run_catalog(
        catalog_path,
        tmp_path / "run",
        selected_source_ids=["source-0001", "source-0002"],
        options=options,
        processor=lambda source, *_args: processed.append(source.source_id) or {},
    )

    manifest = json.loads((tmp_path / "run" / "source_manifest.json").read_text(encoding="utf-8"))
    assert processed == ["source-0002"]
    assert [entry["selected"] for entry in manifest["sources"]] == [False, True]


def test_focus_preflight_rejects_tampered_handoff_without_any_sidecar(
    tmp_path: Path,
) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    focus_path = tmp_path / "focus.json"
    focus_path.write_text("{}", encoding="utf-8")
    run_root = tmp_path / "run"

    with pytest.raises(ValueError):
        run_catalog(
            catalog_path,
            run_root,
            selected_source_ids=["source-0001"],
            options=CatalogRunOptions(
                mode="manual",
                segments_json=str(focus_path),
                manifest_sha256="0" * 64,
                expected_source=str(catalog_path.resolve()),
            ),
        )

    assert not (run_root / "source_manifest.json").exists()
    assert not (run_root / "source_metadata.csv").exists()


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (
            CatalogRunOptions(mode="clean-speaker-beta", only_video_ids=("bbbbbbbbbbb",)),
            ["source-0002"],
        ),
        (
            CatalogRunOptions(mode="clean-speaker-beta", skip_first_videos=1),
            ["source-0002", "source-0003"],
        ),
        (
            CatalogRunOptions(mode="clean-speaker-beta", random_one=True, random_seed="stable"),
            ["source-0001"],
        ),
    ],
)
def test_clean_catalog_collection_selectors_apply_once_before_sidecars(
    tmp_path: Path,
    options: CatalogRunOptions,
    expected: list[str],
) -> None:
    catalog_path = tmp_path / "sources.csv"
    write_catalog(
        catalog_path,
        [
            ["https://www.youtube.com/watch?v=aaaaaaaaaaa", "", "", ""],
            ["https://www.youtube.com/watch?v=bbbbbbbbbbb", "", "", ""],
            ["https://www.youtube.com/watch?v=ccccccccccc", "", "", ""],
        ],
    )
    processed: list[str] = []

    run_catalog(
        catalog_path,
        tmp_path / "run",
        selected_source_ids=["source-0001", "source-0002", "source-0003"],
        options=options,
        processor=lambda source, *_args: processed.append(source.source_id) or {},
    )

    manifest = json.loads((tmp_path / "run" / "source_manifest.json").read_text(encoding="utf-8"))
    assert processed == expected
    assert [entry["source_id"] for entry in manifest["sources"] if entry["selected"]] == expected


def test_clean_per_source_child_does_not_reapply_catalog_collection_selectors(tmp_path: Path) -> None:
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["https://www.youtube.com/watch?v=abcdefghijk", "", "", ""]])
    source = read_catalog(catalog_path).sources[0]

    command = runner_module._clean_speaker_command(
        source,
        tmp_path / "run" / "source-0001",
        CatalogRunOptions(
            mode="clean-speaker-beta",
            only_video_ids=("abcdefghijk",),
            random_one=True,
            random_seed="stable",
            skip_first_videos=3,
        ),
    )

    assert "--only-video-id" not in command
    assert "--random-one" not in command
    assert "--random-seed" not in command
    assert "--skip-first-videos" not in command


def test_sidecar_pair_rejects_dangling_symlinks_without_following_them(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    run_root = tmp_path / "run"
    run_root.mkdir()
    outside = tmp_path / "outside.json"
    manifest_path = run_root / "source_manifest.json"
    try:
        os.symlink(outside, manifest_path)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    with pytest.raises(FileExistsError, match="symlink"):
        run_catalog(catalog_path, run_root, selected_source_ids=[], processor=lambda *_args: {})
    assert manifest_path.is_symlink()
    assert not outside.exists()
    assert not (run_root / "source_metadata.csv").exists()


def test_sidecar_pair_rolls_back_first_publish_if_second_publish_fails(tmp_path: Path, monkeypatch) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    run_root = tmp_path / "run"
    real_link = os.link

    def fail_metadata_publish(source, destination, *args, **kwargs):
        if Path(destination).name == "source_metadata.csv":
            raise OSError("synthetic second publish failure")
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", fail_metadata_publish)
    with pytest.raises(OSError, match="synthetic second publish failure"):
        run_catalog(catalog_path, run_root, selected_source_ids=[], processor=lambda *_args: {})
    assert not (run_root / "source_manifest.json").exists()
    assert not (run_root / "source_metadata.csv").exists()


def test_sidecar_comparison_rejects_a_same_byte_replacement_during_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "source_manifest.json"
    replacement = tmp_path / "replacement.json"
    target.write_bytes(b"same bytes")
    replacement.write_bytes(b"same bytes")
    real_open = Path.open
    replaced = False

    def replace_before_open(path: Path, *args, **kwargs):
        nonlocal replaced
        if path == target and not replaced:
            replaced = True
            replacement.replace(target)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replace_before_open)

    assert not runner_module._regular_file_matches(target, b"same bytes")


def test_sidecar_rollback_preserves_a_concurrent_same_byte_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "source_manifest.json"
    metadata_path = tmp_path / "source_metadata.csv"
    real_link = os.link

    def replace_then_fail(source, destination, *args, **kwargs):
        destination_path = Path(destination)
        if destination_path == metadata_path:
            manifest_path.unlink()
            manifest_path.write_bytes(b"manifest")
            raise OSError("synthetic second publish race")
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", replace_then_fail)

    with pytest.raises(OSError, match="synthetic second publish race"):
        runner_module._write_immutable_sidecar_pair(
            (manifest_path, b"manifest"),
            (metadata_path, b"metadata"),
        )

    assert manifest_path.read_bytes() == b"manifest"
    assert not metadata_path.exists()


def test_reusing_sidecars_with_a_different_procurement_mode_is_rejected(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    write_catalog(catalog_path, [["local.mp4", "", "Ireland", ""]])
    run_root = tmp_path / "run"
    run_catalog(catalog_path, run_root, mode="standard", selected_source_ids=[], processor=lambda *_args: {})

    with pytest.raises(FileExistsError, match="different content"):
        run_catalog(catalog_path, run_root, mode="full", selected_source_ids=[], processor=lambda *_args: {})


def test_metadata_csv_neutralizes_arbitrary_headers_while_manifest_keeps_original_labels(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    with catalog_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Link", "=Category"])
        writer.writerow(["local.mp4", "@value"])

    run_catalog(catalog_path, tmp_path / "run", selected_source_ids=[], processor=lambda *_args: {})
    manifest = json.loads((tmp_path / "run" / "source_manifest.json").read_text(encoding="utf-8"))
    with (tmp_path / "run" / "source_metadata.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    assert manifest["catalog"]["metadata_headers"] == ["=Category"]
    assert manifest["sources"][0]["user_metadata"] == {"=Category": "@value"}
    assert "'=Category" in rows[0]
    category_index = rows[0].index("'=Category")
    assert rows[1][category_index] == "'@value"


def test_metadata_csv_allocates_collision_free_headers_without_losing_values(tmp_path: Path) -> None:
    local_video = tmp_path / "local.mp4"
    local_video.write_bytes(b"synthetic video")
    catalog_path = tmp_path / "sources.csv"
    with catalog_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Link", "SourceID", "Metadata: SourceID", "=Category", "'=Category"])
        writer.writerow(["local.mp4", "research-id", "secondary-id", "formula", "literal"])

    run_catalog(catalog_path, tmp_path / "run", selected_source_ids=[], processor=lambda *_args: {})

    manifest = json.loads((tmp_path / "run" / "source_manifest.json").read_text(encoding="utf-8"))
    export_map = manifest["catalog"]["metadata_export_headers"]
    with (tmp_path / "run" / "source_metadata.csv").open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert len(row) == 16
    assert row[export_map["SourceID"]] == "research-id"
    assert row[export_map["Metadata: SourceID"]] == "secondary-id"
    assert row["'" + export_map["=Category"]] == "formula"
    assert row[export_map["'=Category"]] == "literal"
    assert len(set(row)) == len(row)
