from __future__ import annotations

import csv
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from procurement.catalog_runner import run_catalog
from processing import catalog_context


def test_shared_catalog_processing_adapter_is_available() -> None:
    """Break caught: native processors lose catalog provenance when no shared adapter exists."""

    assert importlib.util.find_spec("processing.catalog_context") is not None


def _catalog_run(tmp_path: Path) -> tuple[Path, str, bytes, bytes]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    media = tmp_path / "shared.mp4"
    media.write_bytes(b"one immutable source, referenced twice")
    catalog_path = tmp_path / "sources.csv"
    with catalog_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Link", "Speaker", "Country", "Language", "Gender", "=Custom"])
        writer.writerow(["shared.mp4", "Speaker A", "Ireland", "Irish", "X", "@alpha"])
        writer.writerow(["shared.mp4", "", "France", "French", "Y", "+3.5e-2"])

    def create_outputs(source, output_directory: Path, _options) -> dict[str, str]:
        (output_directory / "stitched_imotions.mp4").write_bytes(
            f"canonical-{source.source_id}".encode("ascii")
        )
        (output_directory / "raw_clips").mkdir()
        (output_directory / "raw_clips" / "raw.mp4").write_bytes(b"raw")
        (output_directory / "segment_0001.mp4").write_bytes(b"segment")
        (output_directory / "focus_segment_0002.mp4").write_bytes(b"focus")
        (output_directory / "_downloads").mkdir()
        (output_directory / "_downloads" / "cached.mp4").write_bytes(b"cache")
        return {"video_directory": str(output_directory)}

    run_root = tmp_path / "catalog-run"
    run_catalog(
        catalog_path,
        run_root,
        selected_source_ids=["source-0001", "source-0002"],
        processor=create_outputs,
    )
    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    return (
        run_root,
        digest,
        (run_root / "source_manifest.json").read_bytes(),
        (run_root / "source_metadata.csv").read_bytes(),
    )


def test_catalog_jobs_preserve_manifest_order_metadata_repeated_links_and_canonical_media(
    tmp_path: Path,
) -> None:
    """Break caught: recursive discovery swaps row identity or admits procurement intermediates."""

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)

    result = catalog_context.discover_catalog_jobs(
        run_root,
        expected_catalog_sha256=digest,
    )

    assert result is not None
    assert [job.source_id for job in result.jobs] == ["source-0001", "source-0002"]
    assert [job.media_path.name for job in result.jobs] == [
        "stitched_imotions.mp4",
        "stitched_imotions.mp4",
    ]
    assert result.jobs[0].speaker == "Speaker A"
    assert result.jobs[0].speaker_display == "Speaker A"
    assert result.jobs[0].relative_output.parts[0] == "Speaker_A"
    assert result.jobs[1].speaker == ""
    assert result.jobs[1].relative_output.parts[0].startswith("source-0002_")
    assert dict(result.jobs[0].user_metadata) == {
        "Country": "Ireland",
        "Language": "Irish",
        "Gender": "X",
        "=Custom": "@alpha",
    }
    assert dict(result.jobs[1].user_metadata)["Language"] == "French"
    assert result.jobs[0].source_context["resolved_link"] == result.jobs[1].source_context[
        "resolved_link"
    ]
    assert result.catalog_sha256 == digest


def test_direct_catalog_file_accepts_only_its_exact_canonical_media(tmp_path: Path) -> None:
    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    canonical = next(run_root.rglob("source-0001_*/stitched_imotions.mp4"))

    result = catalog_context.discover_catalog_jobs(
        canonical,
        expected_catalog_sha256=digest,
    )

    assert result is not None
    assert [job.source_id for job in result.jobs] == ["source-0001"]


@pytest.mark.parametrize("relative", ["raw_clips/raw.mp4", "segment_0001.mp4", "_downloads/cached.mp4"])
def test_direct_catalog_file_rejects_intermediate_media_without_legacy_fallback(
    tmp_path: Path,
    relative: str,
) -> None:
    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    mapped = next(run_root.glob("Speaker_A/source-0001_*"))

    with pytest.raises(ValueError, match="canonical"):
        catalog_context.discover_catalog_jobs(
            mapped / relative,
            expected_catalog_sha256=digest,
        )


def test_catalog_job_contract_is_deeply_immutable_and_has_exact_fields(tmp_path: Path) -> None:
    """Break caught: a pipeline mutates source identity after catalog preflight."""

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    result = catalog_context.discover_catalog_jobs(run_root, expected_catalog_sha256=digest)
    assert result is not None
    job = result.jobs[0]

    assert [field.name for field in dataclasses.fields(job)] == [
        "source_id",
        "speaker",
        "speaker_display",
        "media_path",
        "relative_output",
        "source_context",
        "catalog_sha256",
        "user_metadata",
        "system_metadata",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.source_id = "source-9999"  # type: ignore[misc]
    with pytest.raises(TypeError):
        job.user_metadata["Country"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        job.source_context["output_mapping"]["video_directory"] = "changed"  # type: ignore[index]


def test_selected_catalog_subset_keeps_manifest_order_and_validates_unselected_contexts(
    tmp_path: Path,
) -> None:
    """Break caught: request order or partial validation lets a SourceID inherit another row."""

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    result = catalog_context.discover_catalog_jobs(
        run_root,
        selected_source_ids=["source-0002", "source-0001"],
        expected_catalog_sha256=digest,
    )
    assert result is not None
    assert [job.source_id for job in result.jobs] == ["source-0001", "source-0002"]

    first_context = next(run_root.rglob("source-0001_*/source_context.json"))
    first_context.unlink()
    with pytest.raises(ValueError, match="source context"):
        catalog_context.discover_catalog_jobs(
            run_root,
            selected_source_ids=["source-0002"],
            expected_catalog_sha256=digest,
        )


@pytest.mark.parametrize("selection", [["source-0001", "source-0001"], ["source-9999"]])
def test_catalog_selection_rejects_duplicate_and_unknown_source_ids(
    tmp_path: Path,
    selection: list[str],
) -> None:
    """Break caught: an invalid authorization list reaches model execution."""

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    with pytest.raises(ValueError, match="SourceID"):
        catalog_context.discover_catalog_jobs(
            run_root,
            selected_source_ids=selection,
            expected_catalog_sha256=digest,
        )


def test_catalog_adapter_rejects_digest_context_manifest_and_orphan_tampering(
    tmp_path: Path,
) -> None:
    """Break caught: stale or ambiguous catalog evidence is accepted as a legacy folder."""

    run_root, digest, manifest_bytes, _metadata = _catalog_run(tmp_path)
    with pytest.raises(ValueError, match="digest"):
        catalog_context.discover_catalog_jobs(
            run_root,
            expected_catalog_sha256="0" * 64,
        )

    context_path = next(run_root.rglob("source-0001_*/source_context.json"))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["speaker"] = "Different Speaker"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    with pytest.raises(ValueError, match="speaker"):
        catalog_context.discover_catalog_jobs(run_root, expected_catalog_sha256=digest)

    context_path.write_bytes(
        next(run_root.rglob("source-0002_*/source_context.json")).read_bytes()
    )
    with pytest.raises(ValueError, match="source context|SourceID"):
        catalog_context.discover_catalog_jobs(run_root, expected_catalog_sha256=digest)

    # Restore the run, then make the manifest ambiguous and add an orphan context.
    run_root, digest, manifest_bytes, _metadata = _catalog_run(tmp_path / "fresh")
    payload = json.loads(manifest_bytes.decode("utf-8"))
    payload["sources"].append(dict(payload["sources"][0]))
    (run_root / "source_manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        catalog_context.discover_catalog_jobs(run_root, expected_catalog_sha256=digest)

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path / "orphan")
    orphan = run_root / "orphan" / "source_context.json"
    orphan.parent.mkdir()
    orphan.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Orphan"):
        catalog_context.discover_catalog_jobs(run_root, expected_catalog_sha256=digest)


def test_partial_catalog_evidence_never_falls_back_to_recursive_discovery(tmp_path: Path) -> None:
    """Break caught: an incomplete catalog directory is silently treated as legacy media."""

    root = tmp_path / "partial"
    root.mkdir()
    (root / "video.mp4").write_bytes(b"legacy-looking")
    (root / "source_manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Incomplete source sidecar pair"):
        catalog_context.discover_catalog_jobs(root)

    (root / "source_manifest.json").unlink()
    nested = root / "nested"
    nested.mkdir()
    (nested / "source_context.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Partial catalog evidence"):
        catalog_context.discover_catalog_jobs(root)

    (nested / "source_context.json").unlink()
    assert catalog_context.discover_catalog_jobs(root) is None


def test_catalog_sidecars_are_published_byte_exact_with_separate_processed_subset(
    tmp_path: Path,
) -> None:
    """Break caught: native runs rewrite catalog selection or conflate it with processed IDs."""

    run_root, digest, manifest_bytes, metadata_bytes = _catalog_run(tmp_path)
    result = catalog_context.discover_catalog_jobs(
        run_root,
        selected_source_ids=["source-0002"],
        expected_catalog_sha256=digest,
    )
    assert result is not None
    output = tmp_path / "native-run"

    selection_path = catalog_context.publish_catalog_run_context(output, result)

    assert (output / "source_manifest.json").read_bytes() == manifest_bytes
    assert (output / "source_metadata.csv").read_bytes() == metadata_bytes
    assert json.loads(selection_path.read_text(encoding="utf-8")) == {
        "format_version": 1,
        "catalog_sha256": digest,
        "processed_source_ids": ["source-0002"],
    }
