from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import hmac
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from procurement.video_sampling.naming import make_video_output_folder_name
from procurement.external_tools import build_yt_dlp_command, credential_free_media_environment, resolve_media_binary
from procurement.input_limits import count_json_items
from application import backend


FFMPEG_TIMEOUT_SECONDS = 6 * 60 * 60
MAX_FOCUS_MANIFEST_BYTES = 1024 * 1024
MAX_FOCUS_MANIFEST_ITEMS = 100_000
MAX_FOCUS_SEGMENTS = 10_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create focused videos from exact user-selected time ranges.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--segments-json", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-source", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    segment_manifest = args.segments_json.expanduser().resolve()
    if source.is_dir() and (output_root == source or source in output_root.parents):
        raise ValueError("Choose an output directory outside the input folder to avoid reprocessing generated videos.")
    payload = load_focus_manifest(
        segment_manifest,
        expected_sha256=args.manifest_sha256,
        expected_source=args.expected_source,
    )
    processing_source = payload.get("processing_source_path")
    if not isinstance(processing_source, str) or not backend.source_references_match(source, processing_source):
        raise ValueError("Focus CLI source identity does not match the launcher-prepared source identity.")
    output_root.mkdir(parents=True, exist_ok=True)
    run_folder = output_root / f"focus_segments_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_folder.mkdir(parents=True, exist_ok=True)
    copied_manifest = run_folder / "focus_segments_manifest.json"
    copied_manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    results = process_local_segments(source, run_folder, payload)
    run_log = run_folder / "run_log.txt"
    run_log.write_text(
        "\n".join(
            [
                "Focus segment procurement completed.",
                f"Source: {source}",
                f"Original manifest: {segment_manifest}",
                f"Copied manifest: {copied_manifest}",
                f"Local videos processed: {results['processed']}",
                f"Recorded only: {results['recorded_only']}",
                f"Failures: {results['failed']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Focus segment manifest recorded: {copied_manifest}")
    print(f"Local videos processed: {results['processed']}")
    print(f"Recorded only: {results['recorded_only']}")
    print(f"Failures: {results['failed']}")
    print(f"Run log: {run_log}")
    return 1 if results["failed"] else 0


def load_focus_manifest(
    path: Path,
    *,
    expected_sha256: str,
    expected_source: str,
) -> dict[str, object]:
    """Load one bounded Focus control manifest and cap segment cardinality."""

    with path.expanduser().resolve().open("rb") as handle:
        raw = handle.read(MAX_FOCUS_MANIFEST_BYTES + 1)
    if len(raw) > MAX_FOCUS_MANIFEST_BYTES:
        raise ValueError(f"Focus manifest JSON exceeds {MAX_FOCUS_MANIFEST_BYTES} bytes: {path}")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_sha256, str(expected_sha256).strip().casefold()):
        raise ValueError("Focus manifest digest does not match the launcher-validated selection.")
    payload = json.loads(raw.decode("utf-8-sig"))
    if count_json_items(payload, stop_after=MAX_FOCUS_MANIFEST_ITEMS) > MAX_FOCUS_MANIFEST_ITEMS:
        raise ValueError(f"Focus manifest JSON contains more than {MAX_FOCUS_MANIFEST_ITEMS} items: {path}")
    if not isinstance(payload, dict):
        raise ValueError("Focus manifest must be a JSON object.")
    if not backend.source_references_match(payload.get("source_path"), expected_source):
        raise ValueError("Focus manifest source does not match the launcher-validated source identity.")
    selected_segments = payload.get("selected_segments")
    if isinstance(selected_segments, list) and len(selected_segments) > MAX_FOCUS_SEGMENTS:
        raise ValueError(f"Focus manifest may contain at most {MAX_FOCUS_SEGMENTS} selected segments.")
    return payload


def process_local_segments(source: Path, run_folder: Path, payload: dict[str, object]) -> dict[str, int]:
    selected_segments = payload.get("selected_segments")
    if not isinstance(selected_segments, list):
        return {"processed": 0, "recorded_only": 0, "failed": 1}

    gap_seconds = max(0.0, float(payload.get("gap_seconds") or 0))
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    youtube_grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    recorded_only = 0
    invalid_sources = 0
    manifest_source = str(payload.get("source_path") or source).strip()
    manifest_source_path = Path(manifest_source).expanduser() if manifest_source else source
    for item in selected_segments:
        if not isinstance(item, dict):
            recorded_only += 1
            continue
        try:
            identity = backend.focus_source_identity(item)
        except ValueError as exc:
            invalid_sources += 1
            print(f"ERROR: Invalid Focus source identity: {exc}")
            continue
        source_path = Path(str(item.get("source_path") or "")).expanduser()
        if identity.kind in {"file", "folder"} and source_path.exists() and source_path.is_file() and source_is_allowed(source, source_path):
            grouped[str(source_path.resolve())].append(item)
        elif identity.kind == "docx" and identity.reference == os.path.normcase(str(manifest_source_path.resolve())):
            youtube_grouped[f"https://www.youtube.com/watch?v={identity.youtube_id}"].append(item)
        elif identity.kind == "youtube":
            manifest_video_id = backend.run_docx_extractions.get_youtube_video_id(manifest_source)
            if manifest_video_id and manifest_video_id == identity.youtube_id:
                youtube_grouped[f"https://www.youtube.com/watch?v={identity.youtube_id}"].append(item)
            else:
                invalid_sources += 1
                print("ERROR: A Focus YouTube selection does not match the scanned source.")
        else:
            invalid_sources += 1
            print("ERROR: A Focus selection no longer has an available local file or YouTube URL.")

    processed = 0
    failed = invalid_sources
    for source_path_text, segments in grouped.items():
        source_video = Path(source_path_text)
        try:
            process_one_video(source, run_folder, source_video, segments, gap_seconds)
            processed += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR processing {source_video}: {exc}")

    for youtube_url, segments in youtube_grouped.items():
        try:
            process_one_youtube_video(run_folder, youtube_url, segments, gap_seconds)
            processed += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR processing {youtube_url}: {exc}")

    return {"processed": processed, "recorded_only": recorded_only, "failed": failed}


def process_one_video(
    source_root: Path,
    run_folder: Path,
    source_video: Path,
    segments: list[dict[str, object]],
    gap_seconds: float,
) -> None:
    target_dir = run_folder / target_relative_stem(source_root, source_video)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_is_allowed(source_root, source_video):
        raise ValueError(f"Focus source is outside the scanned input: {source_video}")
    duration = backend.read_duration_seconds(source_video)
    if not duration or duration <= 0:
        raise RuntimeError(f"Focus source is not a valid video with positive duration: {source_video}")
    segment_files: list[Path] = []
    for index, segment in enumerate(segments, start=1):
        start = float(segment.get("start_seconds") or 0)
        end = float(segment.get("end_seconds") or 0)
        if end <= start:
            raise ValueError(f"Segment {index} has an invalid start/end range.")
        if end > duration + 0.05:
            raise ValueError(f"Segment {index} ends after the source video duration ({duration:.3f}s).")
        target = target_dir / f"focus_segment_{index:03d}.mp4"
        command = backend.build_imotions_transcode_command(
            source_video,
            target,
            start_seconds=start,
            duration_seconds=end - start,
        )
        subprocess.run(
            command,
            check=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            env=credential_free_media_environment(),
        )
        segment_files.append(target)

    stitched = stitch_focus_segments(target_dir, segment_files, gap_seconds)

    (target_dir / "focus_segments_manifest.json").write_text(
        json.dumps(
            {
                "source_video": str(source_video),
                "output_video": str(stitched),
                "gap_seconds": gap_seconds,
                "segments": segments,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Focus stitched output: {stitched}")
    cleanup_focus_intermediates(target_dir)


def process_one_youtube_video(
    run_folder: Path,
    youtube_url: str,
    segments: list[dict[str, object]],
    gap_seconds: float,
) -> None:
    video_id = str(segments[0].get("video_id") or "youtube_video")
    speaker = safe_name(str(segments[0].get("speaker") or "Unknown Speaker"))
    title = safe_name(str(segments[0].get("video_title") or video_id))
    target_dir = run_folder / speaker / make_video_output_folder_name(title, video_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    segment_files: list[Path] = []
    for index, segment in enumerate(segments, start=1):
        start = float(segment.get("start_seconds") or 0)
        end = float(segment.get("end_seconds") or 0)
        if end <= start:
            raise ValueError(f"Segment {index} has an invalid start/end range.")
        duration = float(segment.get("duration_seconds") or 0)
        if duration > 0 and end > duration + 0.05:
            raise ValueError(f"Segment {index} ends after the scanned video duration ({duration:.3f}s).")
        target = target_dir / f"focus_segment_{index:03d}.mp4"
        subprocess.run(
            build_youtube_segment_command(youtube_url, start, end, target),
            check=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            env=credential_free_media_environment(),
        )
        normalise_clip_for_stitching(target)
        segment_files.append(target)

    stitched = stitch_focus_segments(target_dir, segment_files, gap_seconds)

    (target_dir / "focus_segments_manifest.json").write_text(
        json.dumps(
            {
                "youtube_url": youtube_url,
                "output_video": str(stitched),
                "gap_seconds": gap_seconds,
                "segments": segments,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Focus stitched output: {stitched}")
    cleanup_focus_intermediates(target_dir)


def stitch_focus_segments(target_dir: Path, segment_files: list[Path], gap_seconds: float) -> Path:
    """Join selected clips, inserting a matching black/silent clip if requested."""

    if not segment_files:
        raise ValueError("Focus mode did not produce any segment files.")
    stitched = target_dir / "stitched_imotions.mp4"
    if len(segment_files) == 1:
        shutil.copy2(segment_files[0], stitched)
        return stitched

    stitch_files = add_focus_gap_clips(target_dir, segment_files, gap_seconds)
    concat_list = target_dir / "_concat_focus_segments.txt"
    concat_list.write_text("".join(concat_file_line(item) for item in stitch_files), encoding="utf-8")
    subprocess.run(
        backend.build_imotions_concat_command(concat_list, stitched),
        check=True,
        env=credential_free_media_environment(),
    )
    return stitched


def add_focus_gap_clips(target_dir: Path, segment_files: list[Path], gap_seconds: float) -> list[Path]:
    if gap_seconds <= 0 or len(segment_files) < 2:
        return list(segment_files)

    profile = ffprobe_media_profile(segment_files[0])
    gap_file = target_dir / "_black_silent_gap.mp4"
    command = [
        str(resolve_media_binary("ffmpeg", excluded_roots=(target_dir,))),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        (
            f"color=c=black:s={profile['width']}x{profile['height']}:"
            f"r={profile['fps']}:d={gap_seconds:.3f}"
        ),
    ]
    if profile["has_audio"]:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                (
                    f"anullsrc=channel_layout={profile['channel_layout']}:"
                    f"sample_rate={profile['sample_rate']}"
                ),
            ]
        )
    command.extend(["-t", f"{gap_seconds:.3f}", "-c:v", "libx264"])
    if profile["has_audio"]:
        command.extend(["-c:a", "aac", "-shortest"])
    command.append(str(gap_file))
    subprocess.run(command, check=True, env=credential_free_media_environment())
    return interleave_gap_file(segment_files, gap_file)


def interleave_gap_file(segment_files: list[Path], gap_file: Path) -> list[Path]:
    """Return clip, gap, clip ordering without mutating the caller's list."""

    result: list[Path] = []
    for index, segment_file in enumerate(segment_files):
        if index:
            result.append(gap_file)
        result.append(segment_file)
    return result


def normalise_clip_for_stitching(path: Path) -> None:
    """Transcode a downloaded section so it matches the generated gap codec."""

    temporary = path.with_name(f"{path.stem}_normalised.mp4")
    subprocess.run(
        backend.build_imotions_transcode_command(path, temporary),
        check=True,
        env=credential_free_media_environment(),
    )
    path.unlink()
    temporary.replace(path)


def ffprobe_media_profile(path: Path) -> dict[str, object]:
    """Read only the stream properties required to make a compatible gap."""

    defaults: dict[str, object] = {
        "width": 1280,
        "height": 720,
        "fps": 25.0,
        "sample_rate": 48000,
        "channel_layout": "stereo",
        "has_audio": True,
    }
    try:
        result = subprocess.run(
            [
                str(resolve_media_binary("ffprobe", excluded_roots=(path.parent,))),
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,width,height,r_frame_rate,sample_rate,channels,channel_layout",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env=credential_free_media_environment(),
        )
        streams = json.loads(result.stdout).get("streams") or []
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        defaults["width"] = int(video.get("width") or defaults["width"])
        defaults["height"] = int(video.get("height") or defaults["height"])
        defaults["fps"] = parse_frame_rate(str(video.get("r_frame_rate") or defaults["fps"]))
        defaults["has_audio"] = audio is not None
        if audio:
            defaults["sample_rate"] = int(audio.get("sample_rate") or defaults["sample_rate"])
            defaults["channel_layout"] = str(
                audio.get("channel_layout") or ("mono" if int(audio.get("channels") or 2) == 1 else "stereo")
            )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError):
        pass
    return defaults


def parse_frame_rate(value: str) -> float:
    numerator, separator, denominator = str(value).partition("/")
    try:
        if separator:
            parsed = float(numerator) / float(denominator)
        else:
            parsed = float(numerator)
    except (TypeError, ValueError, ZeroDivisionError):
        return 25.0
    return parsed if parsed > 0 else 25.0


def concat_file_line(path: Path) -> str:
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'\n"


def build_youtube_segment_command(
    youtube_url: str,
    start: float,
    end: float,
    target: Path,
    *,
    python_executable: Path | None = None,
    ffmpeg_binary: Path | None = None,
) -> list[str]:
    ffmpeg = ffmpeg_binary or resolve_media_binary(
        "ffmpeg",
        excluded_roots=(target.parent,),
    )
    command = build_yt_dlp_command(
        [
        "--force-keyframes-at-cuts",
        "--download-sections",
        f"*{seconds_to_timecode(start)}-{seconds_to_timecode(end)}",
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(target),
        youtube_url,
        ],
        ffmpeg_binary=ffmpeg,
        python_executable=python_executable,
    )
    cookies_browser = str(os.getenv("YT_DLP_COOKIES_FROM_BROWSER") or "").strip()
    if cookies_browser:
        option_index = command.index("--ffmpeg-location") + 2
        command[option_index:option_index] = ["--cookies-from-browser", cookies_browser]
    return command


def cleanup_focus_intermediates(target_dir: Path) -> None:
    """Keep the canonical stitch and metadata, not duplicate clip inputs."""

    for pattern in ("focus_segment_*.mp4", "_black_silent_gap.mp4", "_concat_focus_segments.txt"):
        for path in target_dir.glob(pattern):
            path.unlink(missing_ok=True)


def source_is_allowed(source_root: Path, source_video: Path) -> bool:
    """Keep local Focus selections within the source that was supplied."""

    resolved_source = source_root.resolve()
    resolved_video = source_video.resolve()
    if resolved_source.is_file():
        return resolved_source == resolved_video
    if resolved_source.is_dir():
        return resolved_video == resolved_source or resolved_source in resolved_video.parents
    return False


def seconds_to_timecode(value: float) -> str:
    safe = max(0.0, float(value))
    hours = int(safe // 3600)
    minutes = int((safe % 3600) // 60)
    seconds = safe % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in " ._-" else "_" for char in value).strip()
    return cleaned.replace(" ", "_") or "untitled"


def target_relative_stem(source_root: Path, source_video: Path) -> Path:
    """Return a stable output path for either a folder root or one source file."""

    resolved_root = source_root.resolve()
    resolved_video = source_video.resolve()
    if resolved_root.is_file() or resolved_root == resolved_video:
        return Path(source_video.stem)

    try:
        relative = resolved_video.relative_to(resolved_root)
    except ValueError:
        relative = Path(source_video.name)
    return relative.with_suffix("")


if __name__ == "__main__":
    raise SystemExit(main())
