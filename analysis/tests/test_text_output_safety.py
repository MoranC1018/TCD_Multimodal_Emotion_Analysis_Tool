from __future__ import annotations

from pathlib import Path

import pytest

from analysis.text_pipeline.ownership import (
    REPOSITORY_ROOT,
    assert_publishable_output,
    validate_output_boundaries,
)
from analysis.text_pipeline.constructs import write_construct_alignment


def test_postprocessing_output_rejects_repository_git_descendant(tmp_path: Path) -> None:
    source = tmp_path / "rocksteady"
    source.mkdir()

    with pytest.raises(ValueError, match="Git metadata"):
        validate_output_boundaries(
            REPOSITORY_ROOT / ".git" / "postprocessing-output",
            (source,),
        )


def test_postprocessing_output_allows_nonoverlapping_custom_path(tmp_path: Path) -> None:
    source = tmp_path / "rocksteady"
    source.mkdir()
    output = tmp_path / "custom" / "result"

    assert validate_output_boundaries(output, (source,)) == output.resolve()


def _write_pre_manifest_variant(root: Path) -> None:
    root.mkdir(parents=True)
    for name in (
        "descriptor_statistics_by_video.csv",
        "video_level_summary.csv",
        "speaker_level_summary.csv",
        "segment_alignment_audit.csv",
    ):
        (root / name).write_text("column\nvalue\n", encoding="utf-8")
    for name in ("POSTPROCESSING_REPORT.md", "POSTPROCESSING_REPORT_EN.md"):
        (root / name).write_text("# Report\n", encoding="utf-8")
    (root / "run_log.txt").write_text("completed\n", encoding="utf-8")
    for name in ("segment_counts", "segment_relative", "segment_level"):
        path = root / name / "UK" / "Test Speaker" / "001_UK_Test_Speaker_20250101.csv"
        path.parent.mkdir(parents=True)
        path.write_text("column\nvalue\n", encoding="utf-8")
    graph = root / "graphs" / "summary" / "plot.svg"
    graph.parent.mkdir(parents=True)
    graph.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")


def test_postprocessing_recognizes_complete_pre_manifest_pair(tmp_path: Path) -> None:
    family = tmp_path / "family"
    _write_pre_manifest_variant(family / "selected")
    _write_pre_manifest_variant(family / "extra")

    assessment = assert_publishable_output(family, scope="pair")

    assert assessment.state == "legacy"


def test_postprocessing_recognizes_legacy_pair_with_construct_alignment(tmp_path: Path) -> None:
    family = tmp_path / "family"
    for variant in ("selected", "extra"):
        child = family / variant
        _write_pre_manifest_variant(child)
        write_construct_alignment(child, variant=variant)

    assessment = assert_publishable_output(family, scope="pair")

    assert assessment.state == "legacy"


def test_postprocessing_rejects_foreign_file_in_pre_manifest_output(tmp_path: Path) -> None:
    variant = tmp_path / "selected"
    _write_pre_manifest_variant(variant)
    (variant / "personal-notes.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="foreign/missing"):
        assert_publishable_output(variant, scope="variant", variant="selected")
