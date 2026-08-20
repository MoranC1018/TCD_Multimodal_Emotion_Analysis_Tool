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
    for index, spec in enumerate(model_provenance.DETECTOR_V2_WEIGHT_SPECS, 1):
        content = f"checkpoint-{spec.component}".encode()
        cached[(spec.repo_id, spec.filenames[0])] = _cached_file(
            tmp_path,
            spec.repo_id,
            str(index) * 40,
            spec.filenames[0],
            content,
        )
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
    for index, spec in enumerate(model_provenance.DETECTOR_V2_WEIGHT_SPECS, 1):
        record = payload["components"][spec.component]
        content = f"checkpoint-{spec.component}".encode()
        assert record["repo_id"] == spec.repo_id
        assert record["filename"] == spec.filenames[0]
        assert record["snapshot_commit"] == str(index) * 40
        assert record["size_bytes"] == len(content)
        assert record["sha256"] == hashlib.sha256(content).hexdigest()
        assert Path(record["local_path"]).is_file()


def test_retinaface_legacy_filename_is_recorded_when_primary_is_absent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    retina = model_provenance.DETECTOR_V2_WEIGHT_SPECS[0]
    fallback = _cached_file(
        tmp_path,
        retina.repo_id,
        "a" * 40,
        retina.filenames[1],
        b"legacy retinaface",
    )

    def lookup(**kwargs):
        if kwargs["repo_id"] == retina.repo_id:
            return None if kwargs["filename"] == retina.filenames[0] else str(fallback)
        return None

    monkeypatch.setattr(model_provenance, "try_to_load_from_cache", lookup)
    payload = model_provenance.resolve_detector_v2_weights(tmp_path)

    record = payload["components"]["retinaface_r34"]
    assert record["status"] == "cached"
    assert record["filename"] == "retinaface_r34.safetensors"
    assert payload["status"] == "incomplete"


def test_arcface_and_multitask_environment_overrides_are_fingerprinted(
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
    assert arcface_record["status"] == "local-override"
    assert arcface_record["environment_variable"] == "FEAT_ARCFACE_R50_PATH"
    assert arcface_record["sha256"] == hashlib.sha256(b"arcface").hexdigest()
    assert multitask_record["status"] == "local-override"
    assert multitask_record["environment_variable"] == "FEAT_MULTITASK_WEIGHTS"
    assert multitask_record["sha256"] == hashlib.sha256(b"multitask").hexdigest()
    assert payload["status"] == "ready"
    assert model_provenance.model_weights_ready(payload)
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
