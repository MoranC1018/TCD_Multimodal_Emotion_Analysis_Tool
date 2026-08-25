"""Local Py-Feat Detectorv2 model-weight discovery and fingerprints.

Py-Feat 2.1.1's ``Detectorv2`` is one logical backend backed by three
independently downloaded checkpoints.  Keeping their discovery here prevents
readiness, manifests, and resume checks from drifting apart.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

try:
    from huggingface_hub import hf_hub_download, try_to_load_from_cache
except ImportError:  # pragma: no cover - Py-Feat installs this dependency.
    hf_hub_download = None
    try_to_load_from_cache = None

from .media import file_sha256


MODEL_WEIGHT_PROVENANCE_VERSION = "1.1"


@dataclass(frozen=True)
class ModelWeightSpec:
    """One checkpoint loaded by the default Py-Feat Detectorv2 constructor."""

    component: str
    repo_id: str
    filenames: tuple[str, ...]
    environment_override: str | None = None
    approved_revision: str = ""
    approved_sha256: str = ""
    approved_size_bytes: int = 0


DETECTOR_V2_WEIGHT_SPECS = (
    ModelWeightSpec(
        component="retinaface_r34",
        repo_id="py-feat/retinaface_r34",
        # Py-Feat 2.1.1 tries the v2 filename first, then this legacy fallback.
        filenames=("model.safetensors",),
        approved_revision="2e4495d934ed359ae8ddc0946d82f85e1e328e52",
        approved_sha256="f339890a869284bb39dc16ed6f52acc21d74a73d6e419088697e46ee0b54eaf2",
        approved_size_bytes=88_606_408,
    ),
    ModelWeightSpec(
        component="arcface_r50",
        repo_id="py-feat/arcface_r50",
        filenames=("arcface_r50.safetensors",),
        environment_override="FEAT_ARCFACE_R50_PATH",
        approved_revision="1e2637bc33aef12c2eeec84f76080509f9d5ab0d",
        approved_sha256="911ba0172feb170e53f2eb94fb2f29099bc722cb82a2c14147bbedd253056313",
        approved_size_bytes=174_387_800,
    ),
    ModelWeightSpec(
        component="face_multitask_v2",
        repo_id="py-feat/face_multitask_v2",
        filenames=("face_multitask_v27.safetensors",),
        environment_override="FEAT_MULTITASK_WEIGHTS",
        approved_revision="7c18f8da048b90f7bf135d6129bcf349960ec32f",
        approved_sha256="e3c870e22ba041d2aeb11ae7eaaf832fbb869413bca21d7486a805b8a4ddc8bd",
        approved_size_bytes=166_817_444,
    ),
)

_COMPONENT_SIGNATURE_FIELDS = (
    "source",
    "repo_id",
    "filename",
    "requested_revision",
    "snapshot_commit",
    "environment_variable",
    "size_bytes",
    "sha256",
)


def resolve_detector_v2_weights(cache_dir: Path | None) -> dict[str, object]:
    """Inspect all Detectorv2 checkpoints locally without downloading anything."""

    components = {
        spec.component: _resolve_component(spec, cache_dir)
        for spec in DETECTOR_V2_WEIGHT_SPECS
    }
    payload: dict[str, object] = {
        "schema_version": MODEL_WEIGHT_PROVENANCE_VERSION,
        "components": components,
    }
    payload["fingerprint"] = model_weight_set_fingerprint(payload)
    payload["status"] = "ready" if model_weights_ready(payload) else "incomplete"
    return payload


def prepare_approved_detector_v2_weights(cache_dir: Path) -> dict[str, object]:
    """Download only release-approved immutable checkpoint revisions."""

    if hf_hub_download is None:
        raise RuntimeError("huggingface_hub is required to prepare Face model weights")
    cache = Path(cache_dir).expanduser().resolve()
    for spec in DETECTOR_V2_WEIGHT_SPECS:
        path = Path(
            hf_hub_download(
                repo_id=spec.repo_id,
                filename=spec.filenames[0],
                revision=spec.approved_revision,
                cache_dir=cache,
            )
        )
        fingerprint = _file_fingerprint(path)
        if (
            fingerprint["sha256"] != spec.approved_sha256
            or fingerprint["size_bytes"] != spec.approved_size_bytes
        ):
            raise RuntimeError(
                f"Downloaded {spec.component} checkpoint does not match the approved release digest."
            )
    _cached_file_sha256.cache_clear()
    return resolve_detector_v2_weights(cache)


def model_weights_ready(payload: object) -> bool:
    """Return whether ``payload`` proves all three checkpoint contents."""

    if not isinstance(payload, Mapping):
        return False
    if payload.get("schema_version") != MODEL_WEIGHT_PROVENANCE_VERSION:
        return False
    components = payload.get("components")
    if not isinstance(components, Mapping):
        return False
    expected = {spec.component: spec for spec in DETECTOR_V2_WEIGHT_SPECS}
    if set(components) != set(expected):
        return False
    for component, spec in expected.items():
        record = components.get(component)
        if not isinstance(record, Mapping):
            return False
        if record.get("status") not in {"cached", "local-override"}:
            return False
        if record.get("repo_id") != spec.repo_id:
            return False
        if record.get("sha256") != spec.approved_sha256:
            return False
        if record.get("size_bytes") != spec.approved_size_bytes:
            return False
        if record.get("status") == "cached":
            if record.get("filename") not in spec.filenames:
                return False
        elif (
            not spec.environment_override
            or record.get("environment_variable") != spec.environment_override
            or not isinstance(record.get("filename"), str)
            or not record.get("filename")
        ):
            return False
        sha256 = record.get("sha256")
        size = record.get("size_bytes")
        if not isinstance(sha256, str) or len(sha256) != 64:
            return False
        try:
            int(sha256, 16)
        except ValueError:
            return False
        if not isinstance(size, int) or size <= 0:
            return False
        if record.get("status") == "cached":
            commit = record.get("snapshot_commit")
            if commit != spec.approved_revision:
                return False
    return payload.get("fingerprint") == model_weight_set_fingerprint(payload)


def model_weight_set_signature(payload: object) -> dict[str, object]:
    """Return portable model identity facts used by analysis resume checks.

    ``local_path`` is intentionally omitted: moving an identical cache should
    not invalidate analysis, while repository revision and content SHA still
    make different bytes a cache miss.
    """

    if not isinstance(payload, Mapping):
        return {"schema_version": None, "components": {}}
    raw_components = payload.get("components")
    components: dict[str, object] = {}
    if isinstance(raw_components, Mapping):
        for name in sorted(str(key) for key in raw_components):
            raw = raw_components.get(name)
            if not isinstance(raw, Mapping):
                components[name] = {"invalid": True}
                continue
            components[name] = {
                field: raw.get(field) for field in _COMPONENT_SIGNATURE_FIELDS
            }
    return {
        "schema_version": payload.get("schema_version"),
        "components": components,
    }


def model_weight_set_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        model_weight_set_signature(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def unavailable_model_components(payload: object) -> list[str]:
    """Summarize unavailable components for an actionable readiness error."""

    if not isinstance(payload, Mapping):
        return [spec.component for spec in DETECTOR_V2_WEIGHT_SPECS]
    components = payload.get("components")
    if not isinstance(components, Mapping):
        return [spec.component for spec in DETECTOR_V2_WEIGHT_SPECS]
    unavailable: list[str] = []
    for spec in DETECTOR_V2_WEIGHT_SPECS:
        record = components.get(spec.component)
        status = record.get("status") if isinstance(record, Mapping) else "missing"
        if status not in {"cached", "local-override"}:
            unavailable.append(f"{spec.component} ({status})")
    return unavailable


def _resolve_component(
    spec: ModelWeightSpec,
    cache_dir: Path | None,
) -> dict[str, object]:
    override = (
        os.environ.get(spec.environment_override)
        if spec.environment_override is not None
        else None
    )
    if override:
        path = Path(override).expanduser().resolve()
        base = {
            "component": spec.component,
            "source": "environment",
            "repo_id": spec.repo_id,
            "filename": path.name,
            "environment_variable": spec.environment_override,
            "local_path": str(path),
        }
        if not path.is_file():
            return {**base, "status": "missing"}
        fingerprint = _file_fingerprint(path)
        status = (
            "local-override"
            if fingerprint["sha256"] == spec.approved_sha256
            and fingerprint["size_bytes"] == spec.approved_size_bytes
            else "unapproved"
        )
        return {**base, "status": status, **fingerprint}

    base = {
        "component": spec.component,
        "source": "huggingface-cache",
        "repo_id": spec.repo_id,
        "candidate_filenames": list(spec.filenames),
        "requested_revision": spec.approved_revision,
    }
    if try_to_load_from_cache is None:
        return {**base, "status": "cache-inspection-unavailable"}
    if cache_dir is None:
        return {**base, "status": "py-feat-not-installed"}

    inspection_failed = False
    for filename in spec.filenames:
        try:
            cached = try_to_load_from_cache(
                repo_id=spec.repo_id,
                filename=filename,
                revision=spec.approved_revision,
                cache_dir=cache_dir,
            )
        except (OSError, ValueError):
            inspection_failed = True
            continue
        if not isinstance(cached, str):
            continue
        path = Path(cached)
        if not path.is_file():
            continue
        fingerprint = _file_fingerprint(path)
        snapshot_commit = _snapshot_commit(path) or "unknown"
        status = (
            "cached"
            if filename == spec.filenames[0]
            and snapshot_commit == spec.approved_revision
            and fingerprint["sha256"] == spec.approved_sha256
            and fingerprint["size_bytes"] == spec.approved_size_bytes
            else "unapproved"
        )
        return {
            **base,
            "status": status,
            "filename": filename,
            "snapshot_commit": snapshot_commit,
            "local_path": str(path.resolve()),
            **fingerprint,
        }
    return {
        **base,
        "status": "cache-inspection-error" if inspection_failed else "not-cached",
    }


def _snapshot_commit(path: Path) -> str | None:
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "snapshots" and index + 1 < len(parts):
            return parts[index + 1]
    return None


def _file_fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "sha256": _cached_file_sha256(
            str(path.resolve()), stat.st_size, stat.st_mtime_ns
        ),
    }


@lru_cache(maxsize=12)
def _cached_file_sha256(path: str, _size: int, _mtime_ns: int) -> str:
    """Avoid re-hashing unchanged multi-hundred-megabyte weights per run."""

    return file_sha256(Path(path))
