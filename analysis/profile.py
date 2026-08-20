"""Immutable researcher choices for one Analysis output.

The profile is deliberately separate from procurement's source sidecars.  A
researcher can therefore reuse one source manifest for several Analysis runs
without changing provenance recorded during procurement.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

from procurement.input_limits import count_json_items


PROFILE_FILENAME = "analysis_profile.json"
MAX_PROFILE_JSON_BYTES = 2 * 1024 * 1024
MAX_PROFILE_JSON_ITEMS = 100_000


@dataclass(frozen=True)
class ProfileMember:
    """One manual-group member, addressed by stable speaker or SourceID."""

    kind: Literal["speaker", "source"]
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in {"speaker", "source"}:
            raise ValueError("Analysis profile member type must be speaker or source.")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("Analysis profile member id must be nonblank.")
        object.__setattr__(self, "value", self.value.strip())


@dataclass(frozen=True)
class ManualGroup:
    """A named collection of source or speaker members."""

    group_id: str
    name: str
    members: tuple[ProfileMember, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not isinstance(self.name, str):
            raise ValueError("Manual group ids and names must be text.")
        if not self.group_id.strip() or not self.name.strip():
            raise ValueError("Manual groups need nonblank ids and names.")
        members = tuple(self.members)
        if not members or not all(isinstance(member, ProfileMember) for member in members):
            raise ValueError("Manual groups need at least one member.")
        if len({(member.kind, member.value) for member in members}) != len(members):
            raise ValueError("Manual group members must be unique.")
        object.__setattr__(self, "group_id", self.group_id.strip())
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "members", members)


@dataclass(frozen=True)
class AnalysisProfile:
    """Grouping and ordering choices bound to one source-manifest snapshot."""

    source_manifest: Path
    source_manifest_sha256: str
    sort_fields: tuple[str, ...] = ()
    automatic_group_field: str | None = None
    manual_groups: tuple[ManualGroup, ...] = ()
    metadata_filters: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_manifest", Path(self.source_manifest).expanduser().resolve())
        digest = str(self.source_manifest_sha256).strip().casefold()
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("Analysis profile source manifest SHA-256 must contain 64 hex characters.")
        object.__setattr__(self, "source_manifest_sha256", digest)
        if not all(isinstance(field, str) for field in self.sort_fields):
            raise ValueError("Analysis profile sort fields must be text.")
        sort_fields = tuple(field.strip() for field in self.sort_fields)
        _require_unique_nonblank(sort_fields, "sort fields")
        object.__setattr__(self, "sort_fields", sort_fields)
        automatic_group_field = self.automatic_group_field
        if automatic_group_field is not None:
            if not isinstance(automatic_group_field, str) or not automatic_group_field.strip():
                raise ValueError("Automatic grouping field must be nonblank when supplied.")
            object.__setattr__(self, "automatic_group_field", automatic_group_field.strip())
        manual_groups = tuple(self.manual_groups)
        if not all(isinstance(group, ManualGroup) for group in manual_groups):
            raise ValueError("Analysis profile manual groups must use ManualGroup entries.")
        object.__setattr__(self, "manual_groups", manual_groups)
        group_ids = [group.group_id for group in manual_groups]
        group_names = [group.name.casefold() for group in manual_groups]
        if len(group_ids) != len(set(group_ids)) or len(group_names) != len(set(group_names)):
            raise ValueError("Manual group ids and names must be unique.")
        metadata_filters: list[tuple[str, tuple[str, ...]]] = []
        for item in self.metadata_filters:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("Metadata filters must contain field and values pairs.")
            field, raw_values = item
            if (
                not isinstance(field, str)
                or not isinstance(raw_values, (tuple, list))
                or not all(isinstance(value, str) for value in raw_values)
            ):
                raise ValueError("Metadata filter fields and values must be text.")
            metadata_filters.append(
                (field.strip(), tuple(value.strip() for value in raw_values))
            )
        object.__setattr__(self, "metadata_filters", tuple(metadata_filters))
        filter_fields = [field for field, _values in metadata_filters]
        _require_unique_nonblank(filter_fields, "metadata filter fields")
        for field, values in metadata_filters:
            if not values or any(not value for value in values):
                raise ValueError(f"Metadata filter {field!r} needs at least one nonblank value.")


def _require_unique_nonblank(values: Sequence[str], label: str) -> None:
    cleaned = [str(value).strip() for value in values]
    if any(not value for value in cleaned):
        raise ValueError(f"Analysis profile {label} must be nonblank.")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"Analysis profile {label} must be unique.")


def profile_payload(profile: AnalysisProfile) -> dict[str, object]:
    """Return the stable JSON representation used by the launcher and CLI."""

    return {
        "format_version": 1,
        "source_manifest": {
            "path": str(profile.source_manifest),
            "sha256": profile.source_manifest_sha256,
        },
        "sort_fields": list(profile.sort_fields),
        "automatic_group_field": profile.automatic_group_field,
        "manual_groups": [
            {
                "id": group.group_id,
                "name": group.name,
                "members": [
                    {"type": member.kind, "id": member.value}
                    for member in group.members
                ],
            }
            for group in profile.manual_groups
        ],
        "metadata_filters": {
            field: list(values) for field, values in profile.metadata_filters
        },
    }


def profile_from_payload(
    payload: Mapping[str, object],
    *,
    relative_to: Path | None = None,
) -> AnalysisProfile:
    """Validate a JSON-compatible profile object without accepting extra shape."""

    allowed = {
        "format_version",
        "source_manifest",
        "sort_fields",
        "automatic_group_field",
        "manual_groups",
        "metadata_filters",
    }
    if set(payload) != allowed or payload.get("format_version") != 1:
        raise ValueError("Analysis profile has an unsupported shape or format version.")
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping) or set(manifest) != {"path", "sha256"}:
        raise ValueError("Analysis profile source_manifest needs only path and sha256.")
    raw_path = manifest.get("path")
    digest = manifest.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(digest, str):
        raise ValueError("Analysis profile source manifest path and sha256 must be text.")
    source_path = Path(raw_path).expanduser()
    if not source_path.is_absolute() and relative_to is not None:
        source_path = relative_to / source_path

    sort_fields = payload.get("sort_fields")
    automatic_group_field = payload.get("automatic_group_field")
    manual_groups = payload.get("manual_groups")
    metadata_filters = payload.get("metadata_filters")
    if not isinstance(sort_fields, list) or not all(isinstance(item, str) for item in sort_fields):
        raise ValueError("Analysis profile sort_fields must be a list of text fields.")
    if automatic_group_field is not None and not isinstance(automatic_group_field, str):
        raise ValueError("Analysis profile automatic_group_field must be text or null.")
    if not isinstance(manual_groups, list):
        raise ValueError("Analysis profile manual_groups must be a list.")
    if not isinstance(metadata_filters, Mapping):
        raise ValueError("Analysis profile metadata_filters must be an object.")

    groups: list[ManualGroup] = []
    for raw_group in manual_groups:
        if not isinstance(raw_group, Mapping) or set(raw_group) != {"id", "name", "members"}:
            raise ValueError("Each manual group needs only id, name, and members.")
        members = raw_group.get("members")
        if not isinstance(members, list):
            raise ValueError("Manual group members must be a list.")
        parsed_members: list[ProfileMember] = []
        for raw_member in members:
            if not isinstance(raw_member, Mapping) or set(raw_member) != {"type", "id"}:
                raise ValueError("Each manual group member needs only type and id.")
            kind = raw_member.get("type")
            value = raw_member.get("id")
            if not isinstance(kind, str) or not isinstance(value, str):
                raise ValueError("Manual group member type and id must be text.")
            parsed_members.append(ProfileMember(kind, value))
        group_id = raw_group.get("id")
        name = raw_group.get("name")
        if not isinstance(group_id, str) or not isinstance(name, str):
            raise ValueError("Manual group id and name must be text.")
        groups.append(ManualGroup(group_id, name, tuple(parsed_members)))

    filters: list[tuple[str, tuple[str, ...]]] = []
    for field, raw_values in metadata_filters.items():
        if not isinstance(field, str) or not isinstance(raw_values, list) or not all(
            isinstance(value, str) for value in raw_values
        ):
            raise ValueError("Metadata filters map field names to lists of text values.")
        filters.append((field, tuple(raw_values)))

    return AnalysisProfile(
        source_manifest=source_path,
        source_manifest_sha256=digest,
        sort_fields=tuple(sort_fields),
        automatic_group_field=automatic_group_field,
        manual_groups=tuple(groups),
        metadata_filters=tuple(filters),
    )


def load_analysis_profile(
    path: Path | str,
    *,
    verify_manifest: bool = False,
) -> AnalysisProfile:
    """Read one bounded profile and optionally verify its source snapshot."""

    profile_path = Path(path).expanduser().resolve()
    raw = _read_bounded(profile_path, MAX_PROFILE_JSON_BYTES, "Analysis profile")
    payload = json.loads(raw.decode("utf-8-sig"))
    if count_json_items(payload, stop_after=MAX_PROFILE_JSON_ITEMS) > MAX_PROFILE_JSON_ITEMS:
        raise ValueError("Analysis profile JSON contains too many items.")
    if not isinstance(payload, Mapping):
        raise ValueError("Analysis profile JSON must contain an object.")
    profile = profile_from_payload(payload, relative_to=profile_path.parent)
    if verify_manifest:
        _verify_manifest_digest(profile)
    return profile


def write_analysis_profile(profile: AnalysisProfile, output_root: Path | str) -> Path:
    """Publish one immutable profile; identical reruns reuse the same bytes."""

    _verify_manifest_digest(profile)
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / PROFILE_FILENAME
    content = (
        json.dumps(profile_payload(profile), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if destination.exists():
        if _read_bounded(destination, MAX_PROFILE_JSON_BYTES, "Analysis profile") == content:
            return destination
        raise FileExistsError(f"Analysis output already contains a different analysis profile: {destination}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def _verify_manifest_digest(profile: AnalysisProfile) -> None:
    raw = _read_bounded(profile.source_manifest, 16 * 1024 * 1024, "Source manifest")
    if hashlib.sha256(raw).hexdigest() != profile.source_manifest_sha256:
        raise ValueError("Analysis profile source manifest digest does not match its current bytes.")


def _read_bounded(path: Path, max_bytes: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"{label} exceeds {max_bytes} bytes: {path}")
    return raw
