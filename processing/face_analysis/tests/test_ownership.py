import json

import pytest

from processing.face_analysis.ownership import (
    FACE_OWNER,
    FACE_OWNER_FILE,
    REPOSITORY_ROOT,
    prepare_face_output_root,
)


def test_face_output_must_not_overlap_input(tmp_path) -> None:
    source = tmp_path / "Videos"
    source.mkdir()

    with pytest.raises(ValueError, match="must not overlap"):
        prepare_face_output_root(source, source / "derived")


def test_face_output_rejects_repository_git_descendant(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")

    with pytest.raises(ValueError, match="Git metadata"):
        prepare_face_output_root(source, REPOSITORY_ROOT / ".git" / "face-output")


def test_nonempty_unowned_directory_is_rejected(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "reports"
    output.mkdir()
    (output / "personal.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to take over"):
        prepare_face_output_root(source, output)

    assert (output / "personal.txt").read_text(encoding="utf-8") == "keep me"


def test_empty_output_is_claimed_with_readable_owner_marker(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "reports"

    assert prepare_face_output_root(source, output) == output.resolve()
    marker = json.loads((output / FACE_OWNER_FILE).read_text(encoding="utf-8"))
    assert marker == {
        "schema_version": "1.0",
        "owner": FACE_OWNER,
        "scope": "output-root",
    }


def test_invalid_owner_marker_is_rejected(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "reports"
    output.mkdir()
    (output / FACE_OWNER_FILE).write_text('{"owner":"someone-else"}', encoding="utf-8")

    with pytest.raises(ValueError, match="marker is invalid"):
        prepare_face_output_root(source, output)


def test_recognised_pre_marker_output_is_upgraded_without_deleting_artifacts(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "reports"
    video_dir = output / "video__abcdef123456"
    video_dir.mkdir(parents=True)
    (video_dir / "face_core.csv").write_text("frame_index\n0\n", encoding="utf-8")
    (video_dir / "face_features.parquet").write_bytes(b"existing")
    (video_dir / "video_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "status": "completed",
                "media_id": "video__abcdef123456",
                "input": {"path": str(source)},
            }
        ),
        encoding="utf-8",
    )
    (output / "run_index.csv").write_text("status\ncompleted\n", encoding="utf-8")
    (output / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "status": "completed",
                "output_root": str(output.resolve()),
                "summary": {"processed": 1, "skipped": 0, "failed": 0},
                "outputs": {
                    "per_video": {
                        "core": "face_core.csv",
                        "full": "face_features.parquet",
                        "manifest": "video_manifest.json",
                    }
                },
                "videos": [{"output_relative": video_dir.name}],
            }
        ),
        encoding="utf-8",
    )

    prepare_face_output_root(source, output)

    assert (output / FACE_OWNER_FILE).is_file()
    assert (video_dir / FACE_OWNER_FILE).is_file()
    assert (video_dir / "face_features.parquet").read_bytes() == b"existing"
