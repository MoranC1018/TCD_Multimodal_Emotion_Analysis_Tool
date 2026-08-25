"""Read imported transcript construct results without invoking text processing."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from processing.io_utils import (
    assert_confined_input_file,
    assert_input_file_budget,
    assert_no_output_path_aliases,
)
from typing import Literal, Mapping

from analysis.combined_summary import (
    TEXT_CONSTRUCTS,
    TextConstructSummary,
    resolve_speaker,
)
from analysis.metadata import load_source_metadata, normalise_identity
from analysis.text_pipeline.ownership import PAIR_KIND
from processing.audio_analysis.audio_pipeline.source_context import snapshot_run_sidecars


class TextResultsError(ValueError):
    """Raised when an imported transcript summary violates its data contract."""


@dataclass(frozen=True)
class TextResultsDiscovery:
    summary_path: Path
    summaries: tuple[TextConstructSummary, ...]
    grain: Literal["speaker", "source"] = "speaker"


_IDENTITY_COLUMNS = (
    "Country",
    "Speaker",
    "Speaker ID",
    "Videos",
    "Valid segments",
    "RockSteady terms",
)
_SENTIMENT_ALIASES = {
    "Positive Sentiment": ("Positive Sentiment", "Positive valence"),
    "Negative Sentiment": ("Negative Sentiment", "Negative valence"),
}
_REQUIRED_COLUMNS = frozenset((*_IDENTITY_COLUMNS, *TEXT_CONSTRUCTS[3:]))
_CONSTRUCT_RANGES = {
    "Positive Sentiment": (0.0, 1.0),
    "Negative Sentiment": (0.0, 1.0),
    "Text Valence": (-1.0, 1.0),
    "Arousal / Activation": (-1.0, 1.0),
    "Dominance / Power": (-1.0, 1.0),
    "Affiliation / Social orientation": (-1.0, 1.0),
}

_NATIVE_IDENTITY_COLUMNS = (
    "Country", "Speaker", "Speaker ID", "Video", "Source ID",
    "Valid segments", "RockSteady terms",
)


def _candidate_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return tuple(next(csv.reader(handle), ()))
    except (OSError, UnicodeError, csv.Error):
        return ()


def _compatible_header(header: tuple[str, ...] | list[str]) -> bool:
    available = set(header)
    return _REQUIRED_COLUMNS.issubset(available) and all(
        any(alias in available for alias in aliases)
        for aliases in _SENTIMENT_ALIASES.values()
    )


def _find_summary(root: Path) -> Path:
    root = assert_no_output_path_aliases(root, description="Text results input").resolve(strict=True)
    candidates = []
    for path in root.rglob("speaker_level_summary.csv"):
        safe = assert_confined_input_file(path, root, description="Text results input")
        if _compatible_header(_candidate_header(safe)):
            candidates.append(safe)
    assert_input_file_budget(candidates, description="Text results input")
    if not candidates:
        raise TextResultsError(
            "No compatible multimodal/speaker_level_summary.csv was found in the text results folder"
        )
    if len(candidates) > 1:
        listed = ", ".join(str(path) for path in sorted(candidates))
        raise TextResultsError(f"Multiple compatible text speaker summaries were found: {listed}")
    return candidates[0]


def _required_integer(row: dict[str, str], column: str, row_number: int) -> int:
    try:
        number = int(str(row.get(column, "")).strip())
    except ValueError as exc:
        raise TextResultsError(f"Row {row_number}: {column} must be a non-negative integer") from exc
    if number < 0:
        raise TextResultsError(f"Row {row_number}: {column} must be a non-negative integer")
    return number


def _construct_value(
    row: dict[str, str], source_column: str, construct: str, row_number: int
) -> float | None:
    raw = str(row.get(source_column, "")).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise TextResultsError(
            f"Row {row_number}: {source_column} must be numeric or blank"
        ) from exc
    lower, upper = _CONSTRUCT_RANGES[construct]
    if not math.isfinite(value) or value < lower or value > upper:
        raise TextResultsError(
            f"Row {row_number}: {source_column} must be between {lower:g} and {upper:g}"
        )
    return value


def discover_text_results(root: str | Path) -> TextResultsDiscovery:
    """Prefer verified SourceID-grain Text results, with legacy speaker fallback."""

    source_root = Path(root).expanduser().resolve()
    if not source_root.is_dir():
        raise TextResultsError(f"Text results folder does not exist: {source_root}")
    native = _find_native_summary(source_root)
    if native is not None:
        return _load_native_summary(source_root, native)
    summary_path = _find_summary(source_root)
    summaries: dict[str, TextConstructSummary] = {}
    try:
        with summary_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not _compatible_header(reader.fieldnames):
                raise TextResultsError("Text speaker summary is missing required columns")
            for row_number, row in enumerate(reader, start=2):
                speaker_label = str(row.get("Speaker", "")).strip()
                speaker_reference = str(row.get("Speaker ID", "")).strip()
                if not speaker_label or not speaker_reference:
                    raise TextResultsError(f"Row {row_number}: Speaker and Speaker ID are required")
                try:
                    speaker = resolve_speaker(speaker_label)
                except ValueError as exc:
                    raise TextResultsError(f"Row {row_number}: {exc}") from exc
                if speaker.speaker_id in summaries:
                    raise TextResultsError(f"Duplicate text summary for {speaker.display_name}")
                country = str(row.get("Country", "")).strip()
                _required_integer(row, "Videos", row_number)
                _required_integer(row, "Valid segments", row_number)
                _required_integer(row, "RockSteady terms", row_number)
                constructs: dict[str, float | None] = {}
                for construct in TEXT_CONSTRUCTS:
                    if construct == "Text Valence":
                        continue
                    aliases = _SENTIMENT_ALIASES.get(construct, (construct,))
                    source_column = next(alias for alias in aliases if alias in reader.fieldnames)
                    constructs[construct] = _construct_value(
                        row, source_column, construct, row_number
                    )
                constructs["Text Valence"] = _text_valence(
                    constructs["Positive Sentiment"], constructs["Negative Sentiment"]
                )
                if not any(value is not None for value in constructs.values()):
                    raise TextResultsError(
                        f"Row {row_number}: at least one transcript construct must be available"
                    )
                summaries[speaker.speaker_id] = TextConstructSummary(
                    speaker_id=speaker.speaker_id,
                    display_name=speaker.display_name,
                    country=country,
                    constructs=constructs,
                    source_path=summary_path,
                )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise TextResultsError(f"Could not read text speaker summary: {summary_path}") from exc
    if not summaries:
        raise TextResultsError("Text speaker summary contains no speaker rows")
    ordered = tuple(summaries.values())
    return TextResultsDiscovery(summary_path, ordered, "speaker")


def _find_native_summary(root: Path) -> Path | None:
    root = assert_no_output_path_aliases(root, description="Text results input").resolve(strict=True)
    candidates = []
    for path in root.rglob("video_level_summary.csv"):
        path = assert_confined_input_file(path, root, description="Text results input")
        header = set(_candidate_header(path))
        if set(_NATIVE_IDENTITY_COLUMNS).issubset(header) and all(
            any(alias in header for alias in aliases)
            for aliases in _SENTIMENT_ALIASES.values()
        ) and set(TEXT_CONSTRUCTS[3:]).issubset(header):
            candidates.append(path)
    assert_input_file_budget(candidates, description="Text results input")
    if len(candidates) > 1:
        raise TextResultsError(
            "Multiple compatible native Text video summaries were found: "
            + ", ".join(str(path) for path in sorted(candidates))
        )
    return candidates[0] if candidates else None


def _load_native_summary(root: Path, summary_path: Path) -> TextResultsDiscovery:
    pair_root = summary_path.parent.parent
    batch_path = pair_root / "text_postprocessing_batch_manifest.json"
    batch = _read_json(batch_path, "native Text pair manifest")
    if batch.get("kind") != PAIR_KIND or batch.get("status") != "completed":
        raise TextResultsError("Native Text pair manifest is incomplete or unsupported")
    multimodal = batch.get("multimodal")
    if not isinstance(multimodal, Mapping):
        raise TextResultsError("Native Text pair manifest has no multimodal contract")
    verified_summary_path, verified_summary_bytes = _verify_bound_artifact_snapshot(
        pair_root,
        multimodal,
        "video_summary",
        "video_summary_sha256",
    )
    if verified_summary_path != summary_path:
        raise TextResultsError(
            "Native Text discovered summary does not match the manifest-bound video summary"
        )
    contract_path = _verify_bound_artifact(pair_root, multimodal, "contract", "contract_sha256")
    contract = _read_json(contract_path, "native Text alignment contract")
    if contract.get("kind") != "transcript-multimodal-alignment":
        raise TextResultsError("Native Text alignment contract has the wrong kind")
    declared_ids = multimodal.get("source_ids")
    if not isinstance(declared_ids, list) or not all(isinstance(value, str) for value in declared_ids):
        raise TextResultsError("Native Text pair manifest has no SourceID inventory")
    if len(declared_ids) != len(set(declared_ids)):
        raise TextResultsError("Native Text pair manifest repeats a SourceID")
    try:
        source_binding = batch.get("source_binding")
        if not isinstance(source_binding, Mapping) or source_binding.get("kind") != "catalog-source-sidecars":
            raise ValueError("Native Text pair manifest has no catalog source binding")
        manifest_path = _verify_bound_artifact(
            pair_root,
            source_binding,
            "source_manifest",
            "source_manifest_sha256",
        )
        metadata_path = _verify_bound_artifact(
            pair_root,
            source_binding,
            "source_metadata",
            "source_metadata_sha256",
        )
        expected_manifest_path = (pair_root / "source_manifest.json").resolve()
        expected_metadata_path = (pair_root / "source_metadata.csv").resolve()
        if manifest_path != expected_manifest_path or metadata_path != expected_metadata_path:
            raise ValueError("Native Text source sidecars are not an explicit run-root pair")
        expected_manifest_sha256 = str(source_binding.get("source_manifest_sha256") or "").casefold()
        metadata = load_source_metadata(manifest_path, expected_sha256=expected_manifest_sha256)
        contexts = _bound_source_contexts(source_binding, declared_ids)
        snapshot_run_sidecars(
            pair_root,
            expected_source_ids=set(declared_ids),
            source_bindings=[(manifest_path, context) for context in contexts],
            require_mapped_input_paths=False,
            expected_catalog_sha256=str(source_binding.get("catalog_sha256") or ""),
        )
    except (OSError, ValueError) as exc:
        raise TextResultsError(f"Native Text source sidecar association is invalid: {exc}") from exc
    metadata_by_id = {source.source_id: source for source in metadata.sources if source.selected}
    summaries: list[TextConstructSummary] = []
    seen: set[str] = set()
    try:
        with io.StringIO(verified_summary_bytes.decode("utf-8-sig"), newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise TextResultsError("Native Text video summary has no header")
            for row_number, row in enumerate(reader, start=2):
                source_id = str(row.get("Source ID") or "").strip()
                if source_id in seen:
                    raise TextResultsError(f"Row {row_number}: duplicate native Text SourceID {source_id}")
                source = metadata_by_id.get(source_id)
                if source is None:
                    raise TextResultsError(f"Row {row_number}: unknown or unselected native Text SourceID {source_id}")
                if normalise_identity(row.get("Speaker")) != source.speaker_key:
                    raise TextResultsError(f"Row {row_number}: native Text speaker does not match {source_id}")
                seen.add(source_id)
                _required_integer(row, "Valid segments", row_number)
                _required_integer(row, "RockSteady terms", row_number)
                constructs: dict[str, float | None] = {}
                for construct in TEXT_CONSTRUCTS:
                    if construct == "Text Valence":
                        continue
                    aliases = _SENTIMENT_ALIASES.get(construct, (construct,))
                    source_column = next(alias for alias in aliases if alias in reader.fieldnames)
                    constructs[construct] = _construct_value(row, source_column, construct, row_number)
                constructs["Text Valence"] = _text_valence(
                    constructs["Positive Sentiment"], constructs["Negative Sentiment"]
                )
                summaries.append(
                    TextConstructSummary(
                        speaker_id=source_id,
                        display_name=source.title,
                        country=str(source.user_metadata.get("Country", row.get("Country", ""))),
                        constructs=constructs,
                        source_path=verified_summary_path,
                        grain="source",
                        source_ids=(source_id,),
                    )
                )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise TextResultsError(f"Could not read native Text summary: {summary_path}") from exc
    if tuple(item.source_ids[0] for item in summaries) != tuple(declared_ids):
        raise TextResultsError("Native Text summary SourceIDs do not match the pair manifest in order")
    return TextResultsDiscovery(verified_summary_path, tuple(summaries), "source")


def _verify_bound_artifact(root: Path, contract: Mapping[str, object], path_key: str, hash_key: str) -> Path:
    path, _ = _verify_bound_artifact_snapshot(root, contract, path_key, hash_key)
    return path


def _verify_bound_artifact_snapshot(
    root: Path,
    contract: Mapping[str, object],
    path_key: str,
    hash_key: str,
) -> tuple[Path, bytes]:
    label = path_key.replace("_", " ")
    relative = Path(str(contract.get(path_key) or ""))
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root.resolve()):
        raise TextResultsError(f"Native Text {label} path is unsafe")
    expected = str(contract.get(hash_key) or "").casefold()
    try:
        snapshot = path.read_bytes()
    except OSError as exc:
        raise TextResultsError(f"Native Text {label} hash does not match its manifest") from exc
    if len(expected) != 64 or hashlib.sha256(snapshot).hexdigest() != expected:
        raise TextResultsError(f"Native Text {label} hash does not match its manifest")
    return path, snapshot


def _bound_source_contexts(
    binding: Mapping[str, object],
    declared_ids: list[str],
) -> list[Mapping[str, object]]:
    records = binding.get("source_contexts")
    if not isinstance(records, list):
        raise ValueError("Native Text source binding has no context inventory")
    contexts: list[Mapping[str, object]] = []
    context_ids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Native Text source context record must be an object")
        source_id = str(record.get("source_id") or "")
        context = record.get("context")
        expected = str(record.get("sha256") or "").casefold()
        if not isinstance(context, Mapping) or str(context.get("source_id") or "") != source_id:
            raise ValueError(f"Native Text source context identity is invalid for {source_id or '<blank>'}")
        encoded = json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(expected) != 64 or hashlib.sha256(encoded).hexdigest() != expected:
            raise ValueError(f"Native Text source context hash is invalid for {source_id or '<blank>'}")
        context_ids.append(source_id)
        contexts.append(context)
    if context_ids != declared_ids:
        raise ValueError("Native Text source context inventory does not match SourceIDs in order")
    return contexts


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TextResultsError(f"Cannot read {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise TextResultsError(f"{label} must be a JSON object")
    return payload


def _text_valence(positive: float | None, negative: float | None) -> float | None:
    if positive is None or negative is None or positive + negative == 0:
        return None
    return (positive - negative) / (positive + negative)
