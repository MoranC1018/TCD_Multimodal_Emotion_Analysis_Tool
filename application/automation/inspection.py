"""Read-only discovery and runtime readiness, shared with the GUI engines."""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from pathlib import Path

from .config import RESOURCE_DEFAULTS, absolute_path
from .errors import ValidationError


def modalities_from_arguments(values):
    from application import backend
    result = []
    for name, method, source in values or []:
        if name not in {"video", "audio", "text", "imotions", "native_face"} or method not in {"run", "import"}:
            raise ValidationError("Each --modality requires NAME (video/audio/text), METHOD (run/import), and PATH.")
        result.append(backend.AnalysisModalityRunRequest(name, method, absolute_path(source, Path.cwd())))
    if not result:
        raise ValidationError("Supply at least one --modality NAME METHOD PATH.")
    return tuple(result)


def inspect_source(source: str, *, enrich_youtube: bool = True):
    from application import backend
    return backend.scan_result_to_json(backend.scan_input_source(source, enrich_youtube=enrich_youtube, logger=lambda message: print(message, file=sys.stderr)))


def inspect_catalog(source: str):
    from application import backend
    result = backend.scan_audio_catalog_run(absolute_path(source, Path.cwd()))
    if result is None:
        raise ValidationError("Source is not a validated procurement catalog run.")
    return backend.scan_result_to_json(result)


def inspect_analysis(kind: str, values, source_manifest: str | None = None):
    from application import backend
    modalities = modalities_from_arguments(values)
    if kind == "analysis-speakers":
        return backend.discover_analysis_speakers(modalities)
    return backend.discover_analysis_profile_context(modalities, source_manifest=absolute_path(source_manifest, Path.cwd()) if source_manifest else None)


def settings_description():
    return {"resource_defaults": RESOURCE_DEFAULTS, "scope": "Per-job resource overrides; desktop settings are not changed.",
            "credential_environment_present": {
                "youtube": bool(os.environ.get("YOUTUBE_API_KEY")),
                "hugging_face": any(os.environ.get(key) for key in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")),
            }, "credentials": "Existing environment and local credential store are consumed by the existing engines. Values are never returned."}


def doctor(component: str = "all", *, device: str = "auto", text_stages: list[str] | None = None):
    selected = ["procurement", "audio", "face", "text", "clean-speaker"] if component == "all" else [component]
    results = {}
    for name in selected:
        try:
            if name == "procurement":
                from procurement.external_tools import resolve_media_binary, yt_dlp_is_available
                paths = {tool: str(resolve_media_binary(tool)) for tool in ("ffmpeg", "ffprobe")}
                result = {"ready": True, "tools": paths, "youtube_available": yt_dlp_is_available()}
            elif name == "audio":
                from processing.audio_analysis.audio_pipeline.doctor import collect_diagnostics, required_checks_pass
                checks = collect_diagnostics()
                result = {"ready": required_checks_pass(checks), "checks": [asdict(check) for check in checks],
                          "scope": "Full audio runtime; includes emotion-model dependencies even for acoustic-only jobs."}
            elif name == "face":
                from processing.face_analysis.health import check_readiness
                result = check_readiness(device).to_dict()
            elif name == "text":
                from processing.text_analysis.pipeline import TextProcessingConfig, check_text_processing_readiness, STAGES
                result = check_text_processing_readiness(TextProcessingConfig(), stages=text_stages or STAGES)
                result["ready"] = result.get("status") == "ready"
            elif name == "clean-speaker":
                from procurement.procurement_beta.readiness import build_readiness_report
                result = build_readiness_report()
                result["ready"] = result["canProduceCleanSegments"]
            else:
                raise ValidationError(f"Unknown doctor component: {name}")
        except Exception as exc:
            result = {"ready": False, "error": str(exc)}
        results[name] = result
    return {"state": "ready" if all(value.get("ready", False) for value in results.values()) else "not_ready",
            "python_executable": sys.executable, "components": results,
            "scope": "Checks the local runtime without installing packages or downloading model weights; it does not certify scientific model accuracy."}
