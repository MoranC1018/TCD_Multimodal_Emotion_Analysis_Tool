from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def bootstrap_repo_path() -> None:
    """Allow this utility to run either from the repo or from a copied package."""

    for index, value in enumerate(sys.argv[:-1]):
        if value == "--repo":
            sys.path.insert(0, str(Path(sys.argv[index + 1]).expanduser().resolve()))
            return
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


bootstrap_repo_path()

from procurement.procurement_beta.detectors import (  # noqa: E402
    embedding_centroid,
    load_reference_embedding_file,
    normalised_embedding,
    padded_crop,
    prepare_insightface_app,
    write_jpeg,
)
from procurement.procurement_beta.speaker_profile import cosine_similarity  # noqa: E402


@dataclass
class FrameCandidate:
    """A candidate reference still taken from one matched video frame."""

    video_path: Path
    video_id: str
    timestamp_seconds: float
    similarity: float
    detection_score: float
    face_width: int
    face_height: int
    sharpness: float
    quality_score: float
    crop: Any
    embedding: list[float]


def safe_token(value: str, *, max_chars: int = 80) -> str:
    """Return a compact filename-safe token."""

    cleaned = re.sub(r"\s+", "_", str(value or "item").strip())
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return (cleaned or "item")[:max_chars]


def load_seed_embedding(bank_dir: Path) -> list[float]:
    """Load the current reference centroid used to identify the speaker."""

    embedding = load_reference_embedding_file(bank_dir / "reference_embedding.json")
    if not embedding:
        raise ValueError(f"No seed embedding found in {bank_dir / 'reference_embedding.json'}")
    return embedding


def video_duration_seconds(cv2: Any, video_path: Path) -> float:
    """Read a duration estimate without shelling out to ffprobe."""

    capture = cv2.VideoCapture(str(video_path))
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        if fps > 0 and frame_count > 0:
            return frame_count / fps
        return 0.0
    finally:
        capture.release()


def sample_times(duration: float, *, step_seconds: float, max_frames: int) -> list[float]:
    """Choose evenly spaced timestamps for face-bank sampling."""

    if duration <= 0:
        return []
    start = min(3.0, max(0.0, duration * 0.05))
    end = max(start, duration - min(3.0, duration * 0.03))
    times = []
    current = start
    while current <= end:
        times.append(current)
        current += max(1.0, step_seconds)
    if len(times) > max_frames:
        stride = len(times) / max_frames
        times = [times[min(len(times) - 1, int(round(index * stride)))] for index in range(max_frames)]
    return sorted(set(round(value, 3) for value in times))


def laplacian_variance(cv2: Any, frame: Any) -> float:
    """Use blur variance as a cheap reference-still quality signal."""

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def candidate_quality(
    *,
    similarity: float,
    detection_score: float,
    face_width: int,
    face_height: int,
    frame_width: int,
    frame_height: int,
    sharpness: float,
) -> float:
    """Rank candidates by identity match first, then image quality."""

    face_ratio = (face_width * face_height) / max(1, frame_width * frame_height)
    size_score = min(1.0, math.sqrt(face_ratio) / 0.32)
    sharpness_score = min(1.0, sharpness / 350.0)
    return (similarity * 0.68) + (detection_score * 0.12) + (size_score * 0.12) + (sharpness_score * 0.08)


def best_matching_face(
    faces: list[Any],
    seed_embedding: list[float],
    normalise_embedding: Any,
) -> tuple[Any | None, list[float], float]:
    """Select the detected face most similar to the speaker seed."""

    best_face = None
    best_embedding: list[float] = []
    best_similarity = -1.0
    for face in faces:
        embedding = normalise_embedding(face.normed_embedding if hasattr(face, "normed_embedding") else face.embedding)
        if not embedding:
            continue
        similarity = cosine_similarity(embedding, seed_embedding)
        if similarity > best_similarity:
            best_face = face
            best_embedding = embedding
            best_similarity = similarity
    return best_face, best_embedding, best_similarity


def collect_video_candidates(
    *,
    cv2: Any,
    app: Any,
    video_path: Path,
    seed_embedding: list[float],
    threshold: float,
    min_face_pixels: int,
    step_seconds: float,
    max_frames_per_video: int,
) -> list[FrameCandidate]:
    """Sample one video and return face crops that match the seed speaker."""

    duration = video_duration_seconds(cv2, video_path)
    times = sample_times(duration, step_seconds=step_seconds, max_frames=max_frames_per_video)
    capture = cv2.VideoCapture(str(video_path))
    candidates: list[FrameCandidate] = []
    try:
        for timestamp in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue

            faces = list(app.get(frame) or [])
            if not faces:
                continue

            face, embedding, similarity = best_matching_face(faces, seed_embedding, normalised_embedding)
            if face is None or similarity < threshold:
                continue

            x1, y1, x2, y2 = [int(round(value)) for value in face.bbox[:4]]
            face_width = max(0, x2 - x1)
            face_height = max(0, y2 - y1)
            if min(face_width, face_height) < min_face_pixels:
                continue

            frame_height, frame_width = frame.shape[:2]
            crop = padded_crop(frame, x1, y1, face_width, face_height, padding_ratio=0.22)
            sharpness = laplacian_variance(cv2, crop)
            detection_score = float(getattr(face, "det_score", 1.0) or 1.0)
            score = candidate_quality(
                similarity=similarity,
                detection_score=detection_score,
                face_width=face_width,
                face_height=face_height,
                frame_width=frame_width,
                frame_height=frame_height,
                sharpness=sharpness,
            )
            candidates.append(
                FrameCandidate(
                    video_path=video_path,
                    video_id=video_path.stem,
                    timestamp_seconds=float(timestamp),
                    similarity=float(similarity),
                    detection_score=detection_score,
                    face_width=face_width,
                    face_height=face_height,
                    sharpness=sharpness,
                    quality_score=score,
                    crop=crop,
                    embedding=embedding,
                )
            )
    finally:
        capture.release()
    return candidates


def too_close_to_existing(
    candidate: FrameCandidate,
    selected: list[FrameCandidate],
    *,
    min_time_gap_seconds: float,
) -> bool:
    """Avoid grabbing many near-identical frames from the same moment."""

    for existing in selected:
        if existing.video_id != candidate.video_id:
            continue
        if abs(existing.timestamp_seconds - candidate.timestamp_seconds) < min_time_gap_seconds:
            return True
    return False


def select_reference_stills(
    candidates: list[FrameCandidate],
    *,
    target_count: int,
    min_time_gap_seconds: float,
    max_per_video: int,
) -> list[FrameCandidate]:
    """Choose a balanced, high-quality set, then relax constraints if needed."""

    ordered = sorted(candidates, key=lambda item: item.quality_score, reverse=True)
    selected: list[FrameCandidate] = []
    per_video: dict[str, int] = {}

    def can_take(candidate: FrameCandidate, *, enforce_balance: bool, enforce_gap: bool) -> bool:
        if candidate in selected:
            return False
        if enforce_balance and per_video.get(candidate.video_id, 0) >= max_per_video:
            return False
        if enforce_gap and too_close_to_existing(candidate, selected, min_time_gap_seconds=min_time_gap_seconds):
            return False
        return True

    for enforce_balance, enforce_gap in ((True, True), (False, True), (False, False)):
        for candidate in ordered:
            if len(selected) >= target_count:
                return selected
            if not can_take(candidate, enforce_balance=enforce_balance, enforce_gap=enforce_gap):
                continue
            selected.append(candidate)
            per_video[candidate.video_id] = per_video.get(candidate.video_id, 0) + 1
    return selected


def write_bank(
    *,
    cv2: Any,
    bank_dir: Path,
    speaker: str,
    speaker_key: str,
    selected: list[FrameCandidate],
    target_count: int,
    threshold: float,
) -> None:
    """Rewrite the bank artifacts from selected video-derived stills."""

    stills_dir = bank_dir / "identity_stills"
    stills_dir.mkdir(parents=True, exist_ok=True)
    for old_file in stills_dir.glob("*.jpg"):
        old_file.unlink()

    embeddings: list[list[float]] = []
    manifest_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        timestamp_token = f"{candidate.timestamp_seconds:.1f}s".replace(".", "p")
        still_path = stills_dir / f"still_{index:03d}_{safe_token(candidate.video_id)}_{timestamp_token}.jpg"
        write_jpeg(cv2, still_path, candidate.crop)
        embeddings.append(candidate.embedding)
        manifest_rows.append(
            {
                "speaker": speaker,
                "speaker_key": speaker_key,
                "source_type": "video_frame",
                "source_video": str(candidate.video_path),
                "video_id": candidate.video_id,
                "timestamp_seconds": round(candidate.timestamp_seconds, 3),
                "similarity_to_seed": round(candidate.similarity, 6),
                "det_score": round(candidate.detection_score, 6),
                "face_width": candidate.face_width,
                "face_height": candidate.face_height,
                "sharpness": round(candidate.sharpness, 3),
                "quality_score": round(candidate.quality_score, 6),
                "still_path": str(still_path),
            }
        )

    payload = {
        "speaker": speaker,
        "speaker_key": speaker_key,
        "created_from": "video_derived_reference_images",
        "target_reference_count": target_count,
        "accepted_source_count": len(selected),
        "similarity_threshold": threshold,
        "embedding": embedding_centroid(embeddings),
        "sources": manifest_rows,
    }
    (bank_dir / "reference_embedding.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (bank_dir / "reference_manifest.json").write_text(json.dumps(manifest_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (bank_dir / "reference_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0].keys()) if manifest_rows else ["speaker"])
        writer.writeheader()
        writer.writerows(manifest_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a speaker reference bank from already-downloaded videos.")
    parser.add_argument("--repo", type=Path, default=None, help="Repo root used when running a copied script.")
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--speaker-key", required=True)
    parser.add_argument("--speaker", default=None)
    parser.add_argument("--target-count", type=int, default=20)
    parser.add_argument("--similarity-threshold", type=float, default=0.34)
    parser.add_argument("--sample-step-seconds", type=float, default=12.0)
    parser.add_argument("--max-frames-per-video", type=int, default=220)
    parser.add_argument("--min-face-pixels", type=int, default=72)
    parser.add_argument("--min-time-gap-seconds", type=float, default=9.0)
    parser.add_argument("--max-per-video", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    raise RuntimeError(
        "The InsightFace reference-bank builder is disabled until the Buffalo-L model "
        "pack has an authoritative digest allowlist."
    )
    args = parse_args()
    import cv2
    import insightface

    package_root = args.package_root.expanduser().resolve()
    speaker_key = args.speaker_key
    speaker = args.speaker or speaker_key.replace("_", " ")
    bank_dir = package_root / "reference_banks" / speaker_key
    video_dir = package_root / "input_videos" / speaker_key
    videos = sorted(video_dir.glob("*.mp4"))
    if not videos:
        raise FileNotFoundError(f"No .mp4 files found in {video_dir}")

    seed_embedding = load_seed_embedding(bank_dir)
    app = prepare_insightface_app(insightface, det_size=(320, 320))
    all_candidates: list[FrameCandidate] = []
    for video_path in videos:
        candidates = collect_video_candidates(
            cv2=cv2,
            app=app,
            video_path=video_path,
            seed_embedding=seed_embedding,
            threshold=args.similarity_threshold,
            min_face_pixels=args.min_face_pixels,
            step_seconds=args.sample_step_seconds,
            max_frames_per_video=args.max_frames_per_video,
        )
        all_candidates.extend(candidates)
        print(f"{speaker}: {video_path.name} produced {len(candidates)} matching frame candidates.", flush=True)

    selected = select_reference_stills(
        all_candidates,
        target_count=args.target_count,
        min_time_gap_seconds=args.min_time_gap_seconds,
        max_per_video=args.max_per_video,
    )
    write_bank(
        cv2=cv2,
        bank_dir=bank_dir,
        speaker=speaker,
        speaker_key=speaker_key,
        selected=selected,
        target_count=args.target_count,
        threshold=args.similarity_threshold,
    )
    print(
        f"{speaker}: wrote {len(selected)}/{args.target_count} video-derived reference stills to {bank_dir / 'identity_stills'}",
        flush=True,
    )
    return 0 if len(selected) >= args.target_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
