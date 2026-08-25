"""Human-readable views of the complete Text postprocessing tables.

The original CSVs remain the machine/audit contract.  This module produces a
small reading layer with plain headers and percentages, without changing any
underlying calculation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from pathlib import Path
from typing import Mapping, Sequence

from analysis.text_pipeline.contracts import CATEGORY_CATALOG
from spreadsheet_safety import SpreadsheetSafeWriter


READABLE_DIRECTORY = "readable"

DISPLAY_NAMES = {category.key: category.display for category in CATEGORY_CATALOG}
IDENTITY_HEADERS: dict[str, tuple[tuple[str, str], ...]] = {
    "video": (
        ("Country", "country"),
        ("Speaker", "speaker"),
        ("Speaker ID", "speaker_id"),
        ("Video", "video"),
        ("Source ID", "source_id"),
        ("Date", "date"),
        ("Valid segments", "segments_with_terms"),
        ("RockSteady terms", "rocksteady_terms_total"),
        ("Whisper segments", "whisper_segments"),
        ("Missing RockSteady segments", "rocksteady_missing_segments"),
    ),
    "speaker": (
        ("Country", "country"),
        ("Speaker", "speaker"),
        ("Speaker ID", "speaker_id"),
        ("Videos", "videos_count"),
        ("Valid segments", "segments_with_terms"),
        ("RockSteady terms", "rocksteady_terms_total"),
    ),
    "segment": (
        ("Country", "country"),
        ("Speaker", "speaker"),
        ("Speaker ID", "speaker_id"),
        ("Video", "video"),
        ("Source ID", "source_id"),
        ("Segment", "segment_id"),
        ("Start (seconds)", "start_sec"),
        ("End (seconds)", "end_sec"),
        ("Duration (seconds)", "duration_sec"),
        ("Transcript text", "segment_text"),
        ("RockSteady terms", "rocksteady_terms"),
    ),
}


def write_readable_tables(variant_root: str | Path, *, variant: str) -> dict[str, int]:
    """Write readable summaries and per-video segment tables for one variant."""

    root = Path(variant_root)
    normalized_variant = str(variant).strip().casefold()
    output = root / READABLE_DIRECTORY
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    video_source = root / "video_level_summary.csv"
    speaker_source = root / "speaker_level_summary.csv"
    video_rows = _read_rows(video_source)
    speaker_rows = _read_rows(speaker_source)
    if not video_rows or not speaker_rows:
        raise ValueError(f"Text summaries are empty under {root}")
    category_keys = _category_keys(tuple(video_rows[0]), video_rows)

    readable_videos = [
        _summary_row(row, level="video", category_keys=category_keys)
        for row in video_rows
    ]
    readable_speakers = [
        _summary_row(row, level="speaker", category_keys=category_keys)
        for row in speaker_rows
    ]
    _write_rows(
        output / "video_level_summary.csv",
        readable_videos,
        _summary_fields("video", category_keys),
    )
    _write_rows(
        output / "speaker_level_summary.csv",
        readable_speakers,
        _summary_fields("speaker", category_keys),
    )
    _write_category_guide(output / "category_guide.csv", category_keys)

    segment_files = sorted((root / "segment_level").rglob("*.csv"))
    segment_rows = 0
    for path in segment_files:
        rows = [
            _segment_row(row, category_keys=category_keys)
            for row in _read_rows(path)
        ]
        relative = path.relative_to(root / "segment_level")
        filename = relative.name.replace("_segments_enriched.csv", "_segments.csv")
        _write_rows(
            output / "segment_level" / relative.parent / filename,
            rows,
            _segment_fields(category_keys),
        )
        segment_rows += len(rows)

    graph_count = _write_readable_graphs(
        output,
        video_rows,
        speaker_rows,
        category_keys,
        variant=normalized_variant,
    )

    (output / "README.md").write_text(
        _readme(normalized_variant, len(video_rows), len(speaker_rows), segment_rows),
        encoding="utf-8",
    )
    return {
        "videos": len(video_rows),
        "speakers": len(speaker_rows),
        "segments": segment_rows,
        "categories": len(category_keys),
        "graphs": graph_count,
    }


def _summary_row(
    source: Mapping[str, str], *, level: str, category_keys: Sequence[str]
) -> dict[str, object]:
    row: dict[str, object] = {
        display: source.get(field, "") for display, field in IDENTITY_HEADERS[level]
    }
    for key in category_keys:
        row[f"{_display(key)} (% of terms)"] = _as_percent(
            source.get(f"{key}_proportion", "")
        )
    row["Text Valence (-1 to 1)"] = source.get("valence_score", "")
    return row


def _segment_row(
    source: Mapping[str, str], *, category_keys: Sequence[str]
) -> dict[str, object]:
    row: dict[str, object] = {
        display: source.get(field, "") for display, field in IDENTITY_HEADERS["segment"]
    }
    for key in category_keys:
        row[f"{_display(key)} count"] = source.get(f"{key}_count", "")
        row[f"{_display(key)} (% of terms)"] = _as_percent(
            source.get(f"{key}_proportion", "")
        )
    row["Text Valence (-1 to 1)"] = source.get("valence_score", "")
    return row


def _category_keys(
    headers: Sequence[str], rows: Sequence[Mapping[str, str]]
) -> tuple[str, ...]:
    keys: list[str] = []
    for header in headers:
        match = re.fullmatch(r"([a-z0-9_]+)_proportion", header)
        if match and match.group(1) not in keys:
            key = match.group(1)
            if any(str(row.get(f"{key}_available", "")).strip() == "1" for row in rows):
                keys.append(key)
    if not keys:
        raise ValueError("Text summary contains no category proportion columns")
    return tuple(keys)


def _display(key: str) -> str:
    return DISPLAY_NAMES.get(key, key.replace("_", " ").title())


def _as_percent(value: object) -> float | str:
    if value is None or str(value).strip() == "":
        return ""
    try:
        return float(value) * 100
    except (TypeError, ValueError):
        return ""


def _summary_fields(level: str, category_keys: Sequence[str]) -> list[str]:
    return [
        *(display for display, _field in IDENTITY_HEADERS[level]),
        *(_display(key) + " (% of terms)" for key in category_keys),
        "Text Valence (-1 to 1)",
    ]


def _segment_fields(category_keys: Sequence[str]) -> list[str]:
    fields = [display for display, _field in IDENTITY_HEADERS["segment"]]
    for key in category_keys:
        fields.extend((f"{_display(key)} count", f"{_display(key)} (% of terms)"))
    fields.append("Text Valence (-1 to 1)")
    return fields


def _write_category_guide(path: Path, category_keys: Sequence[str]) -> None:
    rows = [
        {
            "Category": _display(key),
            "Readable column": f"{_display(key)} (% of terms)",
            "Meaning": "RockSteady category matches divided by RockSteady Terms, shown as 0-100%.",
            "Original technical prefix": key,
        }
        for key in category_keys
    ]
    _write_rows(path, rows, tuple(rows[0]))


def _write_readable_graphs(
    output: Path,
    video_rows: Sequence[Mapping[str, str]],
    speaker_rows: Sequence[Mapping[str, str]],
    category_keys: Sequence[str],
    *,
    variant: str,
) -> int:
    """Write one uncomplicated category-percentage chart per video and speaker."""

    from analysis.text_pipeline.postprocess import render_grouped_bar_svg, write_svg

    labels = [_display(key) for key in category_keys]
    color = "#2563eb" if variant == "selected" else "#7e22ce"
    width = max(1200, 125 * len(labels))
    count = 0

    for row in video_rows:
        country = str(row.get("country", "Unknown"))
        speaker = str(row.get("speaker", "Unknown"))
        video = str(row.get("video", "video"))
        values = [
            _percent_number(row.get(f"{key}_proportion", "")) for key in category_keys
        ]
        write_svg(
            output / "graphs" / "videos" / country / speaker / f"{video}_category_percentages.svg",
            render_grouped_bar_svg(
                title=f"{video}: category percentages",
                subtitle="RockSteady category matches / RockSteady Terms",
                x_labels=labels,
                series=[("% of terms", color, values)],
                y_label="% of RockSteady Terms",
                width=width,
                height=560,
                show_value_labels=True,
                value_suffix="%",
            ),
        )
        count += 1

    for row in speaker_rows:
        country = str(row.get("country", "Unknown"))
        speaker = str(row.get("speaker", "Unknown"))
        values = [
            _percent_number(row.get(f"{key}_proportion", "")) for key in category_keys
        ]
        write_svg(
            output / "graphs" / "speakers" / country / f"{speaker}_category_percentages.svg",
            render_grouped_bar_svg(
                title=f"{speaker}: category percentages",
                subtitle="All videos combined; RockSteady category matches / RockSteady Terms",
                x_labels=labels,
                series=[("% of terms", color, values)],
                y_label="% of RockSteady Terms",
                width=width,
                height=560,
                show_value_labels=True,
                value_suffix="%",
            ),
        )
        count += 1
    return count


def _percent_number(value: object) -> float:
    converted = _as_percent(value)
    return float(converted) if converted != "" else 0.0


def _readme(variant: str, videos: int, speakers: int, segments: int) -> str:
    return f"""# {variant.title()} 可读表 / Readable tables

先打开 `video_level_summary.csv`。它每个视频一行，类别直接显示为百分比，不需要理解
`positive_proportion` 之类的内部字段名。

- `video_level_summary.csv`：{videos} 个视频。
- `speaker_level_summary.csv`：{speakers} 个 speaker。
- `segment_level/`：{segments} 个带时间戳的 segment，按 Speaker/Video 保存（旧数据可含 Country）。
- `graphs/`：{videos} 张视频图片和 {speakers} 张 speaker 图片。
- `category_guide.csv`：类别名称与计算含义。

`(% of terms)` 表示类别命中次数 / RockSteady Terms × 100。空白表示该类别不可用，
不是零。`Text Valence` 范围为 -1 到 1。

原目录中的完整 CSV 是审计和程序使用版本；这里不改变任何底层数值，只改善阅读方式。
"""


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = SpreadsheetSafeWriter(
            csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _format(row.get(field, "")) for field in fieldnames})


def _format(value: object) -> object:
    if isinstance(value, float):
        rendered = f"{value:.4f}".rstrip("0").rstrip(".")
        return "0" if rendered in {"", "-0"} else rendered
    return "" if value is None else value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build readable tables from one existing Text postoutput variant."
    )
    parser.add_argument("variant_root", type=Path)
    parser.add_argument("--variant", required=True)
    args = parser.parse_args(argv)
    summary = write_readable_tables(args.variant_root, variant=args.variant)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
