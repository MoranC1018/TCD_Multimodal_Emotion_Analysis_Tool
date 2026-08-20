"""Human-readable report rendering for RockSteady text postprocessing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from analysis.text_pipeline.contracts import Category


@dataclass(frozen=True)
class ReportCategory:
    category: Category
    available_videos: int


@dataclass(frozen=True)
class SpeakerQuickRow:
    speaker_id: str
    speaker: str
    videos: object
    valid_segments: object
    terms: object
    positive_proportion: object
    negative_proportion: object
    valence: object


@dataclass(frozen=True)
class TextReportModel:
    input_dir: Path
    output_dir: Path
    whisper_root: Path
    prepare_root: Path
    video_count: int
    speaker_count: int
    segment_count: int
    source_segment_count: int
    rocksteady_row_count: int
    matched_segment_count: int
    missing_segment_count: int
    ignored_segment_count: int
    valid_segment_count: int
    zero_term_segment_count: int
    terms_total: float
    descriptor_rows: int
    graph_count: int
    segment_sample_counts: tuple[int, ...]
    alignment_policies: tuple[str, ...]
    text_languages: tuple[str, ...]
    provenance_status: str
    alignment_mapping_statuses: tuple[str, ...]
    categories: tuple[ReportCategory, ...]
    speakers: tuple[SpeakerQuickRow, ...]


def write_report_files(output_dir: Path, model: TextReportModel) -> None:
    """Write both language reports and the concise run log from one model."""

    (output_dir / "POSTPROCESSING_REPORT.md").write_text(
        render_method_report(model, language="zh"), encoding="utf-8"
    )
    (output_dir / "POSTPROCESSING_REPORT_EN.md").write_text(
        render_method_report(model, language="en"), encoding="utf-8"
    )
    (output_dir / "run_log.txt").write_text(render_run_log(model), encoding="utf-8")


def render_speaker_quick_table(
    rows: Sequence[SpeakerQuickRow],
    *,
    language: str,
) -> list[str]:
    """Render one structurally shared seven-column speaker table."""

    if language not in {"zh", "en"}:
        raise ValueError(f"Unsupported report language: {language}")
    header = (
        "| Speaker | Videos | Valid segments | Terms | Positive Sentiment proportion | "
        "Negative Sentiment proportion | Text Valence |"
    )
    lines = [header, "|---|---:|---:|---:|---:|---:|---:|"]
    for row in sorted(rows, key=lambda item: item.speaker_id.casefold()):
        values = (
            row.speaker,
            row.videos,
            row.valid_segments,
            row.terms,
            row.positive_proportion,
            row.negative_proportion,
            row.valence,
        )
        lines.append("| " + " | ".join(_format(value) for value in values) + " |")
    return lines


def render_run_log(model: TextReportModel) -> str:
    sample_counts = ",".join(str(value) for value in model.segment_sample_counts) or "none"
    category_names = ", ".join(
        item.category.display for item in model.categories if item.available_videos
    )
    lines = [
        "RockSteady segment-level text postprocessing",
        f"Input folder: {model.input_dir}",
        f"Output folder: {model.output_dir}",
        f"Whisper JSON root: {model.whisper_root}",
        f"Prepare mapping root: {model.prepare_root}",
        f"Video CSV files: {model.video_count}",
        f"Analysis/output segment rows: {model.segment_count}",
        f"Source Whisper segments: {model.source_segment_count}",
        f"Original RockSteady CSV rows: {model.rocksteady_row_count}",
        f"Matched RockSteady segments: {model.matched_segment_count}",
        f"Missing RockSteady segments: {model.missing_segment_count}",
        f"Ignored stale/out-of-range rows: {model.ignored_segment_count}",
        f"Valid segments (Terms > 0): {model.valid_segment_count}",
        f"Excluded zero-Term segments: {model.zero_term_segment_count}",
        f"Segment alignment policy: {','.join(model.alignment_policies)}",
        f"Alignment mapping status: {','.join(model.alignment_mapping_statuses)}",
        f"Attached text language(s): {','.join(model.text_languages)}",
        f"Upstream provenance status: {model.provenance_status}",
        f"Segment timeline sample counts: {sample_counts}",
        f"Graphs: {model.graph_count}",
        "",
        "Input validation:",
        "Expected RockSteady mode: Total",
        "Validation result: passed",
        "Alignment audit: segment_alignment_audit.csv",
        "Machine-readable contract: output_manifest.json",
        "",
        "Method:",
        "RockSteady Total counts are preserved at segment level.",
        f"Categories present: {category_names or 'none'}.",
        "RockSteady Terms is the formal denominator for category proportions.",
        "Whisper word count is audit-only; segment text and timestamps are attached.",
        "Text Valence = (Positive Sentiment - Negative Sentiment) / "
        "(Positive Sentiment + Negative Sentiment).",
        "Video and speaker Text Valence are recalculated from aggregated counts.",
        "Categories may overlap and are not expected to sum to Terms or 100%.",
        "Text proportions are word-frequency descriptors, not face/audio emotion intensities.",
    ]
    return "\n".join(lines) + "\n"


def render_method_report(model: TextReportModel, *, language: str) -> str:
    if language == "zh":
        return _render_chinese_report(model)
    if language == "en":
        return _render_english_report(model)
    raise ValueError(f"Unsupported report language: {language}")


def _render_chinese_report(model: TextReportModel) -> str:
    lines = [
        "# 方法说明：Segment-Level RockSteady 文本后处理",
        "",
        "## 目的与解释边界",
        "",
        "该流程把 RockSteady Total 词典命中次数转换为 segment、video 和 speaker 三个层级的文本描述变量。",
        "这些变量是词频指标，不是 facial/audio 的情绪概率，也不能独立证明说话者真实体验了某种情绪。",
        "",
        "## 本次运行",
        "",
        f"- 输入：`{model.input_dir}`",
        f"- 输出：`{model.output_dir}`",
        f"- Whisper：`{model.whisper_root}`",
        f"- Prepare mapping：`{model.prepare_root}`",
        f"- 上游 provenance：`{model.provenance_status}`",
        f"- 对齐 mapping：`{', '.join(model.alignment_mapping_statuses)}`",
        f"- 视频：`{model.video_count}`；speakers：`{model.speaker_count}`",
        f"- Analysis segments：`{model.segment_count}`；source Whisper segments："
        f"`{model.source_segment_count}`；valid (`Terms > 0`)：`{model.valid_segment_count}`",
        f"- 缺失 RockSteady segments：`{model.missing_segment_count}`；忽略额外行：`{model.ignored_segment_count}`",
        f"- RockSteady Terms 总计：`{_format(model.terms_total)}`；SVG：`{model.graph_count}`",
        "",
        "## 建议阅读顺序",
        "",
        "1. `readable/video_level_summary.csv`：先看这张，每个视频一行，字段为普通名称和百分比。",
        "2. `readable/speaker_level_summary.csv`：跨视频查看 speaker 总体模式。",
        "3. `readable/segment_level/`：按 Speaker/Video（旧数据可含 Country）查看文本和时间。",
        "4. `output_manifest.json` 与 `segment_alignment_audit.csv`：需要审计时再看。",
        "5. `segment_counts/`、`segment_relative/`、`segment_level/`：程序和完整诊断表。",
        "6. `../multimodal/`：统一命名的 Transcript 心理构念、时间对齐表和 SVG 图片。",
        "",
        "## 实际类别契约",
        "",
        "| 输出字段前缀 | RockSteady 源列 | 可用视频 |",
        "|---|---|---:|",
    ]
    lines.extend(_category_table_rows(model))
    lines.extend(_calculation_section(language="zh"))
    lines.extend(
        [
            "",
            "## 当前 Speaker-Level 快速概览",
            "",
            *render_speaker_quick_table(model.speakers, language="zh"),
            "",
            "## 解释建议",
            "",
            "跨视频或 speaker 比较优先使用 `*_proportion`；它是 count / Terms 的 0–1 小数。",
            "`*_segment_percent` 是至少命中一次的 valid segment 百分比，范围 0–100，受 Whisper 切分方式影响。",
            "Positive Sentiment + Negative Sentiment 为 0 时 Text Valence 留空，不能把缺少正负词证据解释成中性 0。",
            "`../multimodal/` 中的构念分数是 lexical proxy；不能当作与 Facial/Audio 已校准的同一量表。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_english_report(model: TextReportModel) -> str:
    lines = [
        "# Methodological Note: Segment-Level RockSteady Text Postprocessing",
        "",
        "## Purpose and interpretation boundary",
        "",
        "This workflow converts RockSteady Total dictionary-hit counts into "
        "segment-, video-, and speaker-level text descriptors.",
        "They are word-frequency measures, not facial/audio emotion probabilities, "
        "and do not by themselves establish a speaker's experienced emotion.",
        "",
        "## This run",
        "",
        f"- Input: `{model.input_dir}`",
        f"- Output: `{model.output_dir}`",
        f"- Whisper: `{model.whisper_root}`",
        f"- Prepare mapping: `{model.prepare_root}`",
        f"- Upstream provenance: `{model.provenance_status}`",
        f"- Alignment mapping: `{', '.join(model.alignment_mapping_statuses)}`",
        f"- Videos: `{model.video_count}`; speakers: `{model.speaker_count}`",
        f"- Analysis segments: `{model.segment_count}`; source Whisper segments: "
        f"`{model.source_segment_count}`; valid (`Terms > 0`): `{model.valid_segment_count}`",
        f"- Missing RockSteady segments: `{model.missing_segment_count}`; "
        f"ignored extra rows: `{model.ignored_segment_count}`",
        f"- RockSteady Terms: `{_format(model.terms_total)}`; SVG files: `{model.graph_count}`",
        "",
        "## Recommended reading order",
        "",
        "1. `readable/video_level_summary.csv`: start here; one video per row with plain names and percentages.",
        "2. `readable/speaker_level_summary.csv`: speaker aggregates across videos.",
        "3. `readable/segment_level/`: text and timestamps under Speaker/Video "
        "(legacy data may include Country).",
        "4. `output_manifest.json` and `segment_alignment_audit.csv`: open these for auditing.",
        "5. `segment_counts/`, `segment_relative/`, and `segment_level/`: machine/full diagnostic tables.",
        "6. `../multimodal/`: consistently named Transcript constructs, timestamped "
        "alignment tables, and SVG charts.",
        "",
        "## Actual category contract",
        "",
        "| Output prefix | RockSteady source column(s) | Available videos |",
        "|---|---|---:|",
    ]
    lines.extend(_category_table_rows(model))
    lines.extend(_calculation_section(language="en"))
    lines.extend(
        [
            "",
            "## Current Speaker-Level Quick View",
            "",
            *render_speaker_quick_table(model.speakers, language="en"),
            "",
            "## Recommended interpretation",
            "",
            "Prefer `*_proportion` for video or speaker comparisons; it is the 0–1 decimal count / Terms.",
            "`*_segment_percent` is the 0–100 percentage of valid segments with at "
            "least one hit and depends on Whisper segmentation.",
            "Text Valence remains blank when Positive Sentiment + Negative Sentiment is zero; absence of "
            "positive/negative-word evidence is not neutral zero.",
            "Construct scores under `../multimodal/` are lexical proxies, not "
            "a scale calibrated to Facial or Audio outputs.",
        ]
    )
    return "\n".join(lines) + "\n"


def _category_table_rows(model: TextReportModel) -> list[str]:
    return [
        f"| `{item.category.key}` | "
        f"`{item.category.source_column or item.category.source_names[0]}` | "
        f"{item.available_videos}/{model.video_count} |"
        for item in model.categories
    ]


def _calculation_section(*, language: str) -> list[str]:
    if language == "zh":
        return [
            "",
            "## 计算",
            "",
            "```text",
            "category_proportion = category_count / RockSteady Terms",
            "category_segment_percent = segments with count > 0 / valid segments * 100",
            "valence_score = (positive_count - negative_count) / (positive_count + negative_count)",
            "```",
            "",
            "Video/speaker Text Valence 从该层级汇总后的 Positive Sentiment/Negative Sentiment totals 重新计算，不平均下一级 Text Valence。",
            "零 Terms、缺列和缺失 RockSteady 行保持显式不可用，不作为零计数进入统计。",
        ]
    return [
        "",
        "## Calculations",
        "",
        "```text",
        "category_proportion = category_count / RockSteady Terms",
        "category_segment_percent = segments with count > 0 / valid segments * 100",
        "valence_score = (positive_count - negative_count) / (positive_count + negative_count)",
        "```",
        "",
        "Video/speaker Text Valence is recalculated from aggregated Positive Sentiment/Negative Sentiment "
        "totals rather than averaging lower-level Text Valence.",
        "Zero-Term segments, absent columns, and missing RockSteady rows remain "
        "explicitly unavailable and do not enter statistics as zeroes.",
    ]


def _format(value: object) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, (int, float)):
        return str(value).replace("|", "\\|")
    number = float(value)
    if not math.isfinite(number):
        return ""
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    if abs(number) < 1:
        return f"{number:.6f}".rstrip("0").rstrip(".")
    return f"{number:.2f}".rstrip("0").rstrip(".")
