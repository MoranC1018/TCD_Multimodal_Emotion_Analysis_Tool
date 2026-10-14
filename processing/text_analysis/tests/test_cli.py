from __future__ import annotations

import json

from processing.text_analysis import __main__ as text_cli


def test_check_cli_is_json_and_needs_no_input(monkeypatch, capsys) -> None:
    captured = {}

    def fake_readiness(config):
        captured["config"] = config
        return {"status": "ready", "category_count": 45, "categories": ["Active"]}

    monkeypatch.setattr(text_cli, "check_text_processing_readiness", fake_readiness)

    assert text_cli.main(["--check"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "text-processing-readiness"
    assert payload["status"] == "ready"
    assert captured["config"].input_path == "Videos"


def test_check_cli_uses_exact_config_and_reports_failure_without_traceback(
    tmp_path, monkeypatch, capsys
) -> None:
    config_path = tmp_path / "text.json"
    config_path.write_text(
        json.dumps(
            {
                "dictionaries": ["file:custom.xml"],
                "categories": [
                    "Active", "Negativ", "Passive", "Research Theme", "Positiv", "Strong", "Weak"
                ],
            }
        ),
        encoding="utf-8",
    )

    def fail(config):
        assert config.dictionaries == ("file:custom.xml",)
        assert config.categories[-1] == "Weak"
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(text_cli, "check_text_processing_readiness", fail)

    assert text_cli.main(["--check", "--config", str(config_path)]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "not_ready"
    assert payload["error"] == "runtime unavailable"
    assert "Traceback" not in captured.out + captured.err


def test_normal_cli_failure_is_concise_unless_debug(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        text_cli,
        "run_text_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad input")),
    )

    assert text_cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "ERROR: ValueError: bad input"
    assert "Traceback" not in captured.err


def test_complete_cli_forwards_custom_text_options_and_run_id(monkeypatch) -> None:
    captured = {}

    def fake_run(config, **kwargs):
        captured["config"] = config
        captured["kwargs"] = kwargs
        return type(
            "Result",
            (),
            {
                "completed_stages": ("transcribe",),
                "selected_output": None,
                "extra_output": None,
                "manifest": "manifest.json",
            },
        )()

    monkeypatch.setattr(text_cli, "run_text_pipeline", fake_run)
    assert text_cli.main(
        [
            "Videos",
            "--dictionary",
            "file:custom.xml",
            "--category",
            "Risk",
            "--dictionary-combination",
            "override",
            "--run-id",
            "ui-run-7",
            "--to-stage",
            "transcribe",
        ]
    ) == 0

    assert captured["config"].dictionaries == ("file:custom.xml",)
    assert captured["config"].categories == ("Risk",)
    assert captured["config"].dictionary_combination == "override"
    assert captured["kwargs"]["run_id"] == "ui-run-7"


def test_cli_returns_standard_interrupt_code(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        text_cli,
        "run_text_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    assert text_cli.main(["Videos", "--to-stage", "transcribe"]) == 130
    assert "CANCELLED" in capsys.readouterr().err


def test_ui_output_root_maps_every_stage_and_language_variant(tmp_path, monkeypatch) -> None:
    captured = {}

    def fake_run(config, **_kwargs):
        captured["config"] = config
        return type(
            "Result",
            (),
            {
                "completed_stages": ("transcribe",),
                "selected_output": None,
                "extra_output": None,
                "manifest": "manifest.json",
            },
        )()

    monkeypatch.setattr(text_cli, "run_text_pipeline", fake_run)
    output = tmp_path / "text workspace"
    assert text_cli.main(
        [
            "Videos",
            "--output-root",
            str(output),
            "--default-language-variant",
            "original",
            "--to-stage",
            "transcribe",
        ]
    ) == 0

    config = captured["config"]
    resolved = output.resolve()
    assert config.whisper_root == str(resolved / "transcripts")
    assert config.selected_whisper_root == str(resolved / "selected_transcripts")
    assert config.prepared_root == str(resolved / "prepared_segments")
    assert config.selected_csv_root == str(resolved / "rocksteady" / "core")
    assert config.extra_csv_root == str(resolved / "rocksteady" / "all")
    assert config.postprocessing_root == str(resolved / "analysis")
    assert config.default_language_variant == "original"
