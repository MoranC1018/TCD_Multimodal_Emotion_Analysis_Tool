import csv
from pathlib import Path

import pytest

from processing.io_utils import exclusive_process_lock
from processing.text_analysis.derived_views import derive_category_view


def test_derived_view_filters_without_recalculating_counts(tmp_path: Path) -> None:
    source = tmp_path / "full" / "UK" / "Speaker" / "001_UK_Speaker_20250101.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "Title,Date of First Article,Articles,Terms,URL,Positiv,Strong,Risk\n"
        "segment_000001,,1,4,,2,1,3\n",
        encoding="utf-8",
    )
    count = derive_category_view(tmp_path / "full", tmp_path / "core", ("Positiv", "Strong"))
    with (tmp_path / "core" / "UK" / "Speaker" / source.name).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert count == 1
    assert rows == [{
        "Title": "segment_000001", "Date of First Article": "", "Articles": "1",
        "Terms": "4", "URL": "", "Positiv": "2", "Strong": "1",
    }]


def test_derived_view_lock_blocks_a_second_writer(tmp_path: Path) -> None:
    target = tmp_path / "derived"
    lock = target.parent / f".{target.name}.derived-view.lock"
    with exclusive_process_lock(lock, purpose="test derived writer"):
        with pytest.raises(RuntimeError, match="Another process"):
            derive_category_view(tmp_path / "source", target, ("Positiv",))
