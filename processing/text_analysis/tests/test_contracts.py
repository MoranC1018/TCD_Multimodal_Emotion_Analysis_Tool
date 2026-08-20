from __future__ import annotations

import json
from pathlib import Path

import pytest

from processing.io_utils import exclusive_process_lock
from processing.text_analysis.contracts import text_identity_parts, validate_text_identity
from processing.text_analysis.filesystem import (
    OWNER_FILE,
    REPOSITORY_ROOT,
    assert_safe_output_target,
    create_stage_directory,
    replace_stage_directory,
)
from processing.text_analysis.selection import build_selected_whisper_tree


def _write_transcript(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"task": "transcribe", "segments": [{"id": 0, "text": text}]}),
        encoding="utf-8",
    )


def test_authoritative_selection_excludes_historical_transcripts(tmp_path: Path) -> None:
    root = tmp_path / "whisper"
    current = "UK/Test Speaker/001_UK_Test_Speaker_20250101"
    stale = "UK/Test Speaker/002_UK_Test_Speaker_20250102"
    _write_transcript(root / "eng" / f"{current}.json", "current")
    _write_transcript(root / "eng" / f"{stale}.json", "stale")

    output = tmp_path / "selected"
    count = build_selected_whisper_tree(root, output, identities=[current])

    assert count == 1
    assert (output / f"{current}.json").is_file()
    assert not (output / f"{stale}.json").exists()
    manifest = json.loads((output / "selection_manifest.json").read_text(encoding="utf-8"))
    assert [item["identity"] for item in manifest["files"]] == [current]


def test_procurement_speaker_video_identity_needs_no_country(tmp_path: Path) -> None:
    identity = "Test Speaker/YouTubeti_[abc123]"
    assert validate_text_identity(Path(identity)).as_posix() == identity
    assert text_identity_parts(Path(identity)) == (
        "",
        "Test Speaker",
        "YouTubeti_[abc123]",
    )

    root = tmp_path / "whisper"
    _write_transcript(root / "eng" / f"{identity}.json", "selected")
    output = tmp_path / "selected"

    assert build_selected_whisper_tree(root, output, identities=[identity]) == 1
    assert (output / f"{identity}.json").is_file()
    manifest = json.loads((output / "selection_manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"][0]["country"] == ""


def test_authoritative_selection_does_not_scan_unrelated_invalid_json(tmp_path: Path) -> None:
    root = tmp_path / "whisper"
    current = "UK/Test Speaker/001_UK_Test_Speaker_20250101"
    _write_transcript(root / "eng" / f"{current}.json", "current")
    (root / "eng" / "unrelated" / "bad" / "layout" / "foreign.json").parent.mkdir(
        parents=True
    )
    (root / "eng" / "unrelated" / "bad" / "layout" / "foreign.json").write_text(
        "{broken", encoding="utf-8"
    )

    output = tmp_path / "selected"
    assert build_selected_whisper_tree(root, output, identities=[current]) == 1
    assert (output / f"{current}.json").is_file()


def test_root_level_legacy_transcript_is_canonicalised(tmp_path: Path) -> None:
    root = tmp_path / "whisper"
    stem = "001_UK_Test_Speaker_20250101"
    _write_transcript(root / "eng" / f"{stem}.json", "legacy")

    output = tmp_path / "selected"
    build_selected_whisper_tree(root, output, identities=[f"UK/Test Speaker/{stem}"])

    assert (output / "UK" / "Test Speaker" / f"{stem}.json").is_file()


def test_selection_ignores_only_recognized_pipeline_metadata(tmp_path: Path) -> None:
    root = tmp_path / "whisper"
    stem = "001_UK_Test_Speaker_20250101"
    _write_transcript(root / "eng" / "UK" / "Test Speaker" / f"{stem}.json", "current")
    (root / "eng" / ".text_pipeline_owner.json").write_text("{}", encoding="utf-8")
    (root / "eng" / "_manifests").mkdir()
    (root / "eng" / "_manifests" / "transcription_run_manifest.json").write_text(
        "{}", encoding="utf-8"
    )

    output = tmp_path / "selected"
    assert build_selected_whisper_tree(root, output) == 1
    assert (output / "UK" / "Test Speaker" / f"{stem}.json").is_file()

    (root / "eng" / "unexpected_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid video name"):
        build_selected_whisper_tree(root, output)


def test_output_target_rejects_both_source_overlap_directions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="must not overlap"):
        assert_safe_output_target(source / "generated", source)
    with pytest.raises(ValueError, match="must not overlap"):
        assert_safe_output_target(tmp_path, source)


def test_text_output_target_rejects_repository_git_descendant() -> None:
    with pytest.raises(ValueError, match="Git metadata"):
        assert_safe_output_target(REPOSITORY_ROOT / ".git" / "generated-output")


def test_text_output_target_rejects_existing_symlink(tmp_path: Path) -> None:
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    linked_output = tmp_path / "linked-output"
    try:
        linked_output.symlink_to(real_output, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link, junction, or reparse"):
        assert_safe_output_target(linked_output)


def test_stage_publication_refuses_an_unowned_nonempty_target(tmp_path: Path) -> None:
    target = tmp_path / "custom-output"
    target.mkdir()
    (target / "personal.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(ValueError, match="without a valid ownership marker"):
        create_stage_directory(target, "selection")

    assert (target / "personal.txt").read_text(encoding="utf-8") == "do not delete"


def test_stage_publication_accepts_only_the_same_owned_stage(tmp_path: Path) -> None:
    target = tmp_path / "managed-output"
    target.mkdir()
    (target / OWNER_FILE).write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "owner": "multimodal-emotion-analysis-text",
                "stage": "selection",
            }
        ),
        encoding="utf-8",
    )
    (target / "old.txt").write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match stage"):
        create_stage_directory(target, "derived-view")

    staging = create_stage_directory(target, "selection")
    (staging / "new.txt").write_text("new", encoding="utf-8")
    replace_stage_directory(staging, target, "selection")

    assert not (target / "old.txt").exists()
    assert (target / "new.txt").read_text(encoding="utf-8") == "new"


def test_selection_stage_lock_blocks_a_second_writer(tmp_path: Path) -> None:
    target = tmp_path / "selected"
    lock = target.parent / f".{target.name}.selection.lock"
    with exclusive_process_lock(lock, purpose="test selection writer"):
        with pytest.raises(RuntimeError, match="Another process"):
            build_selected_whisper_tree(tmp_path / "whisper", target)
