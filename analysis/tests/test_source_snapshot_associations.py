"""Analysis may join exact native-pipeline provenance copies across roots."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from analysis.metadata import (
    find_source_manifest,
    load_source_metadata,
    validate_source_manifest_associations,
)
from application.backend import AnalysisModalityRunRequest, discover_analysis_profile_context


def _source_pair(root: Path) -> Path:
    root.mkdir()
    manifest = root / "source_manifest.json"
    manifest.write_text(json.dumps({
        "format_version": 1,
        "catalog": {"metadata_headers": ["Country"]},
        "sources": [{
            "source_id": "source-0001", "speaker": "Researcher", "selected": True,
            "system_metadata": {"title": "Interview"},
            "user_metadata": {"Country": "Ireland"},
            "output_mapping": {"video_directory": str(root / "Interview")},
        }],
    }), encoding="utf-8")
    manifest.with_name("source_metadata.csv").write_text(
        "SourceID,Country\nsource-0001,Ireland\n", encoding="utf-8",
    )
    return manifest


def _copy_pair(manifest: Path, destination: Path) -> Path:
    destination.mkdir()
    for filename in ("source_manifest.json", "source_metadata.csv"):
        shutil.copyfile(manifest.with_name(filename), destination / filename)
    return destination / manifest.name


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_analysis_accepts_identical_snapshot_pairs_in_three_native_roots(tmp_path) -> None:
    original = _source_pair(tmp_path / "procurement")
    snapshots = [_copy_pair(original, tmp_path / kind) for kind in ("face", "audio", "text")]
    paths = [path.parent for path in snapshots]

    validate_source_manifest_associations(paths, original, _sha(original))
    assert find_source_manifest(paths) == snapshots[0]
    assert find_source_manifest(paths[::-1]) == snapshots[-1]

    context = discover_analysis_profile_context(tuple(
        AnalysisModalityRunRequest(name, "import", path)
        for name, path in zip(("video", "audio", "text"), paths)
    ))
    assert context["sourceManifestSha256"] == _sha(original)
    assert context["metadataFields"] == [{"name": "Country", "values": ["Ireland"]}]
    assert [item["id"] for item in context["sources"]] == ["source-0001"]


@pytest.mark.parametrize("changed", ("manifest", "metadata", "extra-csv-column", "both"))
def test_analysis_rejects_any_conflicting_copy_even_after_a_matching_copy(tmp_path, changed) -> None:
    original = _source_pair(tmp_path / "procurement")
    matching = _copy_pair(original, tmp_path / "face")
    conflicting = _copy_pair(original, tmp_path / "audio")
    if changed in {"manifest", "both"}:
        conflicting.write_text(conflicting.read_text().replace("Ireland", "Japan"), encoding="utf-8")
    metadata = conflicting.with_name("source_metadata.csv")
    if changed in {"metadata", "both"}:
        metadata.write_text(metadata.read_text().replace("Ireland", "Japan"), encoding="utf-8")
    if changed == "extra-csv-column":
        metadata.write_text("SourceID,Country,Extra\nsource-0001,Ireland,changed\n", encoding="utf-8")
    paths = [matching.parent, conflicting.parent]

    with pytest.raises(ValueError):
        validate_source_manifest_associations(paths, original, _sha(original))
    with pytest.raises(ValueError):
        find_source_manifest(paths)


def test_analysis_revalidates_metadata_even_when_manifest_path_matches(tmp_path) -> None:
    original = _source_pair(tmp_path / "procurement")
    original.with_name("source_metadata.csv").write_text(
        "SourceID,Country\nsource-0001,Japan\n", encoding="utf-8",
    )
    with pytest.raises(ValueError, match="metadata values"):
        validate_source_manifest_associations([original.parent], original, _sha(original))


@pytest.mark.parametrize("bad_digest", ("0" * 64, "", "not-a-sha256"))
def test_analysis_keeps_digest_and_incomplete_pair_guards_for_copies(tmp_path, bad_digest) -> None:
    original = _source_pair(tmp_path / "procurement")
    copied = _copy_pair(original, tmp_path / "face")
    with pytest.raises(ValueError):
        validate_source_manifest_associations([copied.parent], original, bad_digest)
    copied.with_name("source_metadata.csv").unlink()
    with pytest.raises(ValueError, match="Incomplete procurement"):
        find_source_manifest([copied.parent])
    with pytest.raises(ValueError, match="Incomplete procurement"):
        validate_source_manifest_associations([copied.parent], original, _sha(original))


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_analysis_rejects_snapshot_pairs_reached_through_a_junction(tmp_path) -> None:
    original = _source_pair(tmp_path / "procurement")
    alias = tmp_path / "alias"
    completed = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", str(alias), str(original.parent)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    try:
        with pytest.raises(ValueError, match="symbolic link|junction|reparse"):
            find_source_manifest([alias])
        with pytest.raises(ValueError, match="symbolic link|junction|reparse"):
            validate_source_manifest_associations([alias], original, _sha(original))
        with pytest.raises(ValueError, match="symbolic link|junction|reparse"):
            load_source_metadata(alias / original.name)
    finally:
        alias.rmdir()
