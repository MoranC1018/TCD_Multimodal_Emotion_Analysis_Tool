#!/usr/bin/env python3
r"""
blind_youtube_license_verifier.py

Purpose
-------
Independently verify YouTube licence data in a DOCX file, without trusting
or reading the document's existing licence-result columns until AFTER the
YouTube-side checks are complete.

This is intended for research teams maintaining video-source tables over time.

What this script checks
-----------------------
1. Extracts YouTube video IDs from the first column of every table.
   - Handles visible URLs.
   - Handles hidden Word hyperlink targets where the visible cell text is only a title.
2. Queries the official YouTube Data API for each video ID.
   - Uses videos.list(part=snippet,status).
   - Reads status.license, whose official values are:
       creativeCommon
       youtube
3. Scans the title + description for licence-related language.
   - This does NOT override the YouTube API licence.
   - It is used to flag conflicts/manual-review cases.
4. Only after steps 1-3, reads the existing licence columns from the document
   and compares the document result with the independent result.
5. Writes a CSV report and a plain-text summary.

Important interpretation rule
-----------------------------
YouTube API licence and description text are different evidence sources.

- status.license = "creativeCommon"
    YouTube platform flag says Creative Commons Attribution / CC BY.
- status.license = "youtube"
    YouTube platform flag says Standard YouTube License.
- Description says "Creative Commons" but status.license says "youtube"
    Record as Standard YouTube License by API, with a manual-review note.
- status.license says "creativeCommon" but description says "all rights reserved"
    Record as YouTube CC, with a manual-review conflict note.

Requirements
------------
python -m pip install python-docx

Usage
-----
PowerShell:

    $env:YOUTUBE_API_KEY="<key>"
    python .\blind_youtube_license_verifier.py ".\source_catalog_license_audit.docx"

Optional:

    python .\blind_youtube_license_verifier.py ".\source_catalog_license_audit.docx" `
        --out-csv ".\blind_license_verification.csv" `
        --summary ".\blind_license_verification_summary.txt"

Exit codes
----------
0 = completed
1 = completed, but found mismatches/manual review items/missing API rows
2 = setup or input error
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:  # pragma: no cover - direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from procurement.video_sampling.run_docx_extractions import open_docx_document
from procurement.input_limits import read_term_dictionary
from spreadsheet_safety import SpreadsheetSafeWriter

try:
    from docx import Document
    from docx.oxml.ns import qn
except ImportError as exc:
    raise SystemExit(
        "ERROR: python-docx is not installed. Run: python -m pip install python-docx"
    ) from exc


YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# YouTube video IDs are 11 characters: letters, numbers, underscore, dash.
YOUTUBE_ID_RE = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"(?:youtube\.com/watch\?(?:[^#\s]*&)?v=|youtu\.be/|youtube\.com/shorts/)"
    r"([A-Za-z0-9_-]{11})"
)

# Fallback for cells where only a bare 11-character ID appears.
BARE_VIDEO_ID_RE = re.compile(r"\b[A-Za-z0-9_-]{11}\b")


# ---------------------------------------------------------------------------
# Licence-term dictionary
# ---------------------------------------------------------------------------
# Keep this dictionary deliberately transparent and easy to edit.
# It is not legal advice. It simply highlights terms that a human auditor
# may want to review.
DEFAULT_TERM_DICTIONARY = {
    "strong_cc_signals": [
        r"\bcreative commons\b",
        r"\bcc[-\s]?by\b",
        r"\bcc[-\s]?by[-\s]?sa\b",
        r"\bcc[-\s]?by[-\s]?nc\b",
        r"\bcc[-\s]?by[-\s]?nd\b",
        r"\bcc[-\s]?0\b",
        r"\bcc0\b",
        r"creativecommons\.org/licenses/",
        r"creativecommons\.org/publicdomain/",
        r"\blicensed under (?:a )?creative commons\b",
    ],
    "public_domain_signals": [
        r"\bpublic domain\b",
        r"\bno known copyright restrictions\b",
        r"\bfree cultural work\b",
    ],
    "restrictive_signals": [
        r"\ball rights reserved\b",
        r"\bdo not re[-\s]?upload\b",
        r"\bdo not redistribute\b",
        r"\bunauthori[sz]ed use\b",
        r"\bno part of this\b.*\breproduced\b",
        r"\bcopyright(?:ed)? material\b",
        r"\bused with permission\b",
    ],
    "ambiguous_signals": [
        r"\broyalty[-\s]?free\b",
        r"\bcopyright[-\s]?free\b",
        r"\bfair use\b",
        r"\bfor educational purposes\b",
        r"\bcredit to\b",
        r"\bsource:\b",
    ],
}


@dataclass
class ExtractedRow:
    """A video row extracted from a Word table before YouTube verification."""

    table_number: int
    row_number: int
    has_header_row: bool
    first_column_text: str
    extracted_url_or_hyperlink: str
    video_id: str
    speaker_or_second_col: str
    upload_date_or_third_col: str

    # Existing document result columns.
    # These are intentionally populated after extraction; the verification
    # routine does not use them to decide the independent licence.
    document_license: str = ""
    document_youtube_api_license: str = ""
    document_description_signals: str = ""
    document_license_notes: str = ""
    document_checked_date: str = ""


@dataclass
class VerificationRow:
    """Final row written to CSV after independent verification + comparison."""

    table_number: int
    row_number: int
    video_id: str
    url: str
    document_title_or_first_col: str
    youtube_title: str
    youtube_channel: str
    youtube_published_at: str
    raw_api_license: str
    independent_youtube_api_license: str
    independent_description_signals: str
    independent_license_notes: str
    checked_at: str

    document_license: str
    document_youtube_api_license: str
    document_description_signals: str
    document_license_notes: str
    document_checked_date: str

    match_document_license: str
    match_document_youtube_api_license: str
    needs_manual_review: str
    manual_review_reason: str


def normalise_space(text: str) -> str:
    """Collapse whitespace so comparisons are less fragile."""
    return re.sub(r"\s+", " ", (text or "").strip())


def normalise_for_compare(text: str) -> str:
    """Lowercase and normalise punctuation-ish spacing for simple comparisons."""
    return normalise_space(text).lower()


def extract_hyperlink_targets(cell) -> list[str]:
    """
    Return all hyperlink targets from a python-docx table cell.

    Word stores many links separately from visible text. In this project, many
    first-column cells display a title while the actual YouTube URL is stored as
    a hidden hyperlink target. This function recovers those targets.
    """
    links: list[str] = []
    part = cell.part

    # Standard Word hyperlinks: <w:hyperlink r:id="rId...">
    for hyperlink in cell._tc.xpath(".//w:hyperlink"):
        rid = hyperlink.get(qn("r:id"))
        if rid and rid in part.rels:
            links.append(part.rels[rid].target_ref)

    # Less common field-code hyperlinks: HYPERLINK "https://..."
    for instr in cell._tc.xpath(".//w:instrText"):
        text = instr.text or ""
        match = re.search(r'HYPERLINK\s+"([^"]+)"', text, flags=re.IGNORECASE)
        if match:
            links.append(match.group(1))

    # Remove duplicates while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for link in links:
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


def extract_video_id_from_texts(texts: Iterable[str]) -> tuple[str, str]:
    """
    Find a YouTube video ID in a list of candidate strings.

    Returns:
        (video_id, source_text_that_contained_it)
    """
    for text in texts:
        if not text:
            continue
        match = YOUTUBE_ID_RE.search(text)
        if match:
            return match.group(1), match.group(0)

    # Fallback: only accept bare IDs if the surrounding text is very small.
    # This avoids accidentally treating random words as video IDs.
    for text in texts:
        compact = normalise_space(text)
        if len(compact) <= 80:
            match = BARE_VIDEO_ID_RE.search(compact)
            if match:
                return match.group(0), compact

    return "", ""


def map_headers(header_cells: list[str]) -> dict[str, int]:
    """
    Map normalised header labels to their column indexes.

    This lets the script tolerate minor variations such as:
      Date vs Upload date
      Time stamps vs Timestamps
    """
    mapping: dict[str, int] = {}
    for i, label in enumerate(header_cells):
        key = normalise_for_compare(label)
        mapping[key] = i
    return mapping


def find_col(header_map: dict[str, int], possible_names: list[str], default: int | None = None) -> int | None:
    """Find a column index from several possible header names."""
    for name in possible_names:
        key = normalise_for_compare(name)
        if key in header_map:
            return header_map[key]
    return default


def extract_rows_from_docx(docx_path: Path) -> list[ExtractedRow]:
    """
    Extract video rows from every table in the DOCX.

    Blinding note:
    This function extracts all video IDs from first-column text/hyperlinks.
    It also stores existing document result columns for later comparison, but
    those fields are never used to call the API or decide the independent result.
    """
    doc = open_docx_document(docx_path)
    extracted: list[ExtractedRow] = []

    for table_number, table in enumerate(doc.tables, start=1):
        if not table.rows:
            continue

        first_row_text = [normalise_space(cell.text) for cell in table.rows[0].cells]
        first_row_lower = [text.lower() for text in first_row_text]
        has_header = "link" in first_row_lower

        if has_header:
            headers = first_row_text
            header_map = map_headers(headers)
            link_col = find_col(header_map, ["Link"], default=0) or 0
            speaker_col = find_col(header_map, ["Speaker"], default=1)
            date_col = find_col(header_map, ["Upload date", "Date uploaded", "Date"], default=2)
            license_col = find_col(header_map, ["License"])
            api_license_col = find_col(header_map, ["YouTube API License"])
            signals_col = find_col(header_map, ["Description License Signals"])
            notes_col = find_col(header_map, ["License Notes"])
            checked_col = find_col(header_map, ["Date Checked", "License checked date"])
            start_row = 1
        else:
            # Some tables in the supplied document appear to have no header row.
            # In those cases, the first column is still the link/title column.
            link_col = 0
            speaker_col = 1 if len(table.rows[0].cells) > 1 else None
            date_col = 2 if len(table.rows[0].cells) > 2 else None
            license_col = api_license_col = signals_col = notes_col = checked_col = None
            start_row = 0

        for row_number, row in enumerate(table.rows[start_row:], start=start_row + 1):
            cells = row.cells
            if not cells or link_col >= len(cells):
                continue

            first_cell = cells[link_col]
            first_col_text = normalise_space(first_cell.text)
            hyperlinks = extract_hyperlink_targets(first_cell)

            video_id, source_text = extract_video_id_from_texts([first_col_text, *hyperlinks])

            # Skip non-video rows such as "27 total" or blank separators.
            if not video_id:
                continue

            def cell_text(index: int | None) -> str:
                if index is None or index >= len(cells):
                    return ""
                return normalise_space(cells[index].text)

            extracted.append(
                ExtractedRow(
                    table_number=table_number,
                    row_number=row_number,
                    has_header_row=has_header,
                    first_column_text=first_col_text,
                    extracted_url_or_hyperlink=source_text,
                    video_id=video_id,
                    speaker_or_second_col=cell_text(speaker_col),
                    upload_date_or_third_col=cell_text(date_col),
                    document_license=cell_text(license_col),
                    document_youtube_api_license=cell_text(api_license_col),
                    document_description_signals=cell_text(signals_col),
                    document_license_notes=cell_text(notes_col),
                    document_checked_date=cell_text(checked_col),
                )
            )

    return extracted


def api_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET JSON from the YouTube Data API with helpful error messages."""
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"

    try:
        with urllib.request.urlopen(full_url, timeout=60) as response:
            body = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc

    data = json.loads(body)
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], indent=2))
    return data


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    """Yield fixed-size chunks for batched API calls."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_youtube_metadata(api_key: str, video_ids: list[str], sleep_seconds: float = 0.0) -> dict[str, dict[str, Any]]:
    """
    Fetch metadata for video IDs using the official YouTube Data API.

    The videos.list endpoint accepts up to 50 IDs per request.
    """
    metadata: dict[str, dict[str, Any]] = {}

    for batch in chunks(video_ids, 50):
        data = api_get_json(
            YOUTUBE_VIDEOS_URL,
            {
                "part": "snippet,status",
                "id": ",".join(batch),
                "maxResults": 50,
                "key": api_key,
            },
        )

        for item in data.get("items", []):
            metadata[item.get("id", "")] = item

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return metadata


def compile_dictionary(term_dict: dict[str, list[str]]) -> dict[str, list[re.Pattern[str]]]:
    """Compile regex patterns from the editable term dictionary."""
    compiled: dict[str, list[re.Pattern[str]]] = {}
    for category, patterns in term_dict.items():
        compiled[category] = [re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns]
    return compiled


def find_term_signals(text: str, compiled_terms: dict[str, list[re.Pattern[str]]]) -> dict[str, list[str]]:
    """
    Find licence-related text signals in title + description.

    Returns a dict of category -> matched pattern strings.
    """
    found: dict[str, list[str]] = {}
    for category, patterns in compiled_terms.items():
        for pattern in patterns:
            if pattern.search(text or ""):
                found.setdefault(category, []).append(pattern.pattern)
    return found


def format_signals(signals: dict[str, list[str]]) -> str:
    """Human-readable signal summary for CSV."""
    if not signals:
        return "No description licence signals found"
    parts: list[str] = []
    for category, patterns in signals.items():
        parts.append(f"{category}: " + ", ".join(patterns))
    return " | ".join(parts)


def raw_license_to_label(raw: str) -> str:
    """Convert YouTube API raw licence values to readable labels."""
    if raw == "creativeCommon":
        return "Creative Commons Attribution (CC BY)"
    if raw == "youtube":
        return "Standard YouTube License"
    if not raw:
        return "UNKNOWN / NOT RETURNED"
    return f"UNKNOWN RAW LICENSE: {raw}"


def decide_notes(raw_license: str, signals: dict[str, list[str]]) -> tuple[str, str, str]:
    """
    Build audit notes and manual-review flag.

    Returns:
        (notes, needs_manual_review, reason)
    """
    notes: list[str] = []
    reasons: list[str] = []

    if raw_license:
        notes.append(f"YouTube API status.license says {raw_license}.")
    else:
        notes.append("YouTube API did not return status.license.")
        reasons.append("Missing YouTube API licence.")

    has_cc_claim = bool(signals.get("strong_cc_signals") or signals.get("public_domain_signals"))
    has_restrictive = bool(signals.get("restrictive_signals"))
    has_ambiguous = bool(signals.get("ambiguous_signals"))

    if raw_license == "youtube" and has_cc_claim:
        reasons.append("Description/title contains CC or public-domain wording but YouTube API says Standard.")
    if raw_license == "creativeCommon" and has_restrictive:
        reasons.append("YouTube API says Creative Commons but description/title contains restrictive wording.")
    if has_ambiguous:
        reasons.append("Description/title contains ambiguous reuse wording.")

    if reasons:
        notes.append("Manual review recommended: " + "; ".join(reasons))

    return " ".join(notes), "YES" if reasons else "NO", "; ".join(reasons)


def compare_labels(document_value: str, independent_value: str) -> str:
    """Compare document label to independent label with mild normalisation."""
    if not document_value:
        return "NO DOCUMENT VALUE"
    doc_norm = normalise_for_compare(document_value)
    ind_norm = normalise_for_compare(independent_value)

    # Accept exact match, or document value that starts with the independent
    # value but contains a manual-review suffix.
    if doc_norm == ind_norm or doc_norm.startswith(ind_norm):
        return "YES"
    return "NO"


def verify_rows(rows: list[ExtractedRow], metadata: dict[str, dict[str, Any]], term_dict: dict[str, list[str]]) -> list[VerificationRow]:
    """Create final verification rows after independent YouTube checks."""
    compiled_terms = compile_dictionary(term_dict)
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    verified: list[VerificationRow] = []

    for row in rows:
        item = metadata.get(row.video_id, {})
        snippet = item.get("snippet", {}) if item else {}
        status = item.get("status", {}) if item else {}

        youtube_title = normalise_space(snippet.get("title", ""))
        youtube_channel = normalise_space(snippet.get("channelTitle", ""))
        youtube_published_at = normalise_space(snippet.get("publishedAt", ""))
        description = snippet.get("description", "")

        raw_license = status.get("license", "")
        independent_label = raw_license_to_label(raw_license)

        # Scan YouTube title and description, not the DOCX text.
        signals = find_term_signals(f"{youtube_title}\n\n{description}", compiled_terms)
        signal_summary = format_signals(signals)
        notes, needs_manual_review, reason = decide_notes(raw_license, signals)

        match_doc_license = compare_labels(row.document_license, independent_label)
        if row.document_youtube_api_license:
            match_doc_api = compare_labels(row.document_youtube_api_license, independent_label)
        else:
            match_doc_api = "NOT PRESENT BY DESIGN"

        mismatch_reasons: list[str] = []
        if match_doc_license == "NO":
            mismatch_reasons.append("Document License differs from independent API label.")
        if match_doc_api == "NO":
            mismatch_reasons.append("Document YouTube API License differs from independent API label.")
        if match_doc_license == "NO DOCUMENT VALUE":
            mismatch_reasons.append("Document is missing the License column value for this row.")
        if reason:
            mismatch_reasons.append(reason)

        final_manual = "YES" if mismatch_reasons or needs_manual_review == "YES" else "NO"
        final_reason = "; ".join(mismatch_reasons)

        verified.append(
            VerificationRow(
                table_number=row.table_number,
                row_number=row.row_number,
                video_id=row.video_id,
                url=f"https://www.youtube.com/watch?v={row.video_id}",
                document_title_or_first_col=row.first_column_text,
                youtube_title=youtube_title,
                youtube_channel=youtube_channel,
                youtube_published_at=youtube_published_at,
                raw_api_license=raw_license,
                independent_youtube_api_license=independent_label,
                independent_description_signals=signal_summary,
                independent_license_notes=notes,
                checked_at=checked_at,
                document_license=row.document_license,
                document_youtube_api_license=row.document_youtube_api_license,
                document_description_signals=row.document_description_signals,
                document_license_notes=row.document_license_notes,
                document_checked_date=row.document_checked_date,
                match_document_license=match_doc_license,
                match_document_youtube_api_license=match_doc_api,
                needs_manual_review=final_manual,
                manual_review_reason=final_reason,
            )
        )

    return verified


def write_csv(rows: list[VerificationRow], out_path: Path) -> None:
    """Write verification rows to CSV."""
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return

    fieldnames = list(asdict(rows[0]).keys())
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = SpreadsheetSafeWriter(csv.DictWriter(f, fieldnames=fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_summary(
    summary_path: Path,
    docx_path: Path,
    extracted_rows: list[ExtractedRow],
    verified_rows: list[VerificationRow],
    missing_from_api: list[str],
) -> None:
    """Write a human-readable audit summary."""
    total_rows = len(extracted_rows)
    unique_ids = len({row.video_id for row in extracted_rows})
    with_doc_audit = sum(1 for row in extracted_rows if row.document_license or row.document_checked_date)
    without_doc_audit = total_rows - with_doc_audit

    raw_counts = Counter(row.raw_api_license or "missing" for row in verified_rows)
    manual_count = sum(1 for row in verified_rows if row.needs_manual_review == "YES")
    mismatch_count = sum(
        1
        for row in verified_rows
        if row.match_document_license == "NO" or row.match_document_youtube_api_license == "NO"
    )
    no_doc_value_count = sum(
        1
        for row in verified_rows
        if row.match_document_license == "NO DOCUMENT VALUE"
    )

    table_counts = Counter(row.table_number for row in extracted_rows)
    table_audit_counts = Counter(row.table_number for row in extracted_rows if row.document_license or row.document_checked_date)

    lines: list[str] = []
    lines.append("Blind YouTube Licence Verification Summary")
    lines.append("=" * 46)
    lines.append(f"Input DOCX: {docx_path}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("Extraction")
    lines.append("----------")
    lines.append(f"Video rows extracted from first-column text/hyperlinks: {total_rows}")
    lines.append(f"Unique YouTube video IDs: {unique_ids}")
    lines.append(f"Rows that already had document audit values: {with_doc_audit}")
    lines.append(f"Rows missing document audit values: {without_doc_audit}")
    lines.append("")
    lines.append("Rows by table")
    lines.append("-------------")
    for table_number in sorted(table_counts):
        lines.append(
            f"Table {table_number}: {table_counts[table_number]} video rows; "
            f"{table_audit_counts[table_number]} had existing document audit values"
        )
    lines.append("")
    lines.append("Independent API results")
    lines.append("-----------------------")
    for raw, count in sorted(raw_counts.items()):
        lines.append(f"{raw}: {count}")
    lines.append("")
    lines.append(f"Video IDs not returned by YouTube API: {len(missing_from_api)}")
    if missing_from_api:
        lines.append(", ".join(missing_from_api[:50]))
        if len(missing_from_api) > 50:
            lines.append(f"... plus {len(missing_from_api) - 50} more")
    lines.append("")
    lines.append("Comparison with document")
    lines.append("------------------------")
    lines.append(f"Rows requiring manual review: {manual_count}")
    lines.append(f"Rows where existing document value mismatched independent result: {mismatch_count}")
    lines.append(f"Rows missing existing document License values: {no_doc_value_count}")
    lines.append("")
    lines.append("Notes")
    lines.append("-----")
    lines.append(
        "The script extracts video IDs before comparing any existing licence columns. "
        "The independent result comes from YouTube Data API status.license plus a "
        "separate title/description term scan."
    )
    lines.append(
        "Description text does not override YouTube's platform licence flag; it only "
        "creates a manual-review note when it conflicts or looks ambiguous."
    )

    summary_path.write_text("\n".join(lines), encoding="utf-8")


def load_dictionary(path: str | None) -> dict[str, list[str]]:
    """Load an optional JSON term dictionary, or use the built-in default."""
    if not path:
        return DEFAULT_TERM_DICTIONARY
    return read_term_dictionary(Path(path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Blindly verify YouTube licence data in a DOCX before comparing to existing document columns."
    )
    parser.add_argument("docx", help="Input DOCX file containing video tables.")
    parser.add_argument(
        "--api-key",
        default=os.getenv("YOUTUBE_API_KEY"),
        help="YouTube Data API key. Defaults to YOUTUBE_API_KEY environment variable.",
    )
    parser.add_argument(
        "--out-csv",
        default="blind_youtube_license_verification.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--summary",
        default="blind_youtube_license_verification_summary.txt",
        help="Output text summary path.",
    )
    parser.add_argument(
        "--dictionary-json",
        default=None,
        help="Optional JSON file with licence-term regex dictionary.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional delay between API batches.",
    )
    args = parser.parse_args()

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"ERROR: file not found: {docx_path}", file=sys.stderr)
        return 2

    if not args.api_key:
        print(
            "ERROR: missing YouTube API key. Set $env:YOUTUBE_API_KEY or pass --api-key.",
            file=sys.stderr,
        )
        return 2

    try:
        term_dict = load_dictionary(args.dictionary_json)
    except Exception as exc:
        print(f"ERROR: could not load dictionary: {exc}", file=sys.stderr)
        return 2

    extracted_rows = extract_rows_from_docx(docx_path)
    if not extracted_rows:
        print("ERROR: no YouTube video rows found in the document.", file=sys.stderr)
        return 2

    # Preserve first-seen order while de-duplicating video IDs.
    unique_ids: list[str] = []
    seen: set[str] = set()
    for row in extracted_rows:
        if row.video_id not in seen:
            seen.add(row.video_id)
            unique_ids.append(row.video_id)

    print(f"Extracted {len(extracted_rows)} video rows.")
    print(f"Unique YouTube IDs: {len(unique_ids)}")
    print("Querying YouTube Data API...")

    try:
        metadata = fetch_youtube_metadata(args.api_key, unique_ids, sleep_seconds=args.sleep_seconds)
    except Exception as exc:
        print(f"ERROR: YouTube API check failed: {exc}", file=sys.stderr)
        return 2

    missing_from_api = [video_id for video_id in unique_ids if video_id not in metadata]
    verified_rows = verify_rows(extracted_rows, metadata, term_dict)

    out_csv = Path(args.out_csv)
    summary_path = Path(args.summary)
    write_csv(verified_rows, out_csv)
    write_summary(summary_path, docx_path, extracted_rows, verified_rows, missing_from_api)

    raw_counts = Counter(row.raw_api_license or "missing" for row in verified_rows)
    manual_count = sum(1 for row in verified_rows if row.needs_manual_review == "YES")

    print()
    print("Done.")
    print(f"CSV report: {out_csv.resolve()}")
    print(f"Summary:    {summary_path.resolve()}")
    print("Raw API licence counts:")
    for raw, count in sorted(raw_counts.items()):
        print(f"  {raw}: {count}")
    print(f"Manual-review rows: {manual_count}")

    return 1 if manual_count or missing_from_api else 0


if __name__ == "__main__":
    raise SystemExit(main())
