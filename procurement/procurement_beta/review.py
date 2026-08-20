from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

from procurement.procurement_beta.pipeline import PlannedSegment, SegmentPlan


def rejection_counts(plan: SegmentPlan) -> dict[str, int]:
    """Count rejected segment reasons for quick review."""

    return dict(Counter(segment.reason for segment in plan.rejected_segments))


def write_review_html(output_dir: Path, *, title: str, duration_seconds: float, plan: SegmentPlan) -> Path:
    """Write an offline timeline review page beside the beta manifests."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "review_timeline.html"
    path.write_text(render_review_html(title=title, duration_seconds=duration_seconds, plan=plan), encoding="utf-8")
    return path


def render_review_html(*, title: str, duration_seconds: float, plan: SegmentPlan) -> str:
    safe_title = html.escape(title or "Clean speaker beta review")
    counts = rejection_counts(plan)
    rows = "\n".join(
        [
            timeline_section("Selected", plan.selected_segments, duration_seconds, "#2563eb"),
            timeline_section("Clean overlap", plan.clean_segments, duration_seconds, "#16a34a"),
            timeline_section("Rejected", plan.rejected_segments, duration_seconds, "#dc2626"),
        ]
    )
    count_items = "".join(f"<li>{html.escape(reason)}: {count}</li>" for reason, count in sorted(counts.items()))
    if not count_items:
        count_items = "<li>No rejected segments.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{safe_title} clean speaker review</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #172033; background: #f7f9fc; }}
    h1 {{ margin: 0 0 8px; }}
    .summary {{ margin: 0 0 20px; color: #54637a; }}
    .panel {{ background: #fff; border: 1px solid #d8e0ec; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
    .timeline-row {{ display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 12px; align-items: center; margin: 10px 0; }}
    .track {{ height: 20px; background: #e9eef6; border-radius: 4px; position: relative; overflow: hidden; }}
    .bar {{ position: absolute; top: 0; bottom: 0; min-width: 2px; border-radius: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e4eaf2; padding: 6px; }}
    ul {{ margin: 8px 0 0; }}
  </style>
</head>
<body>
  <h1>{safe_title}</h1>
  <p class="summary">Duration: {duration_seconds:.2f}s</p>
  <section class="panel">
    <h2>Timeline</h2>
    {rows}
  </section>
  <section class="panel">
    <h2>Rejected Segment Reasons</h2>
    <ul>{count_items}</ul>
  </section>
</body>
</html>
"""


def timeline_section(label: str, segments: list[PlannedSegment], duration_seconds: float, color: str) -> str:
    bars = "".join(timeline_bar(segment, duration_seconds, color) for segment in segments)
    table = segment_table(segments)
    return f"""
    <div class="timeline-row">
      <strong>{html.escape(label)}</strong>
      <div>
        <div class="track">{bars}</div>
        {table}
      </div>
    </div>
"""


def timeline_bar(segment: PlannedSegment, duration_seconds: float, color: str) -> str:
    duration = max(0.001, float(duration_seconds))
    left = max(0.0, min(100.0, (segment.interval.start / duration) * 100.0))
    width = max(0.1, min(100.0 - left, (segment.interval.duration / duration) * 100.0))
    title = html.escape(f"{segment.reason}: {segment.interval.start:.2f}-{segment.interval.end:.2f}s")
    return f'<span class="bar" title="{title}" style="left:{left:.3f}%;width:{width:.3f}%;background:{color};"></span>'


def segment_table(segments: list[PlannedSegment]) -> str:
    if not segments:
        return "<p>No segments.</p>"
    rows = "".join(
        f"<tr><td>{segment.interval.start:.2f}</td><td>{segment.interval.end:.2f}</td>"
        f"<td>{segment.interval.duration:.2f}</td><td>{segment.interval.confidence:.3f}</td>"
        f"<td>{html.escape(segment.reason)}</td></tr>"
        for segment in segments
    )
    return f"<table><thead><tr><th>Start</th><th>End</th><th>Duration</th><th>Confidence</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table>"
