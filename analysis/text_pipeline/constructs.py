"""Transcript construct views for later multimodal alignment.

The source values remain RockSteady word-frequency proportions.  The signed
balances produced here are lexical proxies, not calibrated face/audio emotion
scores.  Keeping this transformation in one small module makes the contract
easy to inspect and lets existing postprocessing outputs be upgraded without
rerunning RockSteady.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from spreadsheet_safety import SpreadsheetSafeWriter


ALIGNMENT_DIRECTORY = "multimodal"
ALIGNMENT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ConstructDefinition:
    key: str
    label: str
    indicators: tuple[str, ...]
    score_field: str
    formula: str
    score_range: str
    interpretation: str


CONSTRUCTS: tuple[ConstructDefinition, ...] = (
    ConstructDefinition(
        "positive_sentiment",
        "Positive Sentiment",
        ("positive",),
        "Positive Sentiment",
        "Positive matches / RockSteady Terms",
        "0 to 1",
        "Higher values mean a larger share of RockSteady Terms matched positive words.",
    ),
    ConstructDefinition(
        "negative_sentiment",
        "Negative Sentiment",
        ("negative",),
        "Negative Sentiment",
        "Negative matches / RockSteady Terms",
        "0 to 1",
        "Higher values mean a larger share of RockSteady Terms matched negative words.",
    ),
    ConstructDefinition(
        "arousal_activation",
        "Arousal / Activation",
        ("active", "passive"),
        "Arousal / Activation",
        "(Active - Passive) / (Active + Passive), using proportions",
        "-1 to 1",
        "Positive values favour active over passive wording; this is not physiological arousal.",
    ),
    ConstructDefinition(
        "dominance_power",
        "Dominance / Power",
        ("strong", "weak", "power"),
        "Dominance / Power",
        "(Strong + Power - Weak) / (Strong + Power + Weak), using proportions",
        "-1 to 1",
        "Positive values favour strong/power over weak wording; categories may overlap.",
    ),
    ConstructDefinition(
        "affiliation_social",
        "Affiliation / Social orientation",
        ("affiliation", "hostile"),
        "Affiliation / Social orientation",
        "(Affiliation - Hostile) / (Affiliation + Hostile), using proportions",
        "-1 to 1",
        "Positive values favour affiliation over hostile wording.",
    ),
)


COMPONENTS = (
    "positive",
    "negative",
    "active",
    "passive",
    "strong",
    "weak",
    "power",
    "affiliation",
    "hostile",
)


IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "segment": (
        "country",
        "speaker",
        "speaker_id",
        "video",
        "source_id",
        "segment_id",
        "start_sec",
        "end_sec",
        "duration_sec",
        "segment_text",
        "whisper_language",
        "text_language",
        "rocksteady_row_available",
        "rocksteady_terms",
        "valid_segment",
    ),
    "video": (
        "country",
        "speaker",
        "speaker_id",
        "video",
        "source_id",
        "video_order",
        "date",
        "person",
        "segments_with_terms",
        "rocksteady_terms_total",
        "whisper_segments",
        "whisper_language",
        "text_language",
    ),
    "speaker": (
        "country",
        "speaker",
        "speaker_id",
        "videos_count",
        "segments_with_terms",
        "rocksteady_terms_total",
    ),
}

DISPLAY_SCORE_FIELDS = (
    ("Positive Sentiment", "positive_sentiment_score"),
    ("Negative Sentiment", "negative_sentiment_score"),
    ("Arousal / Activation", "activation_balance_score"),
    ("Dominance / Power", "dominance_power_balance_score"),
    ("Affiliation / Social orientation", "affiliation_social_balance_score"),
)

DISPLAY_COLORS = ("#16a34a", "#dc2626", "#2563eb", "#7e22ce", "#0f766e")

READABLE_IDENTITY_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
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
    ),
    "video": (
        ("Country", "country"),
        ("Speaker", "speaker"),
        ("Speaker ID", "speaker_id"),
        ("Video", "video"),
        ("Source ID", "source_id"),
        ("Date", "date"),
        ("Valid segments", "segments_with_terms"),
        ("RockSteady terms", "rocksteady_terms_total"),
    ),
    "speaker": (
        ("Country", "country"),
        ("Speaker", "speaker"),
        ("Speaker ID", "speaker_id"),
        ("Videos", "videos_count"),
        ("Valid segments", "segments_with_terms"),
        ("RockSteady terms", "rocksteady_terms_total"),
    ),
}


def write_construct_alignment(
    variant_root: str | Path,
    *,
    variant: str,
    output_root: str | Path | None = None,
) -> dict[str, object]:
    """Create the readable shared multimodal view from one Text variant."""

    root = Path(variant_root)
    normalized_variant = str(variant).strip().casefold()
    if not normalized_variant:
        raise ValueError("Text output variant is required for construct alignment")

    sources = {
        "segment": sorted((root / "segment_level").rglob("*.csv")),
        "video": [root / "video_level_summary.csv"],
        "speaker": [root / "speaker_level_summary.csv"],
    }
    if not sources["segment"]:
        raise ValueError(f"No segment-level CSV files found under {root}")
    for level in ("video", "speaker"):
        if not sources[level][0].is_file():
            raise FileNotFoundError(f"Missing {level}-level summary: {sources[level][0]}")

    output = (
        Path(output_root)
        if output_root is not None
        else root.parent / ALIGNMENT_DIRECTORY
    )
    if output.exists():
        import shutil

        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    _write_mapping(output / "construct_mapping.csv")

    counts: dict[str, int] = {}
    segment_count = 0
    for path in sources["segment"]:
        rows = [
            _readable_row(construct_row(row, level="segment", variant=normalized_variant), "segment")
            for row in _read_rows(path)
        ]
        relative = path.relative_to(root / "segment_level")
        filename = relative.name.replace("_segments_enriched.csv", "_constructs.csv")
        destination = output / "segment_level" / relative.parent / filename
        _write_rows(destination, rows, _readable_fields("segment"))
        segment_count += len(rows)
    counts["segment"] = segment_count

    readable_rows: dict[str, list[dict[str, object]]] = {}
    for level in ("video", "speaker"):
        paths = sources[level]
        rows: list[dict[str, object]] = []
        for path in paths:
            rows.extend(
                _readable_row(
                    construct_row(row, level=level, variant=normalized_variant), level
                )
                for row in _read_rows(path)
            )
        _write_rows(
            output / f"{level}_level_summary.csv",
            rows,
            _readable_fields(level),
        )
        counts[level] = len(rows)
        readable_rows[level] = rows

    graph_count = _write_construct_graphs(
        output,
        readable_rows["video"],
        readable_rows["speaker"],
    )
    (output / "README.md").write_text(_readme_text(), encoding="utf-8")

    contract = {
        "schema_version": ALIGNMENT_SCHEMA_VERSION,
        "kind": "transcript-multimodal-alignment",
        "modality": "transcript",
        "variant": normalized_variant,
        "measurement_boundary": (
            "RockSteady lexical proportions and derived balances are text descriptors, "
            "not calibrated facial/audio emotion intensities or direct psychological measures."
        ),
        "join_keys": {
            "segment": ["Country", "Speaker ID", "Video", "Segment", "Start (seconds)", "End (seconds)"],
            "video": ["Country", "Speaker ID", "Video"],
            "speaker": ["Country", "Speaker ID"],
        },
        "constructs": [
            {
                "key": item.key,
                "label": item.label,
                "indicators": list(item.indicators),
                "score_field": item.score_field,
                "formula": item.formula,
                "score_range": item.score_range,
                "interpretation": item.interpretation,
            }
            for item in CONSTRUCTS
        ],
        "rows": counts,
        "graphs": graph_count,
        "artifacts": {
            "mapping": "construct_mapping.csv",
            "segment": (
                "segment_level/<Speaker>/<Video>_constructs.csv "
                "(legacy: <Country>/<Speaker>/<Video>_constructs.csv)"
            ),
            "video": "video_level_summary.csv",
            "speaker": "speaker_level_summary.csv",
            "graphs": "graphs/",
            "readme": "README.md",
        },
    }
    (output / "alignment_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return contract


def construct_row(
    source: Mapping[str, object],
    *,
    level: str,
    variant: str,
) -> dict[str, object]:
    """Convert one existing segment/video/speaker row into the stable view."""

    if level not in IDENTITY_FIELDS:
        raise ValueError(f"Unsupported construct level: {level}")
    row: dict[str, object] = {
        field: source.get(field, "") for field in IDENTITY_FIELDS[level]
    }
    row.update(
        {
            "modality": "transcript",
            "source_variant": variant,
            "construct_schema_version": ALIGNMENT_SCHEMA_VERSION,
        }
    )

    proportions: dict[str, float | None] = {}
    for component in COMPONENTS:
        available = _component_available(source, component, level)
        value = _number(source.get(f"{component}_proportion")) if available else None
        proportions[component] = value
        row[f"{component}_available"] = int(available)
        row[f"{component}_proportion"] = value if value is not None else ""

    _set_direct_score(row, "positive_sentiment", proportions["positive"])
    _set_direct_score(row, "negative_sentiment", proportions["negative"])
    _set_balance_score(
        row,
        "activation",
        proportions,
        positive=("active",),
        negative=("passive",),
    )
    _set_balance_score(
        row,
        "dominance_power",
        proportions,
        positive=("strong", "power"),
        negative=("weak",),
    )
    _set_balance_score(
        row,
        "affiliation_social",
        proportions,
        positive=("affiliation",),
        negative=("hostile",),
    )
    return row


def _set_direct_score(
    row: dict[str, object], key: str, value: float | None
) -> None:
    row[f"{key}_available"] = int(value is not None)
    row[f"{key}_evidence"] = int(value is not None and value > 0)
    row[f"{key}_score"] = value if value is not None else ""


def _set_balance_score(
    row: dict[str, object],
    key: str,
    values: Mapping[str, float | None],
    *,
    positive: Sequence[str],
    negative: Sequence[str],
) -> None:
    required = (*positive, *negative)
    available = all(values[name] is not None for name in required)
    row[f"{key}_available"] = int(available)
    if not available:
        row[f"{key}_evidence"] = 0
        row[f"{key}_balance_score"] = ""
        return
    positive_total = sum(float(values[name]) for name in positive if values[name] is not None)
    negative_total = sum(float(values[name]) for name in negative if values[name] is not None)
    denominator = positive_total + negative_total
    row[f"{key}_evidence"] = int(denominator > 0)
    row[f"{key}_balance_score"] = (
        (positive_total - negative_total) / denominator if denominator > 0 else ""
    )


def _component_available(
    source: Mapping[str, object], component: str, level: str
) -> bool:
    availability_field = (
        f"{component}_complete" if level == "speaker" else f"{component}_available"
    )
    return _truthy(source.get(availability_field))


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().casefold() in {"1", "true", "yes"}


def _number(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _readable_row(row: Mapping[str, object], level: str) -> dict[str, object]:
    result = {
        display: row.get(source, "")
        for display, source in READABLE_IDENTITY_FIELDS[level]
    }
    for display, source in DISPLAY_SCORE_FIELDS:
        result[display] = row.get(source, "")
    return result


def _readable_fields(level: str) -> list[str]:
    return [
        *(display for display, _source in READABLE_IDENTITY_FIELDS[level]),
        *(display for display, _source in DISPLAY_SCORE_FIELDS),
    ]


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
            writer.writerow({key: _format_cell(row.get(key, "")) for key in fieldnames})


def _format_cell(value: object) -> object:
    if isinstance(value, float):
        rendered = f"{value:.6f}".rstrip("0").rstrip(".")
        return "0" if rendered in {"-0", ""} else rendered
    return "" if value is None else value


def _write_mapping(path: Path) -> None:
    rows = [
        {
            "Psychological construct": item.label,
            "Modality": "Transcript",
            "Transcript indicators": "; ".join(
                indicator.title() for indicator in item.indicators
            ),
            "Score range": item.score_range,
            "How it is calculated": item.formula,
            "How to read it": item.interpretation,
        }
        for item in CONSTRUCTS
    ]
    _write_rows(path, rows, tuple(rows[0]))


def _write_construct_graphs(
    output: Path,
    video_rows: Sequence[Mapping[str, object]],
    speaker_rows: Sequence[Mapping[str, object]],
) -> int:
    from analysis.text_pipeline.postprocess import render_valence_bar_svg, write_svg

    count = 0
    labels = [display for display, _source in DISPLAY_SCORE_FIELDS]
    for row in video_rows:
        values = [_number(row.get(label)) for label in labels]
        path = (
            output
            / "graphs"
            / "videos"
            / str(row.get("Country", "Unknown"))
            / str(row.get("Speaker", "Unknown"))
            / f"{row.get('Video', 'video')}_constructs.svg"
        )
        write_svg(
            path,
            render_valence_bar_svg(
                title=f"{row.get('Video', 'Video')} Transcript constructs",
                subtitle="Readable lexical proxies; blank means the construct is unavailable or has no evidence",
                x_labels=labels,
                values=values,
                width=1450,
                y_label="construct score (-1 to 1)",
                colors=DISPLAY_COLORS,
            ),
        )
        count += 1

    video_groups: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for row in video_rows:
        key = (str(row.get("Country", "Unknown")), str(row.get("Speaker", "Unknown")))
        video_groups.setdefault(key, []).append(row)
    for (country, speaker), rows in sorted(video_groups.items()):
        ordered = sorted(rows, key=lambda row: str(row.get("Video", "")))
        for index, (label, _source) in enumerate(DISPLAY_SCORE_FIELDS, start=1):
            write_svg(
                output / "graphs" / "speakers" / country / speaker / f"{index:02d}_{_safe_name(label)}.svg",
                render_valence_bar_svg(
                    title=f"{speaker}: {label}",
                    subtitle="One Transcript construct score per video",
                    x_labels=[str(row.get("Video", "")) for row in ordered],
                    values=[_number(row.get(label)) for row in ordered],
                    width=max(1200, 190 * len(ordered)),
                    y_label="construct score (-1 to 1)",
                    colors=[DISPLAY_COLORS[index - 1]] * len(ordered),
                ),
            )
            count += 1

    country_groups: dict[str, list[Mapping[str, object]]] = {}
    for row in speaker_rows:
        country_groups.setdefault(str(row.get("Country", "Unknown")), []).append(row)
    for country, rows in sorted(country_groups.items()):
        ordered = sorted(rows, key=lambda row: str(row.get("Speaker", "")))
        for index, (label, _source) in enumerate(DISPLAY_SCORE_FIELDS, start=1):
            write_svg(
                output / "graphs" / "summary" / country / f"{index:02d}_{_safe_name(label)}.svg",
                render_valence_bar_svg(
                    title=f"{country}: {label}",
                    subtitle="One Transcript construct score per speaker",
                    x_labels=[str(row.get("Speaker", "")) for row in ordered],
                    values=[_number(row.get(label)) for row in ordered],
                    width=max(1200, 190 * len(ordered)),
                    y_label="construct score (-1 to 1)",
                    colors=[DISPLAY_COLORS[index - 1]] * len(ordered),
                ),
            )
            count += 1
    return count


def _safe_name(label: str) -> str:
    return "_".join(part for part in label.replace("/", " ").split() if part)


def _readme_text() -> str:
    return """# Transcript 多模态输出 / Multimodal output

先打开 `video_level_summary.csv`：每个视频一行，五个指标名称与统一心理构念表完全一致。

- `segment_level/`：每个视频一张带时间戳的表，用于时间对齐。
- `video_level_summary.csv`：每个视频一行。
- `speaker_level_summary.csv`：每个 speaker 一行。
- `graphs/`：同样五个构念的 SVG 图片。
- `construct_mapping.csv`：指标来源、范围、公式和阅读方法。
- `alignment_contract.json`：供程序使用的对齐键和契约。

Positive/Negative Sentiment 的范围是 0–1，其余三个方向分数是 -1–1。空白表示
所需词典类别不存在，或者没有相关词语证据。这些值描述语言使用，不是已经与
Facial 或 Audio 校准过的情绪强度。

## English

Start with `video_level_summary.csv`. It has one row per video and five columns
named exactly like the shared psychological-construct table.

- `segment_level/`: one timestamped CSV per video for temporal alignment.
- `video_level_summary.csv`: one row per video.
- `speaker_level_summary.csv`: one row per speaker.
- `graphs/`: the same constructs shown as readable SVG charts.
- `construct_mapping.csv`: plain-language mapping and formulas.
- `alignment_contract.json`: machine-readable join keys and provenance boundary.

Positive and Negative Sentiment range from 0 to 1. The other three balances range
from -1 to 1. A blank cell means the required dictionary category was missing or
there was no relevant word evidence. These values describe language use; they
are not calibrated Facial or Audio emotion measurements.
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build transcript construct tables from an existing Text postoutput variant."
    )
    parser.add_argument("variant_root", type=Path)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    contract = write_construct_alignment(
        args.variant_root,
        variant=args.variant,
        output_root=args.output_root,
    )
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
