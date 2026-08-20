from __future__ import annotations

import json
from pathlib import Path

import pytest

from processing.io_utils import exclusive_process_lock
from processing.text_analysis.contracts import file_sha256, inventory_digest
from processing.text_analysis.prepare_input import whisper_to_rocksteady as prepare_module
from processing.text_analysis.prepare_input.integrity import (
    validate_prepare_batch_artifacts,
    validate_prepared_video_tree,
)
from processing.text_analysis.prepare_input.whisper_to_rocksteady import (
    collect_json_files,
    extract_indexed_segments,
    main,
    replace_segment_directory,
)


def test_unchanged_segments_preserve_existing_files_and_mtimes(tmp_path: Path) -> None:
    video = tmp_path / "video"
    segments = [(1, "first"), (2, "second")]
    replace_segment_directory(video, "video", segments)
    before = {path.name: path.stat().st_mtime_ns for path in video.iterdir()}

    replace_segment_directory(video, "video", segments)

    after = {path.name: path.stat().st_mtime_ns for path in video.iterdir()}
    assert after == before
    assert (video / ".prepare_manifest.json").is_file()


def test_changed_segment_set_atomically_replaces_stale_files(tmp_path: Path) -> None:
    video = tmp_path / "video"
    replace_segment_directory(video, "video", [(1, "old"), (2, "stale")])

    replace_segment_directory(video, "video", [(1, "new")])

    files = list(video.glob("*.txt"))
    assert [path.name for path in files] == ["video__segment_000001.txt"]
    assert files[0].read_text(encoding="utf-8") == "new"


def test_prepared_tree_validator_detects_content_tampering(tmp_path: Path) -> None:
    video = tmp_path / "001_UK_Speaker_20250101"
    replace_segment_directory(
        video,
        video.name,
        [(1, "first"), (2, "second")],
        video_identity=f"UK/Speaker/{video.name}",
    )
    validate_prepared_video_tree(
        video, expected_identity=f"UK/Speaker/{video.name}"
    )

    next(video.glob("*__segment_000002.txt")).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_prepared_video_tree(video)


def test_empty_source_segments_are_filtered_with_an_explicit_mapping(tmp_path: Path) -> None:
    prepared = extract_indexed_segments(
        {
            "task": "transcribe",
            "segments": [
                {"id": 10, "text": "first"},
                {"id": 11, "text": "   "},
                {"id": "source-c", "text": "third"},
            ],
        }
    )
    video = tmp_path / "001_UK_Speaker_20250101"
    replace_segment_directory(
        video,
        video.name,
        prepared,
        video_identity=f"UK/Speaker/{video.name}",
    )

    assert [path.name for path in sorted(video.glob("*.txt"))] == [
        f"{video.name}__segment_000001.txt",
        f"{video.name}__segment_000002.txt",
    ]
    mapping = json.loads((video / ".prepare_manifest.json").read_text(encoding="utf-8"))
    assert mapping["schema_version"] == "2.0"
    assert mapping["video_identity"] == f"UK/Speaker/{video.name}"
    assert mapping["segment_count"] == 2
    assert mapping["segments"] == [
        {"analysis_segment_id": 1, "source_segment_index": 0, "source_segment_id": 10},
        {"analysis_segment_id": 2, "source_segment_index": 2, "source_segment_id": "source-c"},
    ]


def test_prepare_partial_failure_is_nonzero_and_preserves_previous_output(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    good = selected / "UK/Speaker/001_UK_Speaker_20250101.json"
    bad = selected / "UK/Speaker/002_UK_Speaker_20250102.json"
    good.parent.mkdir(parents=True)
    good.write_text(
        json.dumps({"task": "transcribe", "segments": [{"id": 0, "text": "valid"}]}),
        encoding="utf-8",
    )
    bad.write_text("{broken", encoding="utf-8")
    output = tmp_path / "prepared"
    output.mkdir()
    (output / ".text_pipeline_owner.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "owner": "multimodal-emotion-analysis-text",
                "stage": "prepare-batch",
            }
        ),
        encoding="utf-8",
    )
    sentinel = output / "previous.txt"
    sentinel.write_text("keep", encoding="utf-8")
    manifest = tmp_path / "prepare_manifest.json"

    return_code = main(
        [str(selected), "--output", str(output), "--batch-manifest", str(manifest)]
    )

    assert return_code == 1
    assert sentinel.read_text(encoding="utf-8") == "keep"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["summary"] == {"total": 2, "completed": 1, "failed": 1}


def test_standalone_discovery_ignores_recognized_metadata_only(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    transcript = selected / "UK/Test Speaker/001_UK_Test_Speaker_20250101.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps({"task": "transcribe", "segments": [{"id": 0, "text": "valid"}]}),
        encoding="utf-8",
    )
    (selected / ".text_pipeline_owner.json").write_text("{}", encoding="utf-8")
    (selected / "selection_manifest.json").write_text("{}", encoding="utf-8")
    (selected / "_manifests").mkdir()
    (selected / "_manifests" / "transcription_run_manifest.json").write_text(
        "{}", encoding="utf-8"
    )

    input_root, discovered = collect_json_files(selected)

    assert input_root == selected.resolve()
    assert discovered == [transcript.resolve()]

    unknown = selected / "unexpected_manifest.json"
    unknown.write_text("{}", encoding="utf-8")
    _, discovered_with_unknown = collect_json_files(selected)
    assert unknown.resolve() in discovered_with_unknown


def test_inventory_prepare_does_not_scan_unrelated_invalid_json(tmp_path: Path) -> None:
    selected = tmp_path / "selected"
    identity = "Test Speaker/YouTubeti_[abc123]"
    transcript = selected / f"{identity}.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps({"task": "transcribe", "segments": [{"id": 0, "text": "valid"}]}),
        encoding="utf-8",
    )
    foreign = selected / "unrelated" / "bad" / "layout" / "foreign.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("{broken", encoding="utf-8")
    inventory = tmp_path / "selection_manifest.json"
    inventory_files = [
        {
            "identity": identity,
            "output": f"{identity}.json",
            "status": "completed",
            "source_sha256": file_sha256(transcript),
            "variant": "eng",
        }
    ]
    inventory.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "kind": "text-language-selection",
                "status": "completed",
                "inventory_sha256": inventory_digest(inventory_files),
                "files": inventory_files,
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "prepared"
    batch_manifest = tmp_path / "prepare_manifest.json"
    assert main(
        [
            str(selected),
            "--output",
            str(output),
            "--inventory",
            str(inventory),
            "--batch-manifest",
            str(batch_manifest),
        ]
    ) == 0
    assert (output / identity / "YouTubeti_[abc123]__segment_000001.txt").is_file()
    identities, digest = validate_prepare_batch_artifacts(
        output,
        batch_manifest,
        selection_manifest_path=inventory,
    )
    assert identities == {identity}
    assert digest == json.loads(batch_manifest.read_text(encoding="utf-8"))["inventory_sha256"]


def test_standalone_prepare_lock_blocks_a_second_writer(tmp_path: Path) -> None:
    output = tmp_path / "prepared"
    lock = output.parent / f".{output.name}.prepare.lock"
    with exclusive_process_lock(lock, purpose="test prepare writer"):
        with pytest.raises(RuntimeError, match="Another process"):
            main([str(tmp_path / "missing"), "--output", str(output)])


def test_keyboard_interrupt_cleans_prepare_staging_and_marks_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "selected"
    transcript = selected / "UK/Speaker/001_UK_Speaker_20250101.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps({"task": "transcribe", "segments": [{"id": 0, "text": "valid"}]}),
        encoding="utf-8",
    )
    output = tmp_path / "prepared"
    manifest = tmp_path / "prepare_manifest.json"

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(prepare_module, "replace_segment_directory", interrupt)
    with pytest.raises(KeyboardInterrupt):
        main(
            [
                str(selected),
                "--output",
                str(output),
                "--batch-manifest",
                str(manifest),
            ]
        )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "interrupted"
    assert payload["summary"]["interrupted"] == 1
    assert not list(tmp_path.glob(".prepared_staging_*"))
    assert not (tmp_path / ".prepared.prepare.lock").exists()
