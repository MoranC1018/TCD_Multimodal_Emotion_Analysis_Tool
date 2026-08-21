from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from analysis import metadata as analysis_metadata
from analysis.metadata import (
    load_source_metadata,
    map_report_source_ids,
    resolve_analysis_profile,
)
from processing.audio_analysis.audio_pipeline import source_context as producer_limits
from analysis.profile import (
    AnalysisProfile,
    ManualGroup,
    ProfileMember,
    load_analysis_profile,
    write_analysis_profile,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sidecars(root: Path, count: int = 14) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    sources = []
    for index in range(1, count + 1):
        source_id = f"source-{index:04d}"
        speaker = "Dr Aster" if index <= 7 else "Researcher Beta"
        country = "Ireland" if index % 2 else "Japan"
        language = "Irish" if index % 3 else "English"
        sources.append(
            {
                "source_id": source_id,
                "catalog_row": index + 1,
                "link": f"https://www.youtube.com/watch?v={index:011d}",
                "resolved_link": f"https://www.youtube.com/watch?v={index:011d}",
                "source_kind": "youtube",
                "speaker": speaker,
                "speaker_display": speaker,
                "selected": True,
                "status": "selected",
                "system_metadata": {
                    "title": f"Interview {index:02d}",
                    "duration_seconds": index * 10,
                    "youtube_language": language,
                },
                "user_metadata": {
                    "Country": country,
                    "Language": language,
                    "Research Lens": f"Lens {index % 4}",
                },
                "output_mapping": {
                    "video_directory": str(root / speaker / f"{source_id}_Interview_{index:02d}")
                },
                "youtube": {
                    "video_id": f"{index:011d}",
                    "url": f"https://www.youtube.com/watch?v={index:011d}",
                },
            }
        )
    manifest_path = root / "source_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "catalog": {
                    "path": str(root / "sources.csv"),
                    "format": "csv",
                    "sha256": "a" * 64,
                    "original_headers": ["Link", "Speaker", "Country", "Language", "Research Lens"],
                    "ignored_headers": [],
                    "metadata_headers": ["Country", "Language", "Research Lens"],
                    "metadata_export_headers": {
                        "Country": "Country",
                        "Language": "Language",
                        "Research Lens": "Research Lens",
                    },
                },
                "sources": sources,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    metadata_path = root / "source_metadata.csv"
    metadata_path.write_text(
        "SourceID,Country,Language,Research Lens\n"
        + "\n".join(
            f"{item['source_id']},{item['user_metadata']['Country']},"
            f"{item['user_metadata']['Language']},{item['user_metadata']['Research Lens']}"
            for item in sources
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path, metadata_path


@pytest.mark.parametrize("count", [1, 7, 14])
def test_metadata_supports_one_seven_and_more_than_twelve_sources(
    tmp_path: Path,
    count: int,
) -> None:
    manifest_path, _ = _write_sidecars(tmp_path / f"run-{count}", count)

    metadata = load_source_metadata(manifest_path)

    assert len(metadata.sources) == count
    assert metadata.fields == ("Country", "Language", "Research Lens")
    assert metadata.speakers == (("draster", "Dr Aster"),) if count <= 7 else (
        ("draster", "Dr Aster"),
        ("researcherbeta", "Researcher Beta"),
    )
    assert metadata.distinct_values("Country") == (
        ("Ireland",) if count == 1 else ("Ireland", "Japan")
    )


def test_profile_sort_and_automatic_metadata_groups_are_deterministic(tmp_path: Path) -> None:
    manifest_path, _ = _write_sidecars(tmp_path / "run", 14)
    metadata = load_source_metadata(manifest_path)
    profile = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        sort_fields=("Country", "Language"),
        automatic_group_field="Research Lens",
    )

    first = resolve_analysis_profile(metadata, profile)
    second = resolve_analysis_profile(metadata, profile)

    assert first == second
    assert len(first.ordered_source_ids) == 14
    assert first.ordered_source_ids[:4] == (
        "source-0003",
        "source-0009",
        "source-0001",
        "source-0005",
    )
    assert [group.name for group in first.groups] == [
        "Lens 3",
        "Lens 1",
        "Lens 2",
        "Lens 0",
    ]
    assert {source_id for group in first.groups for source_id in group.source_ids} == {
        f"source-{index:04d}" for index in range(1, 15)
    }


def test_automatic_group_ids_remain_unique_for_arbitrary_metadata_values(
    tmp_path: Path,
) -> None:
    manifest_path, metadata_path = _write_sidecars(tmp_path / "run", 3)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for source, country in zip(payload["sources"], ("Group A", "Group-A", "Elsewhere")):
        source["user_metadata"]["Country"] = country
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    metadata_path.write_text(
        "SourceID,Country,Language,Research Lens\n"
        "source-0001,Group A,Irish,Lens 1\n"
        "source-0002,Group-A,Irish,Lens 2\n"
        "source-0003,Elsewhere,English,Lens 3\n",
        encoding="utf-8",
    )
    metadata = load_source_metadata(manifest_path)
    profile = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        automatic_group_field="Country",
        manual_groups=(
            ManualGroup(
                "metadata-country-groupa",
                "Manual focus",
                (ProfileMember("source", "source-0003"),),
            ),
        ),
    )

    resolved = resolve_analysis_profile(metadata, profile)

    assert [group.name for group in resolved.groups] == ["Manual focus", "Group A", "Group-A"]
    assert len({group.group_id for group in resolved.groups}) == 3


def test_metadata_values_use_exact_deterministic_sort_filter_and_group_matching(
    tmp_path: Path,
) -> None:
    manifest_path, metadata_path = _write_sidecars(tmp_path / "run", 3)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for source, country in zip(payload["sources"], ("ireland", "Ireland", "ireland")):
        source["user_metadata"]["Country"] = country
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    metadata_path.write_text(
        "SourceID,Country,Language,Research Lens\n"
        "source-0001,ireland,Irish,Lens 1\n"
        "source-0002,Ireland,Irish,Lens 2\n"
        "source-0003,ireland,English,Lens 3\n",
        encoding="utf-8",
    )
    metadata = load_source_metadata(manifest_path)

    grouped = resolve_analysis_profile(
        metadata,
        AnalysisProfile(
            manifest_path,
            metadata.manifest_sha256,
            sort_fields=("Country",),
            automatic_group_field="Country",
        ),
    )
    filtered = resolve_analysis_profile(
        metadata,
        AnalysisProfile(
            manifest_path,
            metadata.manifest_sha256,
            metadata_filters=(("Country", ("Ireland",)),),
        ),
    )

    assert grouped.ordered_source_ids == ("source-0002", "source-0001", "source-0003")
    assert [group.name for group in grouped.groups] == ["Ireland", "ireland"]
    assert filtered.ordered_source_ids == ("source-0002",)


def test_manual_groups_accept_mixed_speaker_and_source_members_and_reject_overlap(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_sidecars(tmp_path / "run", 14)
    metadata = load_source_metadata(manifest_path)
    profile = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        manual_groups=(
            ManualGroup(
                "focus",
                "Focus set",
                (
                    ProfileMember("source", "source-0001"),
                    ProfileMember("source", "source-0002"),
                ),
            ),
            ManualGroup(
                "remaining",
                "Remaining speaker videos",
                (ProfileMember("speaker", "Researcher Beta"),),
            ),
        ),
    )

    resolved = resolve_analysis_profile(metadata, profile)

    assert resolved.groups[0].source_ids == ("source-0001", "source-0002")
    assert resolved.groups[1].source_ids == (
        "source-0008",
        "source-0009",
        "source-0010",
        "source-0011",
        "source-0012",
        "source-0013",
        "source-0014",
    )

    overlapping = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        manual_groups=(
            ManualGroup(
                "one",
                "One",
                (ProfileMember("speaker", "Dr Aster"),),
            ),
            ManualGroup(
                "two",
                "Two",
                (ProfileMember("source", "source-0002"),),
            ),
        ),
    )
    with pytest.raises(ValueError, match=r"source-0002.*assigned more than once"):
        resolve_analysis_profile(metadata, overlapping)


def test_two_profiles_change_order_without_mutating_source_sidecars(tmp_path: Path) -> None:
    manifest_path, metadata_path = _write_sidecars(tmp_path / "run", 7)
    metadata = load_source_metadata(manifest_path)
    before = (_sha256(manifest_path), _sha256(metadata_path))
    by_country = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        sort_fields=("Country",),
    )
    by_language = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        sort_fields=("Language",),
    )

    country_path = write_analysis_profile(by_country, tmp_path / "country-output")
    language_path = write_analysis_profile(by_language, tmp_path / "language-output")

    assert load_analysis_profile(country_path) == by_country
    assert load_analysis_profile(language_path) == by_language
    assert resolve_analysis_profile(metadata, by_country).ordered_source_ids != (
        resolve_analysis_profile(metadata, by_language).ordered_source_ids
    )
    assert (_sha256(manifest_path), _sha256(metadata_path)) == before


def test_profile_file_is_immutable_and_bound_to_manifest_digest(tmp_path: Path) -> None:
    manifest_path, _ = _write_sidecars(tmp_path / "run", 1)
    metadata = load_source_metadata(manifest_path)
    profile = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
    )
    output = tmp_path / "output"

    path = write_analysis_profile(profile, output)
    assert write_analysis_profile(profile, output) == path

    changed = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        sort_fields=("Country",),
    )
    with pytest.raises(FileExistsError, match="different analysis profile"):
        write_analysis_profile(changed, output)

    manifest_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source manifest digest"):
        load_analysis_profile(path, verify_manifest=True)


def test_profile_copies_mutable_constructor_collections(tmp_path: Path) -> None:
    manifest_path, _ = _write_sidecars(tmp_path / "run", 1)
    metadata = load_source_metadata(manifest_path)
    members = [ProfileMember("source", "source-0001")]
    groups = [ManualGroup("focus", "Focus", members)]
    sort_fields = ["Country"]
    filter_values = ["Ireland"]
    filters = [("Country", filter_values)]

    profile = AnalysisProfile(
        source_manifest=manifest_path,
        source_manifest_sha256=metadata.manifest_sha256,
        sort_fields=sort_fields,
        manual_groups=groups,
        metadata_filters=filters,
    )
    members.clear()
    groups.clear()
    sort_fields.clear()
    filter_values.clear()
    filters.clear()

    assert profile.sort_fields == ("Country",)
    assert profile.manual_groups[0].members == (ProfileMember("source", "source-0001"),)
    assert profile.metadata_filters == (("Country", ("Ireland",)),)


def test_report_labels_map_to_source_ids_without_order_or_substring_guessing(tmp_path: Path) -> None:
    manifest_path, _ = _write_sidecars(tmp_path / "run", 3)
    metadata = load_source_metadata(manifest_path)

    mapped = map_report_source_ids(
        metadata,
        "Dr Aster",
        ("source-0003_Interview_03", "Interview 01", "00000000002"),
    )

    assert mapped == ("source-0003", "source-0001", "source-0002")
    with pytest.raises(ValueError, match="Could not map report source"):
        map_report_source_ids(metadata, "Dr Aster", ("Interview",))


def test_metadata_sidecar_source_ids_and_declared_columns_must_match_manifest(tmp_path: Path) -> None:
    manifest_path, metadata_path = _write_sidecars(tmp_path / "run", 3)
    metadata_path.write_text(
        "SourceID,Country,Language\nsource-0001,Ireland,Irish\nsource-0002,Japan,Irish\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source_metadata.csv.*manifest"):
        load_source_metadata(manifest_path)


def test_analysis_sidecar_limits_cover_the_catalog_producer_envelope() -> None:
    assert analysis_metadata.MAX_SOURCE_MANIFEST_BYTES == producer_limits.MAX_SOURCE_MANIFEST_BYTES
    assert analysis_metadata.MAX_SOURCE_MANIFEST_ITEMS == producer_limits.MAX_SOURCE_MANIFEST_ITEMS
    assert analysis_metadata.MAX_SOURCE_METADATA_BYTES == producer_limits.MAX_SOURCE_METADATA_BYTES


def test_metadata_sidecar_values_must_match_manifest_snapshot(tmp_path: Path) -> None:
    manifest_path, metadata_path = _write_sidecars(tmp_path / "run", 2)
    metadata_path.write_text(
        "SourceID,Country,Language,Research Lens\n"
        "source-0001,Japan,Irish,Lens 1\n"
        "source-0002,Japan,Irish,Lens 2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source_metadata.csv.*values.*source-0001"):
        load_source_metadata(manifest_path)


def test_metadata_sidecar_accepts_spreadsheet_neutralized_custom_header(tmp_path: Path) -> None:
    manifest_path, metadata_path = _write_sidecars(tmp_path / "run", 1)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["catalog"]["metadata_headers"] = ["=Category"]
    payload["catalog"]["metadata_export_headers"] = {"=Category": "=Category"}
    payload["sources"][0]["user_metadata"] = {"=Category": "=formula"}
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    metadata_path.write_text("SourceID,'=Category\nsource-0001,'=formula\n", encoding="utf-8")

    metadata = load_source_metadata(manifest_path)

    assert metadata.fields == ("=Category",)
