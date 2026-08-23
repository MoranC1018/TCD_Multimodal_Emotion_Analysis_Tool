"""
Whisper Transcription Script (openai-whisper version)
======================================================

Transcribes a single video/audio file, or an entire folder tree of videos,
producing JSON files with segment-level transcripts and timestamps.

When the input is a folder the output mirrors the same directory structure.

Usage:
    # From the repository root, install the complete matched environment:
    powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
    # NVIDIA alternative:
    powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -TorchRuntime cu128

    # Single file:
    python -m processing.text_analysis.transcribe.transcribe "Videos/clip.mp4"

    # Whole folder (output mirrors input tree under output/):
    python -m processing.text_analysis.transcribe.transcribe "Path/To/Videos" --output-dir output

    # From a procurement run folder (auto-finds stitched/full videos, names by title):
    python -m processing.text_analysis.transcribe.transcribe --from-procurement procurement/output/<run> --task bilingual

    # With options:
    python -m processing.text_analysis.transcribe.transcribe "Path/To/Videos" --language fr --task bilingual

    # Skip files that already have a JSON:
    python -m processing.text_analysis.transcribe.transcribe "Path/To/Videos" --skip-existing

Output (folder mode):
    output/
      subfolder_a/
        clip1.json
        clip2.json
      subfolder_b/
        clip3.json

Author: Jiaming Liu
"""

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from processing.ffmpeg_runtime import configure_ffmpeg_shared_libraries
from processing.io_utils import (
    atomic_write_json,
    exclusive_process_lock,
    lexical_absolute_path,
)
from processing.catalog_context import catalog_text_language, discover_catalog_jobs
from processing.text_analysis.filesystem import assert_safe_output_target
from processing.text_analysis.contracts import (
    TEXT_MEDIA_EXTENSIONS,
    TEXT_SCHEMA_VERSION,
    canonical_video_relative,
    file_sha256,
    inventory_digest,
    source_fingerprint,
    validate_canonical_relative,
    validate_text_identity,
)
from processing.text_analysis.transcribe.provenance import (
    build_output_provenance,
    collect_whisper_execution_identity,
    whisper_decode_options,
    whisper_provenance_is_complete,
    whisper_provenance_matches,
)
from processing.text_analysis.transcribe.integrity import (
    transcript_segments_are_valid,
    validate_transcription_artifact_set,
)

VIDEO_EXTENSIONS = TEXT_MEDIA_EXTENSIONS

TRANSCRIPTION_MANIFEST = Path("_manifests") / "transcription_run_manifest.json"


@dataclass(frozen=True)
class TranscriptionJob:
    source: Path
    output_stem: Path
    source_relative: str
    source_id: str = ""
    requested_language: str = ""
    catalog_binding: dict[str, object] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        return self.output_stem.as_posix()

    @property
    def relative_json(self) -> Path:
        return self.output_stem.with_suffix(".json")

def _resolve_device(device):
    import torch

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        print("WARNING: CUDA requested but not available. Falling back to CPU.",
              file=sys.stderr)
        device = "cpu"
    return device


def _load_whisper_model(model_name: str, device: str):
    """Import Whisper only when a transcription pass actually needs a model."""

    import whisper

    return whisper.load_model(model_name, device=device)


def _overlap(s1, e1, s2, e2):
    return max(0.0, min(e1, e2) - max(s1, s2))


def _validate_alignment_segments(segments, label):
    if not segments:
        raise ValueError(f"Cannot align bilingual transcription: {label} has no segments.")
    previous_start = -1.0
    for index, segment in enumerate(segments):
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {label} segment timing at index {index}: {segment!r}") from exc
        if start < 0 or end <= start or start < previous_start:
            raise ValueError(f"Invalid or unsorted {label} segment timing at index {index}: {start}-{end}")
        previous_start = start


def _best_overlap_index(segment, candidates):
    overlaps = [
        _overlap(segment["start"], segment["end"], candidate["start"], candidate["end"])
        for candidate in candidates
    ]
    best_index = max(range(len(candidates)), key=lambda index: overlaps[index])
    return best_index, overlaps[best_index]


def _alignment_components(segs_original, segs_en):
    """Return connected time-match groups without reusing either side's text."""
    node_count = len(segs_original) + len(segs_en)
    adjacency = [set() for _ in range(node_count)]

    for original_index, segment in enumerate(segs_original):
        english_index, overlap = _best_overlap_index(segment, segs_en)
        if overlap <= 0:
            raise ValueError(
                f"No English time overlap for original segment {original_index + 1} "
                f"({segment['start']}-{segment['end']}s)."
            )
        english_node = len(segs_original) + english_index
        adjacency[original_index].add(english_node)
        adjacency[english_node].add(original_index)

    for english_index, segment in enumerate(segs_en):
        original_index, overlap = _best_overlap_index(segment, segs_original)
        if overlap <= 0:
            raise ValueError(
                f"No original-language time overlap for English segment {english_index + 1} "
                f"({segment['start']}-{segment['end']}s)."
            )
        english_node = len(segs_original) + english_index
        adjacency[english_node].add(original_index)
        adjacency[original_index].add(english_node)

    components = []
    visited = set()
    for node in range(node_count):
        if node in visited:
            continue
        stack = [node]
        original_indexes = []
        english_indexes = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            if current < len(segs_original):
                original_indexes.append(current)
            else:
                english_indexes.append(current - len(segs_original))
            stack.extend(adjacency[current] - visited)
        components.append((sorted(original_indexes), sorted(english_indexes)))
    return sorted(components, key=lambda component: component[0][0])


def _align_segments(segs_original, segs_en, original_language="original", min_overlap_ratio=0.25):
    """Merge two independently segmented Whisper passes using their timestamps."""
    _validate_alignment_segments(segs_original, "original-language pass")
    _validate_alignment_segments(segs_en, "English pass")
    components = _alignment_components(segs_original, segs_en)

    segments = []
    previous_english_index = -1
    for output_index, (original_indexes, english_indexes) in enumerate(components):
        if english_indexes[0] <= previous_english_index:
            raise ValueError("Bilingual time alignment is not monotonic across the two Whisper passes.")
        previous_english_index = english_indexes[-1]
        original_group = [segs_original[index] for index in original_indexes]
        english_group = [segs_en[index] for index in english_indexes]
        original_start = min(float(segment["start"]) for segment in original_group)
        original_end = max(float(segment["end"]) for segment in original_group)
        english_start = min(float(segment["start"]) for segment in english_group)
        english_end = max(float(segment["end"]) for segment in english_group)
        intersection = _overlap(original_start, original_end, english_start, english_end)
        union = max(original_end, english_end) - min(original_start, english_start)
        overlap_ratio = intersection / union if union > 0 else 0.0
        if overlap_ratio < min_overlap_ratio:
            raise ValueError(
                f"Low bilingual alignment overlap for output segment {output_index + 1}: "
                f"ratio={overlap_ratio:.3f}, original={original_start}-{original_end}s, "
                f"English={english_start}-{english_end}s."
            )

        text_original = " ".join(segment.get("text", "").strip() for segment in original_group).strip()
        text_en = " ".join(segment.get("text", "").strip() for segment in english_group).strip()
        if not text_original or not text_en:
            raise ValueError(f"Empty bilingual text after alignment for output segment {output_index + 1}.")
        segment = {
            "id": output_index,
            "start": round(original_start, 2),
            "end": round(original_end, 2),
            "text_original": text_original,
            "text_en": text_en,
            "alignment_original_segments": len(original_group),
            "alignment_en_segments": len(english_group),
            "alignment_overlap_ratio": round(overlap_ratio, 4),
            "source_original_segment_indexes": original_indexes,
            "source_en_segment_indexes": english_indexes,
            "source_original_segment_ids": [segs_original[index].get("id", index) for index in original_indexes],
            "source_en_segment_ids": [segs_en[index].get("id", index) for index in english_indexes],
        }
        segments.append(segment)
        print(f"  [{original_start:6.1f}s] {original_language.upper()}: {text_original[:60]}")
        print(f"           EN: {text_en[:60]}  (overlap={overlap_ratio:.1%})")
    return segments


def _plain_segments(segments):
    output = []
    for index, segment in enumerate(segments):
        plain_segment = {
            "id": segment.get("id", index),
            "start": round(float(segment["start"]), 2),
            "end": round(float(segment["end"]), 2),
            "text": segment.get("text", "").strip(),
        }
        output.append(plain_segment)
    ids = [segment["id"] for segment in output]
    try:
        ids_are_unique = len(ids) == len(set(ids))
    except TypeError as exc:
        raise ValueError("Whisper segment IDs must be scalar values.") from exc
    if not ids_are_unique:
        raise ValueError("Whisper returned duplicate segment IDs.")
    return output


def _segments_sha256(segments):
    canonical = json.dumps(segments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_content_sha256(video_path: Path) -> str:
    """Hash media content without trusting mutable size/mtime cache keys."""

    return file_sha256(Path(video_path).resolve())


def _apply_whisper_provenance(output, *, model_name, provenance):
    """Attach validated current-schema provenance to a transcript output."""

    if not whisper_provenance_is_complete(provenance):
        raise ValueError("Cannot write a transcript with incomplete Whisper provenance.")
    output["model"] = model_name
    output["whisper_provenance"] = provenance
    return output


def _resolve_output_provenance(
    provenance_by_kind,
    *,
    model_name,
    requested_task,
    device,
    requested_language,
):
    """Use a run-level identity when supplied, otherwise collect it once locally."""

    if provenance_by_kind is None:
        provenance_by_kind = build_output_provenance(
            collect_whisper_execution_identity(model_name),
            requested_task=requested_task,
            device=device,
            requested_language=requested_language,
        )
    required = (
        {"original", "eng", "bilingual"}
        if requested_task == "bilingual"
        else {requested_task}
    )
    if set(provenance_by_kind) != required or any(
        not whisper_provenance_is_complete(provenance_by_kind[kind])
        for kind in required
    ):
        raise ValueError(
            f"Incomplete Whisper provenance map for task {requested_task!r}."
        )
    return provenance_by_kind


def _base_output(
    video_path,
    language,
    task,
    device,
    segments,
    *,
    source_sha256_value=None,
    source_id="",
    catalog_binding=None,
):
    source = Path(video_path)
    output = {
        "schema_version": TEXT_SCHEMA_VERSION,
        "source": str(source.resolve()),
        "source_id": str(source_id or ""),
        "catalog_binding": dict(catalog_binding or {}),
        "language": language,
        "task": task,
        "duration_sec": segments[-1]["end"] if segments else 0.0,
        "model": None,
        "device": device,
        "segments": segments,
    }
    if source.is_file():
        output["source_fingerprint"] = source_fingerprint(source)
        output["source_sha256"] = source_sha256_value or _source_content_sha256(source)
    return output


def _build_bilingual_outputs(
    video_path,
    device,
    detected_lang,
    result_original,
    result_en,
    *,
    source_sha256_value=None,
    source_id="",
    catalog_binding=None,
):
    """Build usable original/English files plus a time-aligned audit file."""
    original_segments = _plain_segments(result_original["segments"])
    english_segments = _plain_segments(result_en["segments"])
    aligned_segments = _align_segments(
        original_segments, english_segments, detected_lang
    )
    used_original = [item for segment in aligned_segments for item in segment["source_original_segment_indexes"]]
    used_english = [item for segment in aligned_segments for item in segment["source_en_segment_indexes"]]
    expected_original = list(range(len(original_segments)))
    expected_english = list(range(len(english_segments)))
    if sorted(used_original) != sorted(expected_original) or len(used_original) != len(set(used_original)):
        raise ValueError("Bilingual alignment duplicated or omitted original-language segments.")
    if sorted(used_english) != sorted(expected_english) or len(used_english) != len(set(used_english)):
        raise ValueError("Bilingual alignment duplicated or omitted English segments.")

    original = _base_output(
        video_path, detected_lang, "transcribe", device, original_segments,
        source_sha256_value=source_sha256_value, source_id=source_id,
        catalog_binding=catalog_binding,
    )
    english = _base_output(
        video_path, "en", "translate", device, english_segments,
        source_sha256_value=source_sha256_value, source_id=source_id,
        catalog_binding=catalog_binding,
    )
    bilingual = _base_output(
        video_path, detected_lang, "bilingual", device, aligned_segments,
        source_sha256_value=source_sha256_value, source_id=source_id,
        catalog_binding=catalog_binding,
    )
    ratios = [segment["alignment_overlap_ratio"] for segment in aligned_segments]
    audit = {
        "method": "mutual_best_time_overlap_components",
        "original_input_segments": len(original_segments),
        "english_input_segments": len(english_segments),
        "aligned_output_segments": len(aligned_segments),
        "original_segments_used_once": True,
        "english_segments_used_once": True,
        "minimum_overlap_ratio": min(ratios),
        "mean_overlap_ratio": round(sum(ratios) / len(ratios), 4),
        "original_segments_sha256": _segments_sha256(original_segments),
        "english_segments_sha256": _segments_sha256(english_segments),
    }
    original["bilingual_companion"] = {"kind": "original", **audit}
    english["bilingual_companion"] = {"kind": "eng", **audit}
    bilingual["bilingual_alignment"] = audit
    return {"original": original, "eng": english, "bilingual": bilingual}


def transcribe_file(
    video_path,
    model,
    device,
    language=None,
    task="transcribe",
    *,
    model_name,
    provenance_by_kind=None,
    source_sha256_value=None,
    source_id="",
    catalog_binding=None,
):
    """Run Whisper on one video/audio file using a pre-loaded model."""
    provenance_by_kind = _resolve_output_provenance(
        provenance_by_kind,
        model_name=model_name,
        requested_task=task,
        device=device,
        requested_language=language,
    )

    if task == "bilingual":
        print(f"  Pass 1/2 - transcribing original: {video_path.name} ...")
        result_fr = model.transcribe(
            str(video_path),
            **whisper_decode_options(
                device=device, requested_language=language, task="transcribe"
            ),
        )
        print(f"  Pass 2/2 - translating to English: {video_path.name} ...")
        result_en = model.transcribe(
            str(video_path),
            **whisper_decode_options(
                device=device, requested_language=language, task="translate"
            ),
        )
        detected_lang = result_fr.get("language", "unknown")
        print(f"  Detected language: {detected_lang}")
        outputs = _build_bilingual_outputs(
            video_path,
            device,
            detected_lang,
            result_fr,
            result_en,
            source_sha256_value=source_sha256_value,
            source_id=source_id,
            catalog_binding=catalog_binding,
        )
        for kind, output in outputs.items():
            _apply_whisper_provenance(
                output,
                model_name=model_name,
                provenance=provenance_by_kind[kind],
            )
        return outputs
    else:
        if task == "translate":
            print(f"  Transcribing + translating to English: {video_path.name} ...")
        else:
            print(f"  Transcribing: {video_path.name} ...")
        result = model.transcribe(
            str(video_path),
            **whisper_decode_options(
                device=device, requested_language=language, task=task
            ),
        )
        detected_lang = result.get("language", "unknown")
        print(f"  Detected language: {detected_lang}")
        segments = _plain_segments(result["segments"])
        for seg in result["segments"]:
            print(f"  [{seg['start']:6.1f}s] {seg['text'].strip()[:80]}")

    duration = segments[-1]["end"] if segments else 0.0

    output = _base_output(
        video_path,
        detected_lang,
        task,
        device,
        segments,
        source_sha256_value=source_sha256_value,
        source_id=source_id,
        catalog_binding=catalog_binding,
    )
    return _apply_whisper_provenance(
        output,
        model_name=model_name,
        provenance=provenance_by_kind[task],
    )


def _output_paths(output_root, relative_json_path, task):
    if task == "bilingual":
        return {kind: output_root / kind / relative_json_path for kind in ("original", "eng", "bilingual")}
    return {task: output_root / relative_json_path}


def _write_json_set(outputs, paths):
    """Stage all JSON files before publishing the complete output set."""
    staged = []
    try:
        for kind, data in outputs.items():
            path = paths[kind]
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp",
            )
            with handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
            staged.append((Path(handle.name), path))
        for temporary, destination in staged:
            temporary.replace(destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def _read_saved_whisper_pass(path, expected_task):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot reuse saved Whisper output {path}: {exc}") from exc
    if data.get("task") != expected_task or not isinstance(data.get("segments"), list):
        raise ValueError(
            f"Cannot reuse saved Whisper output {path}: expected task={expected_task!r} "
            "with a segment list."
        )
    return data


def _saved_pass_is_reusable(
    path,
    expected_task,
    model_name,
    video_path,
    *,
    trust_legacy=False,
    source_sha256_value=None,
    expected_provenance=None,
    expected_source_id="",
    expected_catalog_binding=None,
):
    """Validate a saved pass before allowing expensive Whisper work to skip.

    Source size, mtime, and absolute path are retained as diagnostics.  Content
    SHA-256 is the identity: touching or moving unchanged media must not force a
    new transcription, while a same-size replacement must never be reused.
    """

    try:
        data = _read_saved_whisper_pass(path, expected_task)
    except ValueError:
        return False
    if not trust_legacy and data.get("schema_version") != TEXT_SCHEMA_VERSION:
        return False
    if not trust_legacy and str(data.get("source_id") or "") != str(expected_source_id or ""):
        return False
    if not trust_legacy and data.get("catalog_binding", {}) != dict(expected_catalog_binding or {}):
        return False
    if not _saved_segments_are_valid(data, expected_task):
        return False
    saved_model = data.get("model")
    if saved_model != model_name and not (trust_legacy and saved_model is None):
        return False
    saved_source = data.get("source")
    if not isinstance(saved_source, str):
        if trust_legacy and saved_source is None:
            saved_source = ""
        else:
            return False
    if not saved_source and not trust_legacy:
        return False

    saved_provenance = data.get("whisper_provenance")
    if whisper_provenance_is_complete(saved_provenance):
        if not whisper_provenance_matches(saved_provenance, expected_provenance):
            return False
    elif not trust_legacy:
        return False

    source = Path(video_path)
    if not source.is_file():
        return False
    saved_fingerprint = data.get("source_fingerprint")
    if not isinstance(saved_fingerprint, dict):
        if not trust_legacy:
            return False
    saved_sha256 = data.get("source_sha256")
    if isinstance(saved_sha256, str) and len(saved_sha256) == 64:
        current_sha256 = source_sha256_value or _source_content_sha256(source)
        return saved_sha256.casefold() == current_sha256.casefold()

    if not trust_legacy:
        return False
    # Explicit legacy trust cannot reconstruct a missing content hash.  Use the
    # strongest old metadata available, but never weaken a complete modern
    # provenance mismatch above.
    if isinstance(saved_fingerprint, dict):
        return saved_fingerprint == source_fingerprint(source)
    return bool(saved_source and Path(saved_source).resolve() == source.resolve())


def _saved_segments_are_valid(data, expected_task):
    return transcript_segments_are_valid(data, expected_task)


def transcription_artifact_set_is_reusable(
    paths,
    *,
    model_name,
    video_path,
    provenance_by_kind,
    source_sha256_value=None,
    trust_legacy=False,
    expected_source_id="",
    expected_catalog_binding=None,
):
    """Return whether an exact output set is safe to reuse as one unit.

    This public predicate is shared with the parent Text pipeline.  Current
    artifacts are validated together so a bilingual job cannot be skipped when
    one companion is missing or carries different model/source/provenance data.
    """

    source_hash = source_sha256_value or _source_content_sha256(Path(video_path))
    if not trust_legacy:
        try:
            validate_transcription_artifact_set(
                paths,
                expected_model=model_name,
                expected_source_sha256=source_hash,
                expected_provenance_by_kind=provenance_by_kind,
            )
        except (OSError, ValueError):
            return False
        try:
            return all(
                str(_read_saved_whisper_pass(path, _expected_task(kind)).get("source_id") or "")
                == str(expected_source_id or "")
                and _read_saved_whisper_pass(path, _expected_task(kind)).get("catalog_binding", {})
                == dict(expected_catalog_binding or {})
                for kind, path in paths.items()
            )
        except ValueError:
            return False
    return all(
        _saved_pass_is_reusable(
            path,
            _expected_task(kind),
            model_name,
            video_path,
            trust_legacy=True,
            source_sha256_value=source_hash,
            expected_provenance=provenance_by_kind[kind],
            expected_source_id=expected_source_id,
            expected_catalog_binding=expected_catalog_binding,
        )
        for kind, path in paths.items()
    )


def _expected_task(output_kind):
    return {"original": "transcribe", "eng": "translate", "bilingual": "bilingual"}.get(
        output_kind, output_kind
    )


def transcribe_bilingual_to_paths(
    video_path,
    model,
    device,
    paths,
    *,
    model_name,
    language=None,
    reuse_existing=False,
    trust_legacy=False,
    source_sha256_value=None,
    provenance_by_kind=None,
    source_id="",
    catalog_binding=None,
):
    """Persist each expensive Whisper pass before attempting bilingual alignment."""
    provenance_by_kind = _resolve_output_provenance(
        provenance_by_kind,
        model_name=model_name,
        requested_task="bilingual",
        device=device,
        requested_language=language,
    )

    if reuse_existing and _saved_pass_is_reusable(
        paths["original"], "transcribe", model_name, video_path,
        trust_legacy=trust_legacy, source_sha256_value=source_sha256_value,
        expected_provenance=provenance_by_kind["original"],
        expected_source_id=source_id,
        expected_catalog_binding=catalog_binding,
    ):
        original = _read_saved_whisper_pass(paths["original"], "transcribe")
        print(f"  REUSE original: {paths['original']}")
    else:
        if model is None:
            raise RuntimeError("Whisper model is required to generate the missing original pass.")
        print(f"  Pass 1/2 - transcribing original: {video_path.name} ...")
        raw_original = model.transcribe(
            str(video_path),
            **whisper_decode_options(
                device=device, requested_language=language, task="transcribe"
            ),
        )
        detected_language = raw_original.get("language", "unknown")
        original = _base_output(
            video_path, detected_language, "transcribe", device,
            _plain_segments(raw_original["segments"]),
            source_sha256_value=source_sha256_value,
            source_id=source_id,
            catalog_binding=catalog_binding,
        )
        _apply_whisper_provenance(
            original,
            model_name=model_name,
            provenance=provenance_by_kind["original"],
        )
        _write_json_set({"original": original}, {"original": paths["original"]})
        print(f"  SAVED original: {paths['original']} ({len(original['segments'])} segments)")

    if reuse_existing and _saved_pass_is_reusable(
        paths["eng"], "translate", model_name, video_path,
        trust_legacy=trust_legacy, source_sha256_value=source_sha256_value,
        expected_provenance=provenance_by_kind["eng"],
        expected_source_id=source_id,
        expected_catalog_binding=catalog_binding,
    ):
        english = _read_saved_whisper_pass(paths["eng"], "translate")
        print(f"  REUSE eng: {paths['eng']}")
    else:
        if model is None:
            raise RuntimeError("Whisper model is required to generate the missing English pass.")
        print(f"  Pass 2/2 - translating to English: {video_path.name} ...")
        raw_english = model.transcribe(
            str(video_path),
            **whisper_decode_options(
                device=device, requested_language=language, task="translate"
            ),
        )
        english = _base_output(
            video_path, "en", "translate", device,
            _plain_segments(raw_english["segments"]),
            source_sha256_value=source_sha256_value,
            source_id=source_id,
            catalog_binding=catalog_binding,
        )
        _apply_whisper_provenance(
            english,
            model_name=model_name,
            provenance=provenance_by_kind["eng"],
        )
        _write_json_set({"eng": english}, {"eng": paths["eng"]})
        print(f"  SAVED eng: {paths['eng']} ({len(english['segments'])} segments)")

    detected_language = str(original.get("language") or "unknown")
    outputs = _build_bilingual_outputs(
        video_path,
        device,
        detected_language,
        original,
        english,
        source_sha256_value=source_sha256_value,
        source_id=source_id,
        catalog_binding=catalog_binding,
    )
    for kind, data in outputs.items():
        _apply_whisper_provenance(
            data,
            model_name=model_name,
            provenance=provenance_by_kind[kind],
        )
    _write_json_set(outputs, paths)
    return outputs


def _procurement_identity(speaker_dir: Path, video_dir: Path) -> Path:
    """Return the real ``Speaker/Video`` identity produced by procurement."""

    video_name = video_dir.name
    if video_name.endswith("_full_video"):
        video_name = video_name[: -len("_full_video")]
    return validate_text_identity(Path(speaker_dir.name) / video_name)


def collect_videos(root: Path):
    """Return all video/audio files under root, sorted."""
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )


def collect_from_procurement(downloads_root: Path) -> list[tuple[Path, Path]]:
    """Find transcribable videos from a procurement downloads folder.

    Returns ``(media_path, output_stem)`` pairs where ``output_stem`` is the
    actual ``Speaker/Video`` path already present below ``downloads``.  No
    country or comparison group is inferred during processing.

    Looks for:
      - stitched_imotions.mp4  (standard-license 10% sample)
      - *_full_video/*.mp4     (CC full-video download)
    """
    results: list[tuple[Path, Path]] = []
    for speaker_dir in sorted(downloads_root.iterdir()):
        if not speaker_dir.is_dir():
            continue
        for video_dir in sorted(speaker_dir.iterdir()):
            if not video_dir.is_dir():
                continue
            # Standard license: stitched_imotions.mp4
            stitched = video_dir / "stitched_imotions.mp4"
            if stitched.exists():
                results.append((stitched, _procurement_identity(speaker_dir, video_dir)))
                continue
            # CC full-video: one supported media file directly inside
            # *_full_video.  Reject ambiguity rather than silently choosing a
            # different file on another machine.
            if video_dir.name.endswith("_full_video"):
                media = sorted(
                    (
                        path
                        for path in video_dir.iterdir()
                        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
                    ),
                    key=lambda path: path.name.casefold(),
                )
                if len(media) > 1:
                    raise ValueError(
                        f"Multiple full-video media files found in {video_dir}: "
                        f"{', '.join(path.name for path in media)}"
                    )
                if media:
                    results.append((media[0], _procurement_identity(speaker_dir, video_dir)))
    return results


def _build_transcription_jobs(
    *,
    input_value: str | None,
    procurement_run: Path | None,
    canonical_layout: bool,
    speaker_parent_layout: bool = False,
    catalog_root: Path | None = None,
    selected_source_ids: list[str] | None = None,
    expected_catalog_sha256: str = "",
    explicit_language: str = "",
) -> tuple[Path, Path, list[TranscriptionJob]]:
    """Return invocation input, source root, and collision-free output jobs."""

    if catalog_root is not None:
        discovery = discover_catalog_jobs(
            catalog_root,
            selected_source_ids=selected_source_ids,
            expected_catalog_sha256=expected_catalog_sha256,
        )
        if discovery is None:
            raise ValueError(f"No procurement catalog sidecars found under {catalog_root}")
        invocation_input = discovery.run_root
        source_root = discovery.run_root
        jobs = [
            TranscriptionJob(
                source=job.media_path,
                output_stem=validate_text_identity(job.relative_output),
                source_relative=job.media_path.relative_to(discovery.run_root).as_posix(),
                source_id=job.source_id,
                requested_language=catalog_text_language(job, explicit_language),
                catalog_binding=_catalog_binding(job),
            )
            for job in discovery.jobs
        ]
    elif procurement_run is not None:
        invocation_input = procurement_run.resolve()
        source_root = (
            invocation_input
            if invocation_input.name.casefold() == "downloads"
            else invocation_input / "downloads"
        )
        if not source_root.is_dir():
            raise FileNotFoundError(f"No downloads/ folder found under {invocation_input}")
        pairs = collect_from_procurement(source_root)
        jobs = [
            TranscriptionJob(
                source.resolve(),
                validate_text_identity(stem),
                source.resolve().relative_to(source_root).as_posix(),
            )
            for source, stem in pairs
        ]
    else:
        if input_value is None:
            raise ValueError("Provide either 'input' or --from-procurement")
        invocation_input = Path(input_value).resolve()
        if invocation_input.is_file():
            if invocation_input.suffix.lower() not in VIDEO_EXTENSIONS:
                raise ValueError(f"Unsupported file type: {invocation_input.suffix}")
            source_root = invocation_input.parent
            videos = [invocation_input]
            single_file = True
        elif invocation_input.is_dir():
            source_root = invocation_input
            videos = collect_videos(invocation_input)
            single_file = False
        else:
            raise FileNotFoundError(f"Input path not found: {invocation_input}")
        if not videos:
            raise ValueError(f"No video/audio files found under {invocation_input}")

        jobs = []
        for video in videos:
            source_relative = video.name if single_file else video.relative_to(source_root).as_posix()
            if speaker_parent_layout:
                try:
                    output_stem = canonical_video_relative(video.stem)
                except ValueError:
                    speaker_name = video.parent.name.strip() or "Ungrouped"
                    output_stem = validate_text_identity(Path(speaker_name) / video.stem)
            elif canonical_layout:
                output_stem = canonical_video_relative(video.stem)
            elif single_file:
                try:
                    output_stem = canonical_video_relative(video.stem)
                except ValueError:
                    output_stem = Path(video.stem)
            else:
                relative_stem = video.relative_to(source_root).with_suffix("")
                if len(relative_stem.parts) == 3:
                    try:
                        output_stem = validate_canonical_relative(relative_stem)
                    except ValueError:
                        output_stem = relative_stem
                else:
                    output_stem = relative_stem
            jobs.append(
                TranscriptionJob(
                    video.resolve(),
                    output_stem,
                    source_relative,
                    requested_language=explicit_language,
                )
            )

    if not jobs:
        raise ValueError(f"No transcribable videos found under {source_root}")
    destinations: dict[str, Path] = {}
    for job in jobs:
        key = job.relative_json.as_posix().casefold()
        previous = destinations.get(key)
        if previous is not None:
            raise ValueError(
                f"Multiple media files map to the same transcript {job.relative_json}: "
                f"{previous} and {job.source}"
            )
        destinations[key] = job.source
    return invocation_input, source_root.resolve(), jobs


def _catalog_binding(job) -> dict[str, object]:
    def plain(value):
        if isinstance(value, dict) or hasattr(value, "items"):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [plain(item) for item in value]
        return value

    context = plain(job.source_context)
    return {
        "source_id": job.source_id,
        "speaker": job.speaker,
        "speaker_display": job.speaker_display,
        "catalog_sha256": job.catalog_sha256,
        "user_metadata": plain(job.user_metadata),
        "system_metadata": plain(job.system_metadata),
        "output_mapping": context.get("output_mapping", {}),
        "source_context": context,
    }


def _transcription_record(
    job: TranscriptionJob,
    paths: dict[str, Path],
    output_root: Path,
    *,
    status: str,
    segment_count: int | None = None,
    error: str | None = None,
    source_sha256_value: str | None = None,
    provenance_by_kind: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "source_path": str(job.source),
        "source_relative": job.source_relative,
        "source_id": job.source_id,
        "requested_language": job.requested_language,
        "catalog_binding": job.catalog_binding,
        "whisper_provenance": provenance_by_kind or {},
        "video_stem": job.output_stem.name,
        "identity": job.identity,
        "source_fingerprint": source_fingerprint(job.source),
        "source_sha256": source_sha256_value or _source_content_sha256(job.source),
        "status": status,
        "artifacts": {},
    }
    for kind, path in paths.items():
        artifact: dict[str, object] = {
            "path": path.resolve().relative_to(output_root.resolve()).as_posix()
        }
        if status in {"completed", "skipped"} and path.is_file():
            artifact["sha256"] = file_sha256(path)
        record["artifacts"][kind] = artifact
    if segment_count is not None:
        record["segment_count"] = segment_count
    if error is not None:
        record["error"] = error
    return record


def _write_transcription_manifest(
    path: Path,
    *,
    status: str,
    started_at: str,
    invocation_input: Path,
    source_root: Path,
    output_root: Path,
    task: str,
    model: str,
    device: str,
    language: str | None,
    provenance_by_kind: dict[str, dict[str, object]],
    records: list[dict[str, object]],
) -> None:
    summary = {
        "total": len(records),
        "completed": sum(record.get("status") == "completed" for record in records),
        "skipped": sum(record.get("status") == "skipped" for record in records),
        "failed": sum(record.get("status") == "failed" for record in records),
        "planned": sum(record.get("status") == "planned" for record in records),
    }
    atomic_write_json(
        path,
        {
            "schema_version": TEXT_SCHEMA_VERSION,
            "kind": "whisper-transcription-batch",
            "status": status,
            "started_at": started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "input_path": str(invocation_input),
            "source_root": str(source_root),
            "output_root": str(output_root),
            "config": {"task": task, "model": model, "device": device, "language": language},
            "whisper_provenance": provenance_by_kind,
            "inventory_sha256": inventory_digest(records),
            "summary": summary,
            "videos": records,
        },
    )


def _main_unlocked(argv: list[str] | None = None) -> int:
    # WinGet updates do not alter the PATH inherited by an already-open shell.
    # Configure the shared runtime here so Whisper's FFmpeg child is reliable
    # immediately after scripts/setup.ps1 returns.
    configure_ffmpeg_shared_libraries()
    parser = argparse.ArgumentParser(description="Batch-transcribe video/audio with Whisper")
    parser.add_argument("input", nargs="?", default=None,
                        help="Path to a video/audio file OR a folder")
    parser.add_argument("--from-procurement", type=Path, default=None, metavar="RUN_FOLDER",
                        help="Procurement run or downloads folder "
                             "(e.g. procurement/output/<run>). "
                             "Automatically finds stitched_imotions.mp4 / full-video files "
                             "and preserves their Speaker/Video folder identity.")
    parser.add_argument(
        "--catalog-root",
        type=Path,
        default=None,
        help="Procurement run root containing the exact source sidecar pair.",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        default=None,
        help="Authorized catalog SourceID. Repeat for multiple rows.",
    )
    parser.add_argument("--catalog-sha256", default="")
    parser.add_argument("--model", default="small",
                        choices=["tiny", "base", "small", "medium",
                                 "large", "large-v2", "large-v3"],
                        help="Model size (default: small)")
    parser.add_argument("--language", default=None,
                        help="Language code (en/fr/pl/...). Auto-detected if omitted.")
    parser.add_argument("--device", default=None, choices=["cpu", "cuda"],
                        help="cpu or cuda. Default: auto-detect.")
    parser.add_argument("--task", default="transcribe",
                        choices=["transcribe", "translate", "bilingual"],
                        help="transcribe (default), translate to English, or bilingual.")
    parser.add_argument("--output-dir", default="output",
                        help="Root output folder (default: output/)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Reuse only complete, provenance-verified JSON outputs.")
    parser.add_argument(
        "--trust-legacy", action="store_true",
        help="Allow reuse of pre-v2 JSON without complete provenance (unsafe; off by default).",
    )
    identity_layout = parser.add_mutually_exclusive_group()
    identity_layout.add_argument(
        "--canonical-layout", action="store_true",
        help="Legacy/manual mode: require canonical video names and write "
             "Country/Speaker/Video.json.",
    )
    identity_layout.add_argument(
        "--speaker-parent-layout",
        action="store_true",
        help="General media mode: use each media file's immediate parent folder "
             "as Speaker and its filename stem as Video; canonical legacy names "
             "remain canonical.",
    )
    parser.add_argument("--batch-manifest", type=Path, help="Batch manifest path")
    args = parser.parse_args(argv)

    output_root = assert_safe_output_target(lexical_absolute_path(args.output_dir))
    try:
        invocation_input, source_root, jobs = _build_transcription_jobs(
            input_value=args.input,
            procurement_run=args.from_procurement,
            canonical_layout=args.canonical_layout,
            speaker_parent_layout=args.speaker_parent_layout,
            catalog_root=args.catalog_root,
            selected_source_ids=args.source_id,
            expected_catalog_sha256=args.catalog_sha256,
            explicit_language=str(args.language or ""),
        )
        output_root = assert_safe_output_target(output_root, invocation_input)
        device = _resolve_device(args.device)
        execution_identity = collect_whisper_execution_identity(args.model)
        provenance_by_kind = build_output_provenance(
            execution_identity,
            requested_task=args.task,
            device=device,
            requested_language=args.language,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    manifest_path = (
        args.batch_manifest.resolve()
        if args.batch_manifest is not None
        else output_root / TRANSCRIPTION_MANIFEST
    )
    started_at = datetime.now(timezone.utc).isoformat()
    path_sets = [_output_paths(output_root, job.relative_json, args.task) for job in jobs]
    source_hashes = [_source_content_sha256(job.source) for job in jobs]
    provenance_sets = [
        build_output_provenance(
            execution_identity,
            requested_task=args.task,
            device=device,
            requested_language=job.requested_language or args.language,
        )
        for job in jobs
    ]
    records = [
        _transcription_record(
            job,
            paths,
            output_root,
            status="planned",
            source_sha256_value=source_hash,
            provenance_by_kind=job_provenance,
        )
        for job, paths, source_hash, job_provenance in zip(
            jobs, path_sets, source_hashes, provenance_sets
        )
    ]
    complete: list[bool] = []
    for job, paths, source_hash, job_provenance in zip(
        jobs, path_sets, source_hashes, provenance_sets
    ):
        complete.append(
            bool(args.skip_existing)
            and transcription_artifact_set_is_reusable(
                paths,
                model_name=args.model,
                video_path=job.source,
                provenance_by_kind=job_provenance,
                source_sha256_value=source_hash,
                trust_legacy=args.trust_legacy,
                expected_source_id=job.source_id,
                expected_catalog_binding=job.catalog_binding,
            )
        )
    _write_transcription_manifest(
        manifest_path,
        status="running",
        started_at=started_at,
        invocation_input=invocation_input,
        source_root=source_root,
        output_root=output_root,
        task=args.task,
        model=args.model,
        device=device,
        language=args.language,
        provenance_by_kind=provenance_by_kind,
        records=records,
    )

    needs_model = False
    for job, paths, is_complete, source_hash, job_provenance in zip(
        jobs, path_sets, complete, source_hashes, provenance_sets
    ):
        if is_complete:
            continue
        if args.task != "bilingual" or not args.skip_existing:
            needs_model = True
            break
        original_ready = _saved_pass_is_reusable(
            paths["original"], "transcribe", args.model, job.source,
            trust_legacy=args.trust_legacy,
            source_sha256_value=source_hash,
            expected_provenance=job_provenance["original"],
            expected_source_id=job.source_id,
            expected_catalog_binding=job.catalog_binding,
        )
        english_ready = _saved_pass_is_reusable(
            paths["eng"], "translate", args.model, job.source,
            trust_legacy=args.trust_legacy,
            source_sha256_value=source_hash,
            expected_provenance=job_provenance["eng"],
            expected_source_id=job.source_id,
            expected_catalog_binding=job.catalog_binding,
        )
        if not original_ready or not english_ready:
            needs_model = True
            break

    model = None
    if needs_model:
        try:
            import torch
            print(f"\nLoading Whisper model '{args.model}' on {device} ...")
            if device == "cuda":
                print(f"  GPU: {torch.cuda.get_device_name(0)}")
            model = _load_whisper_model(args.model, device)
        except Exception as exc:
            for index, is_complete in enumerate(complete):
                if not is_complete:
                    records[index]["status"] = "failed"
                    records[index]["error"] = f"{type(exc).__name__}: {exc}"
            _write_transcription_manifest(
                manifest_path, status="failed", started_at=started_at,
                invocation_input=invocation_input, source_root=source_root,
                output_root=output_root, task=args.task, model=args.model,
                device=device, language=args.language, records=records,
                provenance_by_kind=provenance_by_kind,
            )
            print(f"ERROR: Whisper model could not be loaded: {exc}", file=sys.stderr)
            return 1
    elif any(not value for value in complete):
        print("\nSaved original and English passes are valid; retrying alignment without loading Whisper.")

    for index, (job, paths, is_complete, source_hash, job_provenance) in enumerate(
        zip(jobs, path_sets, complete, source_hashes, provenance_sets), start=1
    ):
        print(f"\n[{index}/{len(jobs)}] {job.identity}")
        record_index = index - 1
        if is_complete:
            representative = next(iter(paths.values()))
            saved = _read_saved_whisper_pass(representative, _expected_task(next(iter(paths))))
            records[record_index] = _transcription_record(
                job, paths, output_root, status="skipped", segment_count=len(saved["segments"]),
                source_sha256_value=source_hash,
                provenance_by_kind=job_provenance,
            )
            print(f"  SKIP (verified complete set): {', '.join(str(path) for path in paths.values())}")
        else:
            try:
                if args.task == "bilingual":
                    outputs = transcribe_bilingual_to_paths(
                        job.source,
                        model,
                        device,
                        paths,
                        model_name=args.model,
                        language=job.requested_language or args.language,
                        reuse_existing=args.skip_existing,
                        trust_legacy=args.trust_legacy,
                        source_sha256_value=source_hash,
                        provenance_by_kind=job_provenance,
                        source_id=job.source_id,
                        catalog_binding=job.catalog_binding,
                    )
                    segment_count = len(outputs["bilingual"]["segments"])
                else:
                    if model is None:
                        raise RuntimeError("Whisper model is required for this transcription pass")
                    result = transcribe_file(
                        job.source,
                        model,
                        device,
                        language=job.requested_language or args.language,
                        task=args.task,
                        model_name=args.model,
                        provenance_by_kind=job_provenance,
                        source_sha256_value=source_hash,
                        source_id=job.source_id,
                        catalog_binding=job.catalog_binding,
                    )
                    result["model"] = args.model
                    outputs = {args.task: result}
                    _write_json_set(outputs, paths)
                    segment_count = len(result["segments"])
                records[record_index] = _transcription_record(
                    job, paths, output_root, status="completed", segment_count=segment_count,
                    source_sha256_value=source_hash,
                    provenance_by_kind=job_provenance,
                )
                for kind, path in paths.items():
                    print(f"  -> {kind}: {path} ({len(outputs[kind]['segments'])} segments)")
            except Exception as exc:
                records[record_index] = _transcription_record(
                    job,
                    paths,
                    output_root,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    source_sha256_value=source_hash,
                    provenance_by_kind=job_provenance,
                )
                print(f"  ERROR: {exc}", file=sys.stderr)
        _write_transcription_manifest(
            manifest_path, status="running", started_at=started_at,
            invocation_input=invocation_input, source_root=source_root,
            output_root=output_root, task=args.task, model=args.model,
            device=device, language=args.language, records=records,
            provenance_by_kind=provenance_by_kind,
        )

    failed = sum(record["status"] == "failed" for record in records)
    final_status = "failed" if failed else "completed"
    _write_transcription_manifest(
        manifest_path, status=final_status, started_at=started_at,
        invocation_input=invocation_input, source_root=source_root,
        output_root=output_root, task=args.task, model=args.model,
        device=device, language=args.language, records=records,
        provenance_by_kind=provenance_by_kind,
    )
    succeeded = len(records) - failed
    print(f"\nDone. {succeeded}/{len(records)} video(s) completed or safely skipped.")
    if failed:
        print(f"Batch manifest: {manifest_path}", file=sys.stderr)
        return 1
    return 0


def _interrupt_manifest(path: Path) -> None:
    """Replace a running batch state after Ctrl-C without hiding the interrupt."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict) or payload.get("status") != "running":
        return
    payload["status"] = "interrupted"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["interruption"] = {
        "type": "KeyboardInterrupt",
        "message": "Transcription was interrupted by the user; completed artifacts remain reusable.",
    }
    atomic_write_json(Path(path), payload)


def main(argv: list[str] | None = None) -> int:
    """Run one standalone transcription batch under its output-set lock."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--output-dir", default="output")
    pre_parser.add_argument("--batch-manifest", type=Path)
    preliminary, _unknown = pre_parser.parse_known_args(arguments)
    output_root = assert_safe_output_target(
        lexical_absolute_path(preliminary.output_dir)
    )
    manifest_path = (
        preliminary.batch_manifest.resolve()
        if preliminary.batch_manifest is not None
        else output_root / TRANSCRIPTION_MANIFEST
    )
    lock_path = output_root.parent / f".{output_root.name}.transcribe.lock"
    with exclusive_process_lock(
        lock_path, purpose=f"writing Whisper transcription set {output_root}"
    ):
        temporary_pattern = f".{manifest_path.name}.*.tmp"
        preexisting_temporaries = {
            path.resolve() for path in manifest_path.parent.glob(temporary_pattern)
        }
        try:
            return _main_unlocked(arguments)
        except KeyboardInterrupt:
            _interrupt_manifest(manifest_path)
            raise
        finally:
            for temporary in manifest_path.parent.glob(temporary_pattern):
                if temporary.resolve() not in preexisting_temporaries and temporary.is_file():
                    temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
