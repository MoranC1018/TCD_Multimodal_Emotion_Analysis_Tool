import json
from pathlib import Path

import pytest

from processing.io_utils import exclusive_process_lock
from processing.text_analysis import pipeline
from processing.text_analysis.pipeline import (
    EXTRA_CATEGORIES,
    TextProcessingConfig,
    _effective_rocksteady_categories,
    _postprocess_command,
    _rocksteady_command,
    _transcribe_command,
    check_text_processing_readiness,
    load_text_processing_config,
)
from processing.text_analysis.selection import build_selected_whisper_tree


def test_text_config_validation() -> None:
    with pytest.raises(ValueError, match="threads"):
        TextProcessingConfig(threads=0).validate()


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (TextProcessingConfig(whisper_model="imaginary"), "whisper_model"),
        (TextProcessingConfig(dictionaries="not-a-list"), "dictionaries"),
        (TextProcessingConfig(language_policy=[]), "language_policy"),
        (TextProcessingConfig(write_graphs="false"), "write_graphs"),
        (TextProcessingConfig(overwrite_rocksteady=1), "overwrite_rocksteady"),
        (TextProcessingConfig(input_path=""), "paths"),
    ],
)
def test_text_config_rejects_malformed_runtime_types(config: TextProcessingConfig, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        config.validate()


def test_rocksteady_command_is_total_and_repeats_categories(tmp_path: Path) -> None:
    config = TextProcessingConfig()
    command = _rocksteady_command(config, tmp_path, "csv", ("Positiv", "Strong"))
    assert command.count("--category") == 2
    assert command[command.index("--value-type") + 1] == "total"
    assert "--force" not in command


def test_default_policy_matches_the_english_dictionary() -> None:
    assert TextProcessingConfig().default_language_variant == "eng"
    assert TextProcessingConfig().dictionaries == (
        "embedded:affectDictionaries/General Language (En)(2011-07-05).dict.xml",
    )
    assert TextProcessingConfig().categories == ()
    assert "Positiv" in EXTRA_CATEGORIES


def test_language_selection_discovers_new_countries_and_allows_overrides(tmp_path: Path) -> None:
    whisper = tmp_path / "whisper"
    for variant in ("eng", "original"):
        for country in ("New Country", "Override Country"):
            stem = f"001_{country}_Speaker_20250101"
            path = whisper / variant / country / "Speaker" / f"{stem}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"segments": [{"id": 0, "text": f"{variant}:{country}"}]}),
                encoding="utf-8",
            )

    selected = tmp_path / "selected"
    count = build_selected_whisper_tree(
        whisper,
        selected,
        language_policy={"Override Country": "original"},
        default_variant="eng",
    )

    assert count == 2
    new_payload = json.loads(
        (selected / "New Country/Speaker/001_New Country_Speaker_20250101.json").read_text(encoding="utf-8")
    )
    override_payload = json.loads(
        (selected / "Override Country/Speaker/001_Override Country_Speaker_20250101.json").read_text(encoding="utf-8")
    )
    assert new_payload["segments"][0]["text"] == "eng:New Country"
    assert override_payload["segments"][0]["text"] == "original:Override Country"


def test_postprocess_command_preserves_current_output_layout(tmp_path: Path) -> None:
    config = TextProcessingConfig()
    command = _postprocess_command(config, tmp_path, config.extra_csv_root, "extra")
    output = Path(command[command.index("--output-root") + 1])
    assert output == (tmp_path / "analysis/output/text/text_output/extra").resolve()
    assert Path(command[command.index("--prepare-root") + 1]) == (
        tmp_path / "processing/text_analysis/output/current/prepared_segments"
    ).resolve()


def test_transcribe_command_recognizes_procurement_run_without_canonical_names(
    tmp_path: Path,
) -> None:
    run = tmp_path / "procurement" / "output" / "run"
    (run / "downloads").mkdir(parents=True)
    config = TextProcessingConfig(input_path=str(run))

    command = _transcribe_command(config, tmp_path)

    assert command[command.index("--from-procurement") + 1] == str(run.resolve())
    assert "--canonical-layout" not in command
    assert "--speaker-parent-layout" not in command


def test_transcribe_command_uses_parent_identity_for_general_media_folder(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "custom-media"
    media_root.mkdir()
    config = TextProcessingConfig(input_path=str(media_root))

    command = _transcribe_command(config, tmp_path)

    assert str(media_root.resolve()) in command
    assert "--speaker-parent-layout" in command
    assert "--canonical-layout" not in command


def test_shared_config_loader_supports_json_and_explicit_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "text.json"
    config_path.write_text(
        json.dumps({"threads": 2, "dictionaries": ["file:custom.xml"]}),
        encoding="utf-8",
    )

    config = load_text_processing_config(
        config_path,
        input_path="new-input",
        overrides={"threads": 3, "write_graphs": None},
    )

    assert config.input_path == "new-input"
    assert config.threads == 3
    assert config.dictionaries == ("file:custom.xml",)
    assert config.write_graphs is True


def test_shared_config_loader_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "text.json"
    config_path.write_text('{"surprise": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown text config keys: surprise"):
        load_text_processing_config(config_path)


def test_explicit_categories_automatically_preserve_the_core_output_contract() -> None:
    config = TextProcessingConfig(categories=("Risk",)).validate()
    assert _effective_rocksteady_categories(config.categories) == (
        "Active",
        "Negativ",
        "Passive",
        "Positiv",
        "Strong",
        "Weak",
        "Risk",
    )


def test_default_rocksteady_command_explicitly_ignores_local_category_filters(
    tmp_path: Path,
) -> None:
    command = _rocksteady_command(TextProcessingConfig(), tmp_path, "csv", ())
    assert "--all-categories" in command
    assert "--category" not in command


def test_pipeline_preflights_before_first_expensive_stage(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "001_UK_Test_Speaker_20250101.mp4"
    video.write_bytes(b"media")
    order: list[str] = []

    def fake_preflight(_config, *, stages):
        assert stages == ("transcribe", "select", "prepare", "rocksteady")
        assert not (tmp_path / "processing/text_analysis/output").exists()
        order.append("preflight")
        return {"status": "ready"}

    def fail_first_command(_command, _cwd):
        order.append("stage-command")
        running = json.loads(
            (tmp_path / "processing/text_analysis/output/pipeline_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert running["status"] == "running"
        assert running["stages"][0]["status"] == "running"
        raise RuntimeError("stop after ordering assertion")

    monkeypatch.setattr(pipeline, "check_text_processing_readiness", fake_preflight)
    monkeypatch.setattr(pipeline, "_run", fail_first_command)

    with pytest.raises(RuntimeError, match="ordering assertion"):
        pipeline.run_text_pipeline(
            TextProcessingConfig(input_path=str(video)),
            to_stage="rocksteady",
            repo_root=tmp_path,
            run_id="shared-run-id",
        )

    assert order == ["preflight", "stage-command"]
    failed = json.loads(
        (tmp_path / "processing/text_analysis/output/pipeline_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert failed["run_id"] == "shared-run-id"
    assert failed["status"] == "failed"
    assert failed["stages"][0]["command"]
    assert failed["inventory"] == {
        "digest": pipeline.inventory_digest([]),
        "inventory_sha256": pipeline.inventory_digest([]),
        "items": [],
    }


def test_missing_whisper_preflight_leaves_the_entire_tree_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "001_UK_Test_Speaker_20250101.mp4"
    video.write_bytes(b"media")
    before = {
        path.relative_to(tmp_path).as_posix(): (
            "file" if path.is_file() else "directory",
            path.read_bytes() if path.is_file() else None,
        )
        for path in tmp_path.rglob("*")
    }
    monkeypatch.setattr(
        pipeline,
        "collect_whisper_execution_identity",
        lambda _model: (_ for _ in ()).throw(
            ModuleNotFoundError("No module named 'whisper'")
        ),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="Whisper preflight failed"):
        pipeline.run_text_pipeline(
            TextProcessingConfig(input_path=str(video)),
            to_stage="transcribe",
            repo_root=tmp_path,
        )

    after = {
        path.relative_to(tmp_path).as_posix(): (
            "file" if path.is_file() else "directory",
            path.read_bytes() if path.is_file() else None,
        )
        for path in tmp_path.rglob("*")
    }
    assert after == before


def test_pipeline_does_not_require_rocksteady_when_range_stops_at_prepare(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "001_UK_Test_Speaker_20250101.mp4"
    video.write_bytes(b"media")

    def fake_preflight(_config, *, stages):
        assert "transcribe" in stages
        assert "rocksteady" not in stages
        return {"status": "ready"}

    monkeypatch.setattr(pipeline, "check_text_processing_readiness", fake_preflight)
    monkeypatch.setattr(
        pipeline, "_run", lambda _command, _cwd: (_ for _ in ()).throw(RuntimeError("stop"))
    )

    with pytest.raises(RuntimeError, match="stop"):
        pipeline.run_text_pipeline(
            TextProcessingConfig(input_path=str(video)),
            to_stage="prepare",
            repo_root=tmp_path,
        )


def test_pipeline_records_user_interruption_as_cancelled(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "001_UK_Test_Speaker_20250101.mp4"
    video.write_bytes(b"media")
    monkeypatch.setattr(
        pipeline,
        "_run",
        lambda _command, _cwd: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(
        pipeline,
        "check_text_processing_readiness",
        lambda *_args, **_kwargs: {"status": "ready"},
    )

    with pytest.raises(KeyboardInterrupt):
        pipeline.run_text_pipeline(
            TextProcessingConfig(input_path=str(video)),
            to_stage="transcribe",
            repo_root=tmp_path,
            run_id="cancelled-run",
        )

    payload = json.loads(
        (tmp_path / "processing/text_analysis/output/pipeline_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["status"] == "cancelled"
    assert payload["finished_at"]
    assert payload["stages"][0]["status"] == "cancelled"
    assert payload["summary"]["cancelled_stages"] == 1


def test_pipeline_preflights_requested_output_ownership_before_whisper(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "001_UK_Test_Speaker_20250101.mp4"
    video.write_bytes(b"media")
    selected = (
        tmp_path
        / "processing/text_analysis/output/current/selected_transcripts"
    )
    selected.mkdir(parents=True)
    (selected / "personal.txt").write_text("do not replace", encoding="utf-8")
    monkeypatch.setattr(
        pipeline,
        "_run",
        lambda *_args: pytest.fail("Whisper must not start after a failed output preflight"),
    )

    with pytest.raises(ValueError, match="without a valid ownership marker"):
        pipeline.run_text_pipeline(
            TextProcessingConfig(input_path=str(video)),
            to_stage="select",
            repo_root=tmp_path,
        )


def test_readiness_uses_the_exact_pipeline_dictionary_and_category_config(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    def fake_load(_path, args):
        captured["dictionary"] = args.dictionary
        captured["category"] = args.category
        captured["all_categories"] = args.all_categories
        return "adapter-settings"

    monkeypatch.setattr(pipeline, "load_rocksteady_settings", fake_load)
    monkeypatch.setattr(pipeline, "resolve_rocksteady_home", lambda *_args: tmp_path)
    monkeypatch.setattr(
        pipeline,
        "check_runtime",
        lambda home, settings: (["Active", "Positiv"], home / "app.jar", home / "classes"),
    )
    monkeypatch.setattr(
        pipeline,
        "collect_whisper_execution_identity",
        lambda model: {
            "engine": {"distribution": "openai-whisper", "version": "test"},
            "checkpoint": {"requested_name": model},
            "runtime": {"torch_version": "test", "ffmpeg_version": "test"},
        },
    )
    config = TextProcessingConfig()

    result = check_text_processing_readiness(config)

    assert captured == {
        "dictionary": list(config.dictionaries),
        "category": None,
        "all_categories": True,
    }
    assert result["status"] == "ready"
    assert result["category_count"] == 2


def test_pipeline_rejects_a_concurrent_live_run(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "001_UK_Test_Speaker_20250101.mp4"
    video.write_bytes(b"media")
    lock = tmp_path / "processing/text_analysis/output/.pipeline.run.lock"
    monkeypatch.setattr(
        pipeline,
        "check_text_processing_readiness",
        lambda *_args, **_kwargs: {"status": "ready"},
    )

    with exclusive_process_lock(lock, purpose="test live Text run"):
        with pytest.raises(RuntimeError, match="Another process is running the Text"):
            pipeline.run_text_pipeline(
                TextProcessingConfig(input_path=str(video)),
                to_stage="transcribe",
                repo_root=tmp_path,
            )


def test_pipeline_recovers_an_abandoned_run_lock(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "001_UK_Test_Speaker_20250101.mp4"
    video.write_bytes(b"media")
    lock = tmp_path / "processing/text_analysis/output/.pipeline.run.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        json.dumps(
            {
                "lock_id": "abandoned",
                "pid": 999999,
                "process_started_at_unix": 0,
                "purpose": "old Text run",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pipeline, "_run", lambda _command, _cwd: (_ for _ in ()).throw(RuntimeError("stop"))
    )
    monkeypatch.setattr(
        pipeline,
        "check_text_processing_readiness",
        lambda *_args, **_kwargs: {"status": "ready"},
    )

    with pytest.raises(RuntimeError, match="stop"):
        pipeline.run_text_pipeline(
            TextProcessingConfig(input_path=str(video)),
            to_stage="transcribe",
            repo_root=tmp_path,
        )

    assert not lock.exists()
