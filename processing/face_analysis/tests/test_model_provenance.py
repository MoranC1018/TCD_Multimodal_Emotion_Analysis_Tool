from __future__ import annotations

import hashlib
from pathlib import Path

from processing.face_analysis import model_provenance


def _cached_file(
    cache: Path,
    repo_id: str,
    commit: str,
    filename: str,
    content: bytes,
) -> Path:
    path = (
        cache
        / f"models--{repo_id.replace('/', '--')}"
        / "snapshots"
        / commit
        / filename
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_all_detector_v2_weights_include_commit_size_and_content_hash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cached: dict[tuple[str, str], Path] = {}
    specs = []
    for index, spec in enumerate(model_provenance.DETECTOR_V2_WEIGHT_SPECS, 1):
        content = f"checkpoint-{spec.component}".encode()
        spec = model_provenance.ModelWeightSpec(
            component=spec.component,
            repo_id=spec.repo_id,
            filenames=(spec.filenames[0],),
            environment_override=spec.environment_override,
            approved_revision=str(index) * 40,
            approved_sha256=hashlib.sha256(content).hexdigest(),
            approved_size_bytes=len(content),
        )
        specs.append(spec)
        cached[(spec.repo_id, spec.filenames[0])] = _cached_file(
            tmp_path,
            spec.repo_id,
            str(index) * 40,
            spec.filenames[0],
            content,
        )
    monkeypatch.setattr(model_provenance, "DETECTOR_V2_WEIGHT_SPECS", tuple(specs))
    monkeypatch.delenv("FEAT_ARCFACE_R50_PATH", raising=False)
    monkeypatch.delenv("FEAT_MULTITASK_WEIGHTS", raising=False)
    monkeypatch.setattr(
        model_provenance,
        "try_to_load_from_cache",
        lambda **kwargs: str(cached[(kwargs["repo_id"], kwargs["filename"])]),
    )

    payload = model_provenance.resolve_detector_v2_weights(tmp_path)

    assert payload["status"] == "ready"
    assert model_provenance.model_weights_ready(payload)
    assert len(payload["fingerprint"]) == 64
    for index, spec in enumerate(specs, 1):
        record = payload["components"][spec.component]
        content = f"checkpoint-{spec.component}".encode()
        assert record["repo_id"] == spec.repo_id
        assert record["filename"] == spec.filenames[0]
        assert record["snapshot_commit"] == str(index) * 40
        assert record["size_bytes"] == len(content)
        assert record["sha256"] == hashlib.sha256(content).hexdigest()
        assert Path(record["local_path"]).is_file()


def test_cache_lookup_uses_approved_revision_and_rejects_unapproved_bytes(monkeypatch, tmp_path: Path) -> None:
    content = b"approved"
    spec = model_provenance.ModelWeightSpec(
        component="component",
        repo_id="owner/model",
        filenames=("model.safetensors",),
        approved_revision="a" * 40,
        approved_sha256=hashlib.sha256(content).hexdigest(),
        approved_size_bytes=len(content),
    )
    cached = _cached_file(tmp_path, spec.repo_id, spec.approved_revision, spec.filenames[0], b"tampered")
    seen = {}

    def lookup(**kwargs):
        seen.update(kwargs)
        return str(cached)

    monkeypatch.setattr(model_provenance, "try_to_load_from_cache", lookup)
    record = model_provenance._resolve_component(spec, tmp_path)

    assert seen["revision"] == spec.approved_revision
    assert record["status"] == "unapproved"


def test_model_preparation_downloads_only_approved_revisions(monkeypatch, tmp_path: Path) -> None:
    specs = []
    downloads = []
    for index, original in enumerate(model_provenance.DETECTOR_V2_WEIGHT_SPECS, start=1):
        content = f"approved-{index}".encode()
        spec = model_provenance.ModelWeightSpec(
            component=original.component,
            repo_id=original.repo_id,
            filenames=(original.filenames[0],),
            environment_override=original.environment_override,
            approved_revision=str(index) * 40,
            approved_sha256=hashlib.sha256(content).hexdigest(),
            approved_size_bytes=len(content),
        )
        specs.append(spec)

    def download(**kwargs):
        downloads.append(kwargs)
        spec = next(item for item in specs if item.repo_id == kwargs["repo_id"])
        return str(
            _cached_file(
                tmp_path,
                spec.repo_id,
                spec.approved_revision,
                spec.filenames[0],
                f"approved-{specs.index(spec) + 1}".encode(),
            )
        )

    monkeypatch.setattr(model_provenance, "DETECTOR_V2_WEIGHT_SPECS", tuple(specs))
    monkeypatch.setattr(model_provenance, "hf_hub_download", download)
    monkeypatch.setattr(
        model_provenance,
        "try_to_load_from_cache",
        lambda **kwargs: str(
            tmp_path
            / f"models--{kwargs['repo_id'].replace('/', '--')}"
            / "snapshots"
            / kwargs["revision"]
            / kwargs["filename"]
        ),
    )

    payload = model_provenance.prepare_approved_detector_v2_weights(tmp_path)

    assert model_provenance.model_weights_ready(payload)
    assert [item["revision"] for item in downloads] == [spec.approved_revision for spec in specs]


def test_retinaface_unpinned_legacy_filename_is_not_considered(
    monkeypatch,
    tmp_path: Path,
) -> None:
    retina = model_provenance.DETECTOR_V2_WEIGHT_SPECS[0]
    _cached_file(
        tmp_path,
        retina.repo_id,
        "a" * 40,
        "retinaface_r34.safetensors",
        b"legacy retinaface",
    )

    def lookup(**kwargs):
        if kwargs["repo_id"] == retina.repo_id:
            return None
        return None

    monkeypatch.setattr(model_provenance, "try_to_load_from_cache", lookup)
    payload = model_provenance.resolve_detector_v2_weights(tmp_path)

    record = payload["components"]["retinaface_r34"]
    assert record["status"] == "not-cached"
    assert record["candidate_filenames"] == ["model.safetensors"]
    assert payload["status"] == "incomplete"


def test_unapproved_arcface_and_multitask_environment_overrides_are_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    arcface = tmp_path / "custom-identity.safetensors"
    multitask = tmp_path / "custom-multitask.pt"
    arcface.write_bytes(b"arcface")
    multitask.write_bytes(b"multitask")
    retina_spec = model_provenance.DETECTOR_V2_WEIGHT_SPECS[0]
    retina = _cached_file(
        tmp_path,
        retina_spec.repo_id,
        "d" * 40,
        retina_spec.filenames[0],
        b"retinaface",
    )
    monkeypatch.setenv("FEAT_ARCFACE_R50_PATH", str(arcface))
    monkeypatch.setenv("FEAT_MULTITASK_WEIGHTS", str(multitask))
    monkeypatch.setattr(
        model_provenance,
        "try_to_load_from_cache",
        lambda **kwargs: str(retina)
        if kwargs["repo_id"] == retina_spec.repo_id
        else None,
    )

    payload = model_provenance.resolve_detector_v2_weights(tmp_path)

    arcface_record = payload["components"]["arcface_r50"]
    multitask_record = payload["components"]["face_multitask_v2"]
    assert arcface_record["status"] == "unapproved"
    assert arcface_record["environment_variable"] == "FEAT_ARCFACE_R50_PATH"
    assert arcface_record["sha256"] == hashlib.sha256(b"arcface").hexdigest()
    assert multitask_record["status"] == "unapproved"
    assert multitask_record["environment_variable"] == "FEAT_MULTITASK_WEIGHTS"
    assert multitask_record["sha256"] == hashlib.sha256(b"multitask").hexdigest()
    assert payload["status"] == "incomplete"
    assert not model_provenance.model_weights_ready(payload)
    for record in (arcface_record, multitask_record):
        assert record["size_bytes"] > 0


def test_weight_signature_ignores_machine_local_path_but_not_content() -> None:
    spec = model_provenance.DETECTOR_V2_WEIGHT_SPECS[0]
    payload = {
        "schema_version": model_provenance.MODEL_WEIGHT_PROVENANCE_VERSION,
        "components": {
            spec.component: {
                "source": "huggingface-cache",
                "repo_id": spec.repo_id,
                "filename": spec.filenames[0],
                "requested_revision": "main",
                "snapshot_commit": "a" * 40,
                "local_path": "C:/first/cache/model.safetensors",
                "size_bytes": 10,
                "sha256": "b" * 64,
            }
        },
    }
    moved = {
        **payload,
        "components": {
            spec.component: {
                **payload["components"][spec.component],
                "local_path": "D:/other/cache/model.safetensors",
            }
        },
    }

    assert model_provenance.model_weight_set_signature(payload) == (
        model_provenance.model_weight_set_signature(moved)
    )
    moved["components"][spec.component]["sha256"] = "c" * 64
    assert model_provenance.model_weight_set_signature(payload) != (
        model_provenance.model_weight_set_signature(moved)
    )


def test_missing_component_never_reports_ready(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FEAT_ARCFACE_R50_PATH", raising=False)
    monkeypatch.delenv("FEAT_MULTITASK_WEIGHTS", raising=False)
    monkeypatch.setattr(model_provenance, "try_to_load_from_cache", lambda **_kwargs: None)

    payload = model_provenance.resolve_detector_v2_weights(tmp_path)

    assert payload["status"] == "incomplete"
    assert not model_provenance.model_weights_ready(payload)
    assert model_provenance.unavailable_model_components(payload) == [
        "retinaface_r34 (not-cached)",
        "arcface_r50 (not-cached)",
        "face_multitask_v2 (not-cached)",
    ]
