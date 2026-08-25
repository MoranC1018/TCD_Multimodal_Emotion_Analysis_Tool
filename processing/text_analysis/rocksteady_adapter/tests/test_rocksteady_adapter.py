from __future__ import annotations

import argparse
import csv
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from processing.text_analysis.rocksteady_adapter import runner


def namespace(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "dictionary": None,
        "dictionary_combination": None,
        "analyser": None,
        "value_type": None,
        "category": None,
        "threads": None,
        "timeout": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def make_video(root: Path, *, count: int = 2, text: str = "good future") -> Path:
    video = root / "France" / "Example Speaker" / "001_France_Example_Speaker_20260101"
    video.mkdir(parents=True)
    for index in range(1, count + 1):
        (video / f"{video.name}__segment_{index:06d}.txt").write_text(
            text, encoding="utf-8"
        )
    return video


def write_valid_csv(path: Path, video: Path, *, terms: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([*runner.IDENTITY_COLUMNS, "Positiv"])
        for source in runner.segment_files(video):
            writer.writerow([source.stem, "", 1, terms, "", 1])


def test_default_runtime_is_repository_local() -> None:
    expected = runner.REPOSITORY_ROOT / "external" / "RockSteady"
    assert runner.resolve_rocksteady_home(None) == expected.resolve()


def test_explicit_runtime_takes_precedence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MULTIMODAL_EMOTION_ROCKSTEADY_HOME", str(tmp_path / "env"))
    explicit = tmp_path / "explicit"
    assert runner.resolve_rocksteady_home(explicit) == explicit.resolve()


def test_config_runtime_is_repository_relative(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"rocksteady_home": "external/RockSteady"}', encoding="utf-8")
    assert runner.resolve_rocksteady_home(None, config) == runner.DEFAULT_ROCKSTEADY_HOME.resolve()


def test_default_settings_and_cli_overrides(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "dictionaries": {
                    "combination": "merge",
                    "items": [{"source": "file", "path": "GI/custom.dict.xml"}],
                },
                "analyser": {"type": "simple", "threads": 2},
                "value_type": "percentage",
                "categories": ["Positiv"],
                "timeout_seconds": 20,
            }
        ),
        encoding="utf-8",
    )
    settings = runner.load_settings(config, namespace(threads=3, value_type="total"))
    assert settings.dictionaries == (runner.DictionarySpec("file", "GI/custom.dict.xml"),)
    assert settings.threads == 3
    assert settings.value_type == "total"
    assert settings.categories == ("Positiv",)
    assert settings.timeout_seconds == 20


def test_adapter_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"application_jar": "silently-ignored-before.jar"}', encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown RockSteady adapter config keys"):
        runner.load_settings(config, namespace())


def test_runtime_rejects_a_dictionary_with_zero_export_categories(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "RockSteady"
    home.mkdir()
    (home / runner.APPLICATION_JAR_NAME).write_bytes(b"jar")
    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(runner, "validate_runtime_configuration", lambda *_args: [])

    with pytest.raises(RuntimeError, match="zero export categories"):
        runner.check_runtime(home, runner.Settings())


def test_nonfunctional_pos_analyser_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-functional POS"):
        runner.load_settings(None, namespace(analyser="pos"))


@pytest.mark.parametrize("value", ["0m", "2x", "-1g", "m"])
def test_invalid_heap_values_are_rejected(value: str, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"minimum_heap": value}), encoding="utf-8")
    with pytest.raises(ValueError, match="heap"):
        runner.load_settings(config, namespace())


def test_minimum_heap_must_not_exceed_maximum(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"minimum_heap": "3g", "maximum_heap": "2g"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="must not exceed"):
        runner.load_settings(config, namespace())


def test_discover_single_and_batch_jobs(tmp_path: Path) -> None:
    video = make_video(tmp_path / "input")
    single, is_single = runner.discover_jobs(video, tmp_path / "one.csv")
    assert is_single is True
    assert single[0].identity == "France/Example Speaker/001_France_Example_Speaker_20260101"

    batch, is_single = runner.discover_jobs(tmp_path / "input", tmp_path / "output")
    assert is_single is False
    assert len(batch) == 1
    assert batch[0].output_csv.relative_to(tmp_path / "output").as_posix() == (
        "France/Example Speaker/001_France_Example_Speaker_20260101.csv"
    )

    rooted, rooted_is_single = runner.discover_jobs(
        video, tmp_path / "rooted", output_is_root=True
    )
    assert rooted_is_single is True
    assert rooted[0].output_csv.relative_to(tmp_path / "rooted").as_posix() == (
        "France/Example Speaker/001_France_Example_Speaker_20260101.csv"
    )


def test_inventory_jobs_accept_procurement_speaker_video_identity(tmp_path: Path) -> None:
    input_root = tmp_path / "prepared"
    identity = "Test Speaker/YouTubeti_[abc123]"
    video = input_root / identity
    video.mkdir(parents=True)
    (video / "YouTubeti_[abc123]__segment_000001.txt").write_text(
        "segment text", encoding="utf-8"
    )

    jobs, is_single = runner.discover_jobs(
        input_root,
        tmp_path / "output",
        identities={identity},
    )

    assert is_single is False
    assert jobs[0].identity == identity
    assert jobs[0].output_csv.relative_to(tmp_path / "output").as_posix() == (
        "Test Speaker/YouTubeti_[abc123].csv"
    )


def test_batch_discovery_ignores_interrupted_hidden_staging_directories(tmp_path: Path) -> None:
    video = make_video(tmp_path / "input")
    staging = video.parent / ".segments_interrupted"
    staging.mkdir()
    (staging / f"{video.name}__segment_000001.txt").write_text("temporary", encoding="utf-8")

    jobs, is_single = runner.discover_jobs(tmp_path / "input", tmp_path / "output")

    assert is_single is False
    assert [job.input_dir for job in jobs] == [video.resolve()]


def test_legacy_batch_discovery_rejects_linked_video_directory_outside_root(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    speaker = input_root / "Country" / "Speaker"
    speaker.mkdir(parents=True)
    outside = make_video(tmp_path / "outside")
    alias = speaker / outside.name
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link|reparse|outside"):
        runner.discover_jobs(input_root, tmp_path / "output")


def test_single_video_output_error_points_to_output_root(tmp_path: Path) -> None:
    video = make_video(tmp_path / "input")
    with pytest.raises(ValueError, match="use --output-root"):
        runner.discover_jobs(video, tmp_path / "not-a-csv")


def test_segment_gap_is_rejected(tmp_path: Path) -> None:
    video = make_video(tmp_path, count=1)
    (video / f"{video.name}__segment_000003.txt").write_text("gap", encoding="utf-8")
    with pytest.raises(ValueError, match="contiguous"):
        runner.segment_files(video)


def test_validate_csv_rejects_false_success_with_zero_terms(tmp_path: Path) -> None:
    video = make_video(tmp_path / "input", count=1)
    output = tmp_path / "output.csv"
    write_valid_csv(output, video, terms=0)
    with pytest.raises(ValueError, match="Terms=0"):
        runner.validate_csv(output, video, "total")


def test_validate_csv_accepts_matching_total_output(tmp_path: Path) -> None:
    video = make_video(tmp_path / "input")
    output = tmp_path / "output.csv"
    write_valid_csv(output, video)
    result = runner.validate_csv(output, video, "total")
    assert result["rows"] == 2
    assert result["categories"] == ["Positiv"]


@pytest.mark.parametrize("bad_value", ["NaN", "Infinity", "-Infinity"])
def test_validate_csv_rejects_non_finite_values(tmp_path: Path, bad_value: str) -> None:
    video = make_video(tmp_path / "input", count=1)
    output = tmp_path / "output.csv"
    write_valid_csv(output, video)
    rows = output.read_text(encoding="utf-8").splitlines()
    fields = rows[1].split(",")
    fields[-1] = bad_value
    output.write_text("\n".join([rows[0], ",".join(fields)]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Non-finite"):
        runner.validate_csv(output, video, "total")


def test_validate_csv_binds_categories_hash_and_integer_totals(tmp_path: Path) -> None:
    video = make_video(tmp_path / "input", count=1)
    output = tmp_path / "output.csv"
    write_valid_csv(output, video)
    digest = runner.sha256_file(output)
    runner.validate_csv(
        output,
        video,
        "total",
        expected_categories=["Positiv"],
        expected_sha256=digest,
    )
    with pytest.raises(ValueError, match="categories"):
        runner.validate_csv(output, video, "total", expected_categories=["Strong"])
    with pytest.raises(ValueError, match="content hash"):
        runner.validate_csv(output, video, "total", expected_sha256="0" * 64)

    text = output.read_text(encoding="utf-8").replace(",1\n", ",1.5\n")
    output.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="Non-integer total"):
        runner.validate_csv(output, video, "total")


def test_inventory_authoritatively_filters_batch_discovery(tmp_path: Path) -> None:
    first = make_video(tmp_path / "input")
    second = (
        tmp_path / "input" / "UK" / "Another Speaker" /
        "002_UK_Another_Speaker_20250102"
    )
    second.mkdir(parents=True)
    (second / f"{second.name}__segment_000001.txt").write_text("text", encoding="utf-8")

    jobs, is_single = runner.discover_jobs(
        tmp_path / "input",
        tmp_path / "output",
        identities={"France/Example Speaker/001_France_Example_Speaker_20260101"},
    )

    assert is_single is False
    assert [job.input_dir for job in jobs] == [first.resolve()]


def test_inventory_does_not_validate_unrelated_stale_segment_directories(
    tmp_path: Path,
) -> None:
    current = make_video(tmp_path / "input", count=1)
    stale = (
        tmp_path
        / "input"
        / "UK"
        / "Old Speaker"
        / "002_UK_Old_Speaker_20240101"
    )
    stale.mkdir(parents=True)
    (stale / f"{stale.name}__segment_000002.txt").write_text("gap", encoding="utf-8")

    jobs, _ = runner.discover_jobs(
        tmp_path / "input",
        tmp_path / "output",
        identities={"France/Example Speaker/001_France_Example_Speaker_20260101"},
    )

    assert [job.input_dir for job in jobs] == [current.resolve()]


def test_check_cli_needs_no_input_or_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runner,
        "check_runtime",
        lambda _home, _settings: (["Positiv"], tmp_path / "application.jar", tmp_path / "classes"),
    )
    monkeypatch.setattr(runner, "resolve_rocksteady_home", lambda *_args: tmp_path)

    assert runner.main(["--check", "--all-categories"]) == 0
    assert "ROCKSTEADY_CHECK_OK" in capsys.readouterr().out


def test_completed_job_is_safely_skipped_on_next_run(tmp_path: Path, monkeypatch) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    application_jar = rocksteady_home / runner.APPLICATION_JAR_NAME
    with zipfile.ZipFile(application_jar, "w") as archive:
        archive.writestr(runner.DEFAULT_DICTIONARY, b"dictionary")
    video = make_video(tmp_path / "input", count=1)
    output = tmp_path / "output" / "result.csv"
    job = runner.VideoJob(video, output, "France/Example Speaker/example")
    calls = 0

    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(runner, "require_executable", lambda name: name)
    monkeypatch.setattr(
        runner, "validate_runtime_configuration", lambda *_args: ["Positiv"]
    )

    def fake_run(command, _home, _timeout):
        nonlocal calls
        calls += 1
        partial = Path(command[command.index("--output") + 1])
        write_valid_csv(partial, video)
        return "ROCKSTEADY_ADAPTER_OK rows=1 columns=6"

    monkeypatch.setattr(runner, "run_java", fake_run)
    settings = runner.Settings()
    first, failures = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=None,
    )
    second, failures_again = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=None,
    )
    third, failures_third = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=None,
    )
    assert (failures, failures_again, failures_third) == (0, 0, 0)
    assert [first[0]["status"], second[0]["status"], third[0]["status"]] == [
        "completed",
        "skipped",
        "skipped",
    ]
    assert calls == 1
    manifest_path = runner.manifest_path_for_job(job)
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert manifest_path == (
        output.parent
        / "_manifests"
        / "France"
        / "Example Speaker"
        / "example.csv.manifest.json"
    )
    assert str(tmp_path) not in manifest_text


def test_java_processes_an_immutable_segment_snapshot(tmp_path: Path, monkeypatch) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    application_jar = rocksteady_home / runner.APPLICATION_JAR_NAME
    with zipfile.ZipFile(application_jar, "w") as archive:
        archive.writestr(runner.DEFAULT_DICTIONARY, b"dictionary")
    video = make_video(tmp_path / "input", count=1)
    original_segment = next(video.glob("*.txt"))
    job = runner.VideoJob(video, tmp_path / "output" / "result.csv", "Country/Speaker/Video")
    observed_input = None

    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(runner, "require_executable", lambda name: name)
    monkeypatch.setattr(runner, "validate_runtime_configuration", lambda *_args: ["Positiv"])

    def fake_run(command, _home, _timeout):
        nonlocal observed_input
        observed_input = Path(command[command.index("--input") + 1])
        original_segment.write_text("mutated after snapshot", encoding="utf-8")
        write_valid_csv(Path(command[command.index("--output") + 1]), observed_input)
        return "ROCKSTEADY_ADAPTER_OK rows=1 columns=6"

    monkeypatch.setattr(runner, "run_java", fake_run)
    records, failures = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=runner.Settings(),
        force=True,
        dry_run=False,
        batch_manifest_path=None,
    )

    assert failures == 0
    assert records[0]["status"] == "completed"
    assert observed_input is not None
    assert observed_input != video
    assert not observed_input.exists()


def test_snapshot_removes_stale_csvs_and_cache_restores_later_full_run(
    tmp_path: Path, monkeypatch
) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    application_jar = rocksteady_home / runner.APPLICATION_JAR_NAME
    with zipfile.ZipFile(application_jar, "w") as archive:
        archive.writestr(runner.DEFAULT_DICTIONARY, b"dictionary")

    first_video = make_video(tmp_path / "input", count=1)
    second_video = first_video.with_name("002_France_Example_Speaker_20260102")
    second_video.mkdir()
    (second_video / f"{second_video.name}__segment_000001.txt").write_text(
        "another speech", encoding="utf-8"
    )
    output_root = tmp_path / "results"
    jobs = [
        runner.VideoJob(
            first_video,
            output_root / "France/Example Speaker/001_France_Example_Speaker_20260101.csv",
            "France/Example Speaker/001_France_Example_Speaker_20260101",
            output_root,
        ),
        runner.VideoJob(
            second_video,
            output_root / "France/Example Speaker/002_France_Example_Speaker_20260102.csv",
            "France/Example Speaker/002_France_Example_Speaker_20260102",
            output_root,
        ),
    ]
    calls = 0
    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(runner, "require_executable", lambda name: name)
    monkeypatch.setattr(
        runner, "validate_runtime_configuration", lambda *_args: ["Positiv"]
    )

    def fake_run(command, _home, _timeout):
        nonlocal calls
        calls += 1
        input_video = Path(command[command.index("--input") + 1])
        partial = Path(command[command.index("--output") + 1])
        write_valid_csv(partial, input_video)
        return "ROCKSTEADY_ADAPTER_OK rows=1 columns=6"

    monkeypatch.setattr(runner, "run_java", fake_run)
    settings = runner.Settings()
    manifest = output_root / "_manifests/rocksteady_run_manifest.json"

    _, first_failures = runner.process_jobs_as_snapshot(
        jobs,
        output_root=output_root,
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=manifest,
        run_id="full-1",
    )
    _, subset_failures = runner.process_jobs_as_snapshot(
        jobs[:1],
        output_root=output_root,
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=manifest,
        run_id="subset",
    )
    subset_csvs = [
        path.relative_to(output_root).as_posix()
        for path in output_root.rglob("*.csv")
    ]
    final_records, final_failures = runner.process_jobs_as_snapshot(
        jobs,
        output_root=output_root,
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=manifest,
        run_id="full-2",
    )

    assert (first_failures, subset_failures, final_failures) == (0, 0, 0)
    assert len(subset_csvs) == 1
    assert subset_csvs[0].endswith("001_France_Example_Speaker_20260101.csv")
    assert [record["resume_source"] for record in final_records] == [
        "current-output",
        "content-addressed-cache",
    ]
    assert calls == 2
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["run_id"] == "full-2"
    assert payload["summary"] == {"total": 2, "completed": 0, "skipped": 2, "failed": 0}
    adapter_source = (
        runner.ADAPTER_ROOT
        / "java/ie/tcd/multimodal/rocksteady/RockSteadyCli.java"
    )
    assert payload["adapter_source_sha256"] == runner.sha256_file(adapter_source)
    assert runner.validate_rocksteady_batch_manifest(
        manifest,
        expected_adapter_source_sha256=runner.sha256_file(adapter_source),
    ) == payload


def test_completed_job_can_resume_from_legacy_adjacent_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    application_jar = rocksteady_home / runner.APPLICATION_JAR_NAME
    with zipfile.ZipFile(application_jar, "w") as archive:
        archive.writestr(runner.DEFAULT_DICTIONARY, b"dictionary")
    video = make_video(tmp_path / "input", count=1)
    output = tmp_path / "output" / "France" / "Example Speaker" / "example.csv"
    job = runner.VideoJob(video, output, "France/Example Speaker/example")
    calls = 0

    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(
        runner, "validate_runtime_configuration", lambda *_args: ["Positiv"]
    )

    def fake_run(command, _home, _timeout):
        nonlocal calls
        calls += 1
        partial = Path(command[command.index("--output") + 1])
        write_valid_csv(partial, video)
        return "ROCKSTEADY_ADAPTER_OK rows=1 columns=6"

    monkeypatch.setattr(runner, "run_java", fake_run)
    settings = runner.Settings()
    first, first_failures = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=None,
    )
    new_manifest = runner.manifest_path_for_job(job)
    legacy_manifest = runner.legacy_manifest_path_for_single(output)
    legacy_manifest.parent.mkdir(parents=True, exist_ok=True)
    new_manifest.replace(legacy_manifest)

    second, second_failures = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=settings,
        force=False,
        dry_run=False,
        batch_manifest_path=None,
    )

    assert (first_failures, second_failures) == (0, 0)
    assert [first[0]["status"], second[0]["status"]] == ["completed", "skipped"]
    assert calls == 1
    assert new_manifest.is_file()


def test_failed_job_removes_incomplete_csv(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    application_jar = rocksteady_home / runner.APPLICATION_JAR_NAME
    with zipfile.ZipFile(application_jar, "w") as archive:
        archive.writestr(runner.DEFAULT_DICTIONARY, b"dictionary")
    video = make_video(tmp_path / "input", count=1)
    output = tmp_path / "output" / "result.csv"
    job = runner.VideoJob(video, output, "France/Example Speaker/example")

    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(
        runner, "validate_runtime_configuration", lambda *_args: ["Positiv"]
    )

    def fake_failure(command, _home, _timeout):
        partial = Path(command[command.index("--output") + 1])
        partial.write_text("incomplete", encoding="utf-8")
        raise RuntimeError("simulated Java failure")

    monkeypatch.setattr(runner, "run_java", fake_failure)
    records, failures = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=runner.Settings(),
        force=False,
        dry_run=False,
        batch_manifest_path=None,
    )

    assert failures == 1
    assert records[0]["status"] == "failed"
    assert records[0]["error_summary"] == "simulated Java failure"
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()
    captured = capsys.readouterr()
    assert "Reason: simulated Java failure" in captured.err
    assert "Manifest:" in captured.err


def test_concise_error_extracts_java_root_cause() -> None:
    error = RuntimeError(
        "log noise\nException in thread \"main\" java.lang.IllegalArgumentException: "
        "Dictionary category not found: Econ@\n\tat example.Main.main(Main.java:1)"
    )
    assert runner.concise_error(error) == "Dictionary category not found: Econ@"


def test_dry_run_performs_runtime_validation_and_reports_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    (rocksteady_home / runner.APPLICATION_JAR_NAME).write_bytes(b"jar")
    video = make_video(tmp_path / "input", count=1)
    output = tmp_path / "output" / "France" / "Example Speaker" / "example.csv"
    job = runner.VideoJob(video, output, "France/Example Speaker/example")
    validations = 0

    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")

    def fake_validation(*_args):
        nonlocal validations
        validations += 1
        return ["Positiv", "Strong"]

    monkeypatch.setattr(runner, "validate_runtime_configuration", fake_validation)
    records, failures = runner.process_jobs(
        [job],
        rocksteady_home=rocksteady_home,
        settings=runner.Settings(categories=("Positiv", "Strong")),
        force=False,
        dry_run=True,
        batch_manifest_path=None,
    )

    assert failures == 0
    assert validations == 1
    assert records[0]["categories"] == ["Positiv", "Strong"]
    assert str(output) in capsys.readouterr().out


def test_real_java_adapter_smoke_when_runtime_is_available(tmp_path: Path) -> None:
    jar = runner.DEFAULT_ROCKSTEADY_HOME / runner.APPLICATION_JAR_NAME
    if not jar.is_file() or shutil.which("java") is None or shutil.which("javac") is None:
        pytest.skip("Local ignored RockSteady runtime/JDK is not installed")
    video = make_video(tmp_path / "input", count=1, text="a good and strong future")
    output = tmp_path / "result.csv"
    records, failures = runner.process_jobs(
        [runner.VideoJob(video, output, "France/Example Speaker/example")],
        rocksteady_home=runner.DEFAULT_ROCKSTEADY_HOME,
        settings=runner.Settings(categories=("Positiv", "Strong")),
        force=True,
        dry_run=False,
        batch_manifest_path=None,
    )
    assert failures == 0, records
    validation = runner.validate_csv(output, video, "total")
    assert validation["rows"] == 1


def test_adapter_build_is_atomic_content_bound_and_compile_locked(
    tmp_path: Path, monkeypatch
) -> None:
    adapter_root = tmp_path / "adapter"
    source = (
        adapter_root
        / "java/ie/tcd/multimodal/rocksteady/RockSteadyCli.java"
    )
    source.parent.mkdir(parents=True)
    source.write_text("class RockSteadyCli {}", encoding="utf-8")
    application_jar = tmp_path / "application.jar"
    application_jar.write_bytes(b"jar")
    calls = 0

    def fake_compile(command, *, check, **_kwargs):
        nonlocal calls
        assert check is True
        calls += 1
        destination = Path(command[command.index("-d") + 1])
        target = destination / "ie/tcd/multimodal/rocksteady/RockSteadyCli.class"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"bytecode")

    monkeypatch.setattr(runner, "ADAPTER_ROOT", adapter_root)
    monkeypatch.setattr(runner, "require_executable", lambda _name: "javac")
    monkeypatch.setattr(runner.subprocess, "run", fake_compile)

    classes = runner.build_adapter(application_jar)
    assert runner.build_adapter(application_jar) == classes
    assert calls == 1
    build_identity = json.loads(
        (classes / ".adapter_build_manifest.json").read_text(encoding="utf-8")
    )
    assert build_identity["source_sha256"] == runner.sha256_file(source)
    assert build_identity["application_jar_sha256"] == runner.sha256_file(application_jar)

    lock = adapter_root / "build/.classes.compile.lock"
    from processing.io_utils import exclusive_process_lock

    with exclusive_process_lock(lock, purpose="test adapter compiler"):
        with pytest.raises(RuntimeError, match="Another process"):
            runner.build_adapter(application_jar)


def test_failed_snapshot_manifest_survives_outside_discarded_staging(
    tmp_path: Path, monkeypatch
) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    application_jar = rocksteady_home / runner.APPLICATION_JAR_NAME
    with zipfile.ZipFile(application_jar, "w") as archive:
        archive.writestr(runner.DEFAULT_DICTIONARY, b"dictionary")
    video = make_video(tmp_path / "input", count=1)
    output_root = tmp_path / "results"
    output_root.mkdir()
    (output_root / runner.OWNER_FILE).write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "owner": "multimodal-emotion-analysis-text",
                "stage": runner.ROCKSTEADY_STAGE,
            }
        ),
        encoding="utf-8",
    )
    sentinel = output_root / "previous.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    job = runner.VideoJob(
        video,
        output_root / "France/Example Speaker/001_France_Example_Speaker_20260101.csv",
        "France/Example Speaker/001_France_Example_Speaker_20260101",
        output_root,
    )
    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(runner, "require_executable", lambda name: name)
    monkeypatch.setattr(runner, "validate_runtime_configuration", lambda *_args: ["Positiv"])
    monkeypatch.setattr(
        runner,
        "run_java",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("simulated failure")),
    )

    records, failures = runner.process_jobs_as_snapshot(
        [job],
        output_root=output_root,
        rocksteady_home=rocksteady_home,
        settings=runner.Settings(),
        force=True,
        dry_run=False,
        batch_manifest_path=output_root / "_manifests/rocksteady_run_manifest.json",
        run_id="failed-test",
    )

    assert failures == 1
    assert records[0]["status"] == "failed"
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    history_files = list(
        runner.failed_run_history_root(output_root).glob("*.json")
    )
    history_files = [
        path for path in history_files if path.name != ".rocksteady_run_history_owner.json"
    ]
    assert len(history_files) == 1
    history = json.loads(history_files[0].read_text(encoding="utf-8"))
    assert history["status"] == "failed"
    assert history["snapshot_publication"]["visible_output_preserved"] is True
    assert not list(tmp_path.glob(".results_staging_*"))


def test_keyboard_interrupt_cleans_snapshot_and_archives_interrupted_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    rocksteady_home = tmp_path / "RockSteady"
    rocksteady_home.mkdir()
    application_jar = rocksteady_home / runner.APPLICATION_JAR_NAME
    with zipfile.ZipFile(application_jar, "w") as archive:
        archive.writestr(runner.DEFAULT_DICTIONARY, b"dictionary")
    video = make_video(tmp_path / "input", count=1)
    output_root = tmp_path / "results"
    job = runner.VideoJob(
        video,
        output_root / "France/Example Speaker/001_France_Example_Speaker_20260101.csv",
        "France/Example Speaker/001_France_Example_Speaker_20260101",
        output_root,
    )
    monkeypatch.setattr(runner, "build_adapter", lambda _jar: tmp_path / "classes")
    monkeypatch.setattr(runner, "require_executable", lambda name: name)
    monkeypatch.setattr(runner, "validate_runtime_configuration", lambda *_args: ["Positiv"])

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_java", interrupt)
    with pytest.raises(KeyboardInterrupt):
        runner.process_jobs_as_snapshot(
            [job],
            output_root=output_root,
            rocksteady_home=rocksteady_home,
            settings=runner.Settings(),
            force=True,
            dry_run=False,
            batch_manifest_path=output_root / "_manifests/rocksteady_run_manifest.json",
            run_id="interrupt-test",
        )

    history_files = [
        path
        for path in runner.failed_run_history_root(output_root).glob("*.json")
        if path.name != ".rocksteady_run_history_owner.json"
    ]
    assert len(history_files) == 1
    history = json.loads(history_files[0].read_text(encoding="utf-8"))
    assert history["status"] == "interrupted"
    assert history["summary"]["interrupted"] == 1
    assert not list(tmp_path.glob(".results_staging_*"))
    assert not (tmp_path / ".results.rocksteady.lock").exists()
