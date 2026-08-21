"""Read procurement sidecars and resolve reusable Analysis groupings."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from analysis.profile import AnalysisProfile
from procurement.input_limits import count_json_items
from processing.audio_analysis.audio_pipeline.source_context import (
    MAX_SOURCE_MANIFEST_BYTES,
    MAX_SOURCE_MANIFEST_ITEMS,
    MAX_SOURCE_METADATA_BYTES,
)
from spreadsheet_safety import neutralize_spreadsheet_value


def normalise_identity(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", ascii_text.casefold())


@dataclass(frozen=True)
class ManifestSource:
    source_id: str
    speaker_key: str
    speaker: str
    title: str
    selected: bool
    order: int
    user_metadata: Mapping[str, str]
    output_directory: Path
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SourceMetadata:
    manifest_path: Path
    manifest_sha256: str
    metadata_path: Path
    fields: tuple[str, ...]
    sources: tuple[ManifestSource, ...]

    @property
    def speakers(self) -> tuple[tuple[str, str], ...]:
        speakers: dict[str, str] = {}
        for source in self.sources:
            speakers.setdefault(source.speaker_key, source.speaker)
        return tuple(speakers.items())

    def distinct_values(self, field: str) -> tuple[str, ...]:
        if field not in self.fields:
            raise ValueError(f"Unknown source metadata field: {field}")
        values: list[str] = []
        seen: set[str] = set()
        for source in self.sources:
            if not source.selected:
                continue
            value = str(source.user_metadata.get(field, "")).strip()
            if value and value not in seen:
                values.append(value)
                seen.add(value)
        return tuple(values)


@dataclass(frozen=True)
class ResolvedGroup:
    group_id: str
    name: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedAnalysisProfile:
    ordered_source_ids: tuple[str, ...]
    groups: tuple[ResolvedGroup, ...]


def load_source_metadata(
    manifest_path: Path | str,
    *,
    expected_sha256: str = "",
) -> SourceMetadata:
    """Load the manifest snapshot and validate its paired metadata sidecar."""

    path = Path(manifest_path).expanduser().resolve()
    raw = _read_regular_bounded(path, MAX_SOURCE_MANIFEST_BYTES, "Source manifest")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest != str(expected_sha256).strip().casefold():
        raise ValueError("Source manifest digest does not match the selected Analysis profile.")
    payload = json.loads(raw.decode("utf-8-sig"))
    if count_json_items(payload, stop_after=MAX_SOURCE_MANIFEST_ITEMS) > MAX_SOURCE_MANIFEST_ITEMS:
        raise ValueError("Source manifest contains too many JSON items.")
    if not isinstance(payload, Mapping) or payload.get("format_version") != 1:
        raise ValueError("Source manifest has an unsupported format.")
    catalog = payload.get("catalog")
    raw_sources = payload.get("sources")
    if not isinstance(catalog, Mapping) or not isinstance(raw_sources, list):
        raise ValueError("Source manifest is missing catalog or sources data.")
    fields = catalog.get("metadata_headers")
    if not isinstance(fields, list) or not all(isinstance(field, str) and field.strip() for field in fields):
        raise ValueError("Source manifest metadata_headers must be nonblank text.")
    if len(fields) != len(set(fields)):
        raise ValueError("Source manifest metadata_headers must be unique.")

    metadata_path = path.with_name("source_metadata.csv")
    metadata_raw = _read_regular_bounded(metadata_path, MAX_SOURCE_METADATA_BYTES, "Source metadata")
    sources: list[ManifestSource] = []
    seen_ids: set[str] = set()
    for order, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, Mapping):
            raise ValueError("Every source manifest entry must be an object.")
        source_id = str(raw_source.get("source_id") or "").strip()
        if re.fullmatch(r"source-\d{4,6}", source_id) is None or source_id in seen_ids:
            raise ValueError(f"Source manifest contains an invalid or duplicate SourceID: {source_id!r}")
        seen_ids.add(source_id)
        user_metadata = raw_source.get("user_metadata")
        system_metadata = raw_source.get("system_metadata")
        output_mapping = raw_source.get("output_mapping")
        if not isinstance(user_metadata, Mapping) or not isinstance(system_metadata, Mapping) or not isinstance(
            output_mapping, Mapping
        ):
            raise ValueError(f"Source manifest metadata is invalid for {source_id}.")
        clean_metadata = {
            str(field): str(value)
            for field, value in user_metadata.items()
            if isinstance(field, str) and isinstance(value, (str, int, float, bool))
        }
        unknown = set(clean_metadata) - set(fields)
        if unknown:
            raise ValueError(f"Source manifest has undeclared metadata for {source_id}: {', '.join(sorted(unknown))}")
        speaker = str(raw_source.get("speaker_display") or raw_source.get("speaker") or "Pooled (no speaker)").strip()
        speaker_key = normalise_identity(raw_source.get("speaker") or speaker)
        title = str(system_metadata.get("title") or source_id).strip()
        output_text = str(output_mapping.get("video_directory") or "").strip()
        if not speaker_key or not title or not output_text:
            raise ValueError(f"Source manifest identity is incomplete for {source_id}.")
        output_directory = Path(output_text).expanduser().resolve()
        youtube = raw_source.get("youtube")
        video_id = str(youtube.get("video_id") or "").strip() if isinstance(youtube, Mapping) else ""
        aliases = tuple(
            dict.fromkeys(
                alias
                for value in (source_id, title, output_directory.name, video_id)
                if (alias := normalise_identity(value))
            )
        )
        sources.append(
            ManifestSource(
                source_id=source_id,
                speaker_key=speaker_key,
                speaker=speaker,
                title=title,
                selected=bool(raw_source.get("selected")),
                order=order,
                user_metadata=clean_metadata,
                output_directory=output_directory,
                aliases=aliases,
            )
        )
    _validate_metadata_sidecar(metadata_path, metadata_raw, catalog, tuple(fields), tuple(sources))
    return SourceMetadata(path, digest, metadata_path, tuple(fields), tuple(sources))


def _validate_metadata_sidecar(
    path: Path,
    raw: bytes,
    catalog: Mapping[str, object],
    fields: tuple[str, ...],
    sources: tuple[ManifestSource, ...],
) -> None:
    """Require the human-readable CSV to identify the same manifest snapshot."""

    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        headers = tuple(reader.fieldnames or ())
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"{path.name} is not a valid UTF-8 CSV sidecar.") from exc
    if not headers or len(headers) != len(set(headers)) or "SourceID" not in headers:
        raise ValueError(f"{path.name} must contain unique headers including SourceID.")
    export_headers = catalog.get("metadata_export_headers")
    if export_headers is not None and not isinstance(export_headers, Mapping):
        raise ValueError("Source manifest metadata_export_headers must be an object when supplied.")
    expected_metadata_headers = tuple(
        str(
            neutralize_spreadsheet_value(
                export_headers.get(field, field) if isinstance(export_headers, Mapping) else field
            )
        )
        for field in fields
    )
    missing_headers = [header for header in expected_metadata_headers if header not in headers]
    if missing_headers:
        raise ValueError(
            f"{path.name} does not match source manifest metadata columns: {', '.join(missing_headers)}"
        )
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"{path.name} contains malformed rows.")
    csv_source_ids = tuple(str(row.get("SourceID") or "").strip() for row in rows)
    manifest_source_ids = tuple(source.source_id for source in sources)
    if csv_source_ids != manifest_source_ids:
        raise ValueError(f"{path.name} SourceIDs do not match the source manifest in order and count.")
    for row, source in zip(rows, sources):
        for field, header in zip(fields, expected_metadata_headers):
            expected = str(neutralize_spreadsheet_value(source.user_metadata.get(field, "")))
            if row.get(header) != expected:
                raise ValueError(
                    f"{path.name} metadata values do not match the source manifest for "
                    f"{source.source_id}."
                )


def resolve_analysis_profile(
    metadata: SourceMetadata,
    profile: AnalysisProfile,
) -> ResolvedAnalysisProfile:
    """Apply filtering, deterministic ordering, and manual/automatic grouping."""

    if profile.source_manifest != metadata.manifest_path or profile.source_manifest_sha256 != metadata.manifest_sha256:
        raise ValueError("Analysis profile does not match the loaded source manifest snapshot.")
    requested_fields = (*profile.sort_fields, *((profile.automatic_group_field,) if profile.automatic_group_field else ()))
    requested_fields += tuple(field for field, _values in profile.metadata_filters)
    unknown = [field for field in requested_fields if field not in metadata.fields]
    if unknown:
        raise ValueError(f"Unknown source metadata field(s): {', '.join(dict.fromkeys(unknown))}")

    filter_map = {
        field: set(values)
        for field, values in profile.metadata_filters
    }
    selected_sources = [
        source
        for source in metadata.sources
        if source.selected
        and all(
            str(source.user_metadata.get(field, "")).strip() in values
            for field, values in filter_map.items()
        )
    ]

    def sort_key(source: ManifestSource) -> tuple[object, ...]:
        keys: list[object] = []
        for field in profile.sort_fields:
            value = str(source.user_metadata.get(field, "")).strip()
            keys.extend((not bool(value), value))
        keys.extend((source.order, source.source_id))
        return tuple(keys)

    ordered = tuple(sorted(selected_sources, key=sort_key))
    sources_by_id = {source.source_id: source for source in ordered}
    sources_by_speaker: dict[str, list[ManifestSource]] = {}
    for source in ordered:
        sources_by_speaker.setdefault(source.speaker_key, []).append(source)

    groups: list[ResolvedGroup] = []
    assigned: set[str] = set()
    used_group_ids: set[str] = set()

    def unique_group_id(base: str) -> str:
        candidate = base
        suffix = 2
        while candidate in used_group_ids:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used_group_ids.add(candidate)
        return candidate

    for group in profile.manual_groups:
        member_sources: list[ManifestSource] = []
        for member in group.members:
            if member.kind == "source":
                source = sources_by_id.get(member.value.strip())
                if source is None:
                    raise ValueError(f"Manual group {group.name} contains an unknown SourceID: {member.value}")
                candidates = [source]
            else:
                candidates = sources_by_speaker.get(normalise_identity(member.value), [])
                if not candidates:
                    raise ValueError(f"Manual group {group.name} contains an unknown speaker: {member.value}")
            for source in candidates:
                if source.source_id in assigned:
                    raise ValueError(
                        f"Source {source.source_id} is assigned more than once across manual groups."
                    )
                assigned.add(source.source_id)
                member_sources.append(source)
        member_ids = tuple(source.source_id for source in ordered if source in member_sources)
        group_id = group.group_id.strip()
        used_group_ids.add(group_id)
        groups.append(ResolvedGroup(group_id, group.name.strip(), member_ids))

    remaining = tuple(source for source in ordered if source.source_id not in assigned)
    if profile.automatic_group_field:
        automatic: dict[str, list[str]] = {}
        display_names: dict[str, str] = {}
        for source in remaining:
            value = str(source.user_metadata.get(profile.automatic_group_field, "")).strip() or "(blank)"
            key = value
            automatic.setdefault(key, []).append(source.source_id)
            display_names.setdefault(key, value)
        for key, source_ids in automatic.items():
            groups.append(
                ResolvedGroup(
                    unique_group_id(
                        f"metadata-{normalise_identity(profile.automatic_group_field)}-"
                        f"{normalise_identity(display_names[key]) or 'blank'}"
                    ),
                    display_names[key],
                    tuple(source_ids),
                )
            )
    elif remaining:
        groups.append(
            ResolvedGroup(
                unique_group_id("ungrouped"),
                "All other sources",
                tuple(source.source_id for source in remaining),
            )
        )
    if not groups and ordered:
        groups.append(ResolvedGroup("all-sources", "All sources", tuple(source.source_id for source in ordered)))
    return ResolvedAnalysisProfile(
        tuple(source.source_id for source in ordered),
        tuple(groups),
    )


def map_report_source_ids(
    metadata: SourceMetadata,
    speaker: str,
    report_labels: Sequence[str],
) -> tuple[str, ...]:
    """Map exact report labels to stable SourceIDs for one speaker."""

    speaker_key = normalise_identity(speaker)
    candidates = [source for source in metadata.sources if source.selected and source.speaker_key == speaker_key]
    mapped: list[str] = []
    for label in report_labels:
        key = normalise_identity(label)
        matches = [source.source_id for source in candidates if key in source.aliases]
        if len(matches) != 1:
            raise ValueError(
                f"Could not map report source {label!r} for {speaker!r} to exactly one SourceID."
            )
        if matches[0] in mapped:
            raise ValueError(f"Report maps SourceID more than once: {matches[0]}")
        mapped.append(matches[0])
    return tuple(mapped)


def find_source_manifest(paths: Sequence[Path | str]) -> Path:
    """Find the one procurement sidecar pair available beside selected paths."""

    candidates: set[Path] = set()
    for raw_path in paths:
        associated_manifest = _associated_source_manifest(raw_path)
        if associated_manifest is not None:
            candidates.add(associated_manifest)
    if not candidates:
        raise ValueError("No paired source_manifest.json and source_metadata.csv were found for the selected run.")
    if len(candidates) != 1:
        raise ValueError("Selected Analysis sources refer to more than one source manifest.")
    return next(iter(candidates))


def validate_source_manifest_associations(
    paths: Sequence[Path | str],
    expected_manifest: Path | str,
    expected_sha256: str,
) -> None:
    """Reject conflicting sidecars while allowing ordinary sidecarless exports."""

    expected_path = Path(expected_manifest).expanduser().resolve()
    for raw_path in paths:
        associated = _associated_source_manifest(raw_path)
        if associated is None:
            continue
        if associated != expected_path:
            raise ValueError(
                f"Selected Analysis source {Path(raw_path).expanduser()} refers to a different source manifest."
            )
        raw = _read_regular_bounded(
            associated,
            MAX_SOURCE_MANIFEST_BYTES,
            "Source manifest",
        )
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError(
                f"Selected Analysis source {Path(raw_path).expanduser()} refers to a changed source manifest."
            )


def _associated_source_manifest(path: Path | str) -> Path | None:
    current = Path(path).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *tuple(current.parents)[:6]):
        manifest = directory / "source_manifest.json"
        metadata = directory / "source_metadata.csv"
        has_manifest = manifest.exists()
        has_metadata = metadata.exists()
        if has_manifest != has_metadata:
            raise ValueError(
                f"Incomplete procurement sidecars are associated with {current}; "
                "source_manifest.json and source_metadata.csv must be kept together."
            )
        if has_manifest:
            if not manifest.is_file() or not metadata.is_file():
                raise ValueError(f"Procurement sidecars must be regular files: {directory}")
            return manifest.resolve()
    return None


def validate_text_profile_grouping(
    metadata: SourceMetadata,
    resolved: ResolvedAnalysisProfile,
) -> None:
    """Require one output group per speaker when speaker-level Text is enabled."""

    sources_by_id = {source.source_id: source for source in metadata.sources}
    groups_by_speaker: dict[str, set[str]] = {}
    display_by_speaker: dict[str, str] = {}
    for group in resolved.groups:
        for source_id in group.source_ids:
            source = sources_by_id[source_id]
            groups_by_speaker.setdefault(source.speaker_key, set()).add(group.group_id)
            display_by_speaker.setdefault(source.speaker_key, source.speaker)
    split = [
        display_by_speaker[speaker_key]
        for speaker_key, group_ids in groups_by_speaker.items()
        if len(group_ids) > 1
    ]
    if split:
        raise ValueError(
            "Text is speaker-level, so every visible source for a speaker must stay in "
            f"the same output group: {', '.join(split)}."
        )


def _read_regular_bounded(path: Path, max_bytes: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"{label} exceeds {max_bytes} bytes: {path}")
    return raw
