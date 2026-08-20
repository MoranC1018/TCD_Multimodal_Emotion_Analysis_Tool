from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.workflow import _archive_fixed_outputs


def test_prior_workflow_manifest_rejects_oversized_control_json(tmp_path: Path) -> None:
    (tmp_path / "combined_analysis_manifest.json").write_text(
        json.dumps({"padding": "x" * (1024 * 1024)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="workflow manifest JSON exceeds"):
        _archive_fixed_outputs(tmp_path, "2026-08-20T00:00:00Z")


def test_prior_workflow_manifest_rejects_excessive_semantic_items(tmp_path: Path) -> None:
    (tmp_path / "combined_analysis_manifest.json").write_text(
        json.dumps({"items": [None] * 50_001}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="more than 50000 items"):
        _archive_fixed_outputs(tmp_path, "2026-08-20T00:00:00Z")
