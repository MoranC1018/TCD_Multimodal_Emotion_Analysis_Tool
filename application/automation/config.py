"""Strict, versioned jobs and explicit sequential artifact references."""

from __future__ import annotations

import copy
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError

MAX_JOB_BYTES = 1024 * 1024
MAX_STEPS = 100
from application.backend import DEFAULT_UI_SETTINGS, validate_ui_settings_updates

RESOURCE_DEFAULTS = {key: value for key, value in DEFAULT_UI_SETTINGS.items() if key != "youtubeCookiesBrowser"}


@dataclass(frozen=True)
class Step:
    id: str
    stage: str
    options: dict[str, Any]
    native_options: dict[str, Any]
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class Job:
    source: Path
    base_dir: Path
    submitted: dict[str, Any]
    steps: tuple[Step, ...]
    resources: dict[str, Any]
    timeout_seconds: float | None = None


def absolute_path(value: str | Path, base_dir: Path) -> Path:
    """Use lexical absolute paths so engine reparse checks still see the input."""
    from processing.io_utils import assert_local_filesystem_path_syntax, assert_no_output_path_aliases
    path = assert_local_filesystem_path_syntax(value, description="automation")
    return assert_no_output_path_aliases(path if path.is_absolute() else base_dir / path, description="automation")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path, *, max_bytes: int = MAX_JOB_BYTES) -> Any:
    try:
        path = absolute_path(path, Path.cwd())
        if path.stat().st_size > max_bytes:
            raise ValidationError(f"JSON file exceeds {max_bytes} bytes: {path}")
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValidationError(f"Non-finite JSON number: {value}")))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError(f"Cannot read JSON file {path}: {exc}") from exc


def _check_json(value: Any, depth: int = 0) -> None:
    if depth > 40:
        raise ValidationError("JSON nesting exceeds 40 levels.")
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z]", "", key.casefold())
            if normalized in {"hftoken", "huggingfacetoken", "youtubeapikey", "apikey", "password", "credential", "credentials", "accesstoken"}:
                raise ValidationError(f"Credentials must be supplied by the existing environment/store, never job field {key}.")
            _check_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_json(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValidationError("All numbers must be finite.")


def _keys(value: Any, allowed: set[str], context: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{context} must be an object.")
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(f"Unknown {context} fields: {', '.join(sorted(unknown))}")
    return value


def _timeout(value: Any, context: str) -> float | None:
    if value is None:
        return None
    try:
        valid = type(value) in {int, float} and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValidationError(f"{context} must be a positive finite number.")
    return float(value)


def validate_resources(value: Any) -> dict[str, Any]:
    _keys(value, set(RESOURCE_DEFAULTS), "resources")
    result = dict(RESOURCE_DEFAULTS)
    result.update(value)
    for key, item in result.items():
        if key == "resourceLimitsEnabled":
            if type(item) is not bool:
                raise ValidationError(f"resources.{key} must be boolean.")
        elif key == "ramLimitMode":
            if item not in {"percent", "gb"}:
                raise ValidationError("resources.ramLimitMode must be percent or gb.")
        else:
            integer = key in {"maxCpuCores", "nativeThreads"}
            try:
                valid = (type(item) is int if integer else type(item) in {int, float}) and math.isfinite(item)
            except OverflowError:
                valid = False
            if not valid:
                raise ValidationError(f"resources.{key} must be a finite {'integer' if integer else 'number'}.")
    try:
        validate_ui_settings_updates(result)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return result


def references(value: Any):
    if isinstance(value, dict):
        if "from_step" in value or ("output" in value and set(value) <= {"from_step", "output"}):
            if set(value) != {"from_step", "output"} or not isinstance(value.get("from_step"), str) or value.get("output") != "output_root":
                raise ValidationError('An output reference must be {"from_step":"earlier-id","output":"output_root"}.')
            yield value["from_step"]
        else:
            for item in value.values():
                yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def resolve_references(value: Any, outputs: Mapping[str, Mapping[str, Any]]) -> Any:
    if isinstance(value, dict):
        if "from_step" in value:
            source = value["from_step"]
            try:
                return str(outputs[source][value["output"]])
            except KeyError as exc:
                raise ValidationError(f"Output from earlier successful step {source} is unavailable.") from exc
        return {key: resolve_references(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_references(item, outputs) for item in value]
    return copy.deepcopy(value)


def load_job(path: str | Path) -> Job:
    from .stages import validate_stage_options

    source = absolute_path(path, Path.cwd())
    payload = read_json(source)
    _keys(payload, {"schema_version", "steps", "stage", "options", "native_options", "resources", "timeout_seconds"}, "job")
    _check_json(payload)
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValidationError("schema_version must be the integer 1.")
    if "steps" in payload:
        if any(key in payload for key in ("stage", "options", "native_options")):
            raise ValidationError("Use either steps or the single-stage shorthand.")
        raw_steps = payload["steps"]
    else:
        raw_steps = [{"id": "main", **{key: payload[key] for key in ("stage", "options", "native_options") if key in payload}}]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise ValidationError(f"steps must contain between 1 and {MAX_STEPS} stages.")
    seen: set[str] = set()
    steps = []
    for item in raw_steps:
        _keys(item, {"id", "stage", "options", "native_options", "timeout_seconds"}, "step")
        step_id, stage = item.get("id"), item.get("stage")
        if not isinstance(step_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", step_id):
            raise ValidationError("Step id must start with a letter and contain at most 64 letters, digits, underscores or hyphens.")
        if step_id.casefold() in {value.casefold() for value in seen}:
            raise ValidationError("Step ids must be unique, including on case-insensitive filesystems.")
        if not isinstance(stage, str):
            raise ValidationError(f"Step {step_id} requires a stage name.")
        options, native = item.get("options", {}), item.get("native_options", {})
        if not isinstance(options, dict) or not isinstance(native, dict):
            raise ValidationError("options and native_options must be objects.")
        dependencies = list(references(options)) + list(references(native))
        if any(dependency not in seen for dependency in dependencies):
            raise ValidationError(f"Step {step_id} may refer only to earlier steps.")
        placeholders = {value: {"output_root": str(source.parent / ("deferred-" + value))} for value in seen}
        validate_stage_options(stage, resolve_references(options, placeholders), resolve_references(native, placeholders))
        steps.append(Step(step_id, stage, options, native, _timeout(item.get("timeout_seconds"), "step.timeout_seconds")))
        seen.add(step_id)
    return Job(source, source.parent, copy.deepcopy(payload), tuple(steps), validate_resources(payload.get("resources", {})), _timeout(payload.get("timeout_seconds"), "timeout_seconds"))


def job_schema() -> dict[str, Any]:
    from .stages import stage_schema, native_options_schema

    stages = stage_schema()
    native = native_options_schema()
    reference = {"type": "object", "additionalProperties": False, "required": ["from_step", "output"], "properties": {"from_step": {"type": "string"}, "output": {"const": "output_root"}}}
    def with_references(schema):
        schema = copy.deepcopy(schema)
        for key, value in schema.get("properties", {}).items():
            if key in {"source_path", "output_root", "segment_manifest", "beta_reference_audio", "config", "reference_face_dir"}:
                schema["properties"][key] = {"anyOf": [value, {"$ref": "#/$defs/output_reference"}]}
            elif key == "args":
                schema["properties"][key] = {**value, "items": {"anyOf": [{"type": "string"}, {"$ref": "#/$defs/output_reference"}]}}
            else:
                schema["properties"][key] = with_references(value)
        if "items" in schema:
            schema["items"] = with_references(schema["items"])
        for union in ("anyOf", "oneOf"):
            if union in schema:
                schema[union] = [with_references(item) for item in schema[union]]
        return schema
    branches = [{"if": {"properties": {"stage": {"const": name}}, "required": ["stage"]},
                 "then": {"required": ["options"], "properties": {"options": with_references(options),
                          "native_options": with_references(native.get(name, {"type": "object", "additionalProperties": False}))}}}
                for name, options in stages.items()]
    step = {"type": "object", "additionalProperties": False, "required": ["id", "stage"], "allOf": branches, "properties": {
        "id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"}, "stage": {"enum": list(stages)},
        "options": {"type": "object"}, "native_options": {"type": "object"}, "timeout_seconds": {"type": ["number", "null"], "exclusiveMinimum": 0},
    }}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Multimodal automation job v1", "type": "object", "additionalProperties": False,
            "required": ["schema_version"], "oneOf": [{"required": ["steps"], "not": {"anyOf": [{"required": ["stage"]}, {"required": ["options"]}, {"required": ["native_options"]}]}}, {"required": ["stage"], "not": {"required": ["steps"]}}],
            "allOf": branches,
            "properties": {"schema_version": {"const": 1, "type": "integer"}, "steps": {"type": "array", "minItems": 1, "maxItems": MAX_STEPS, "items": step}, "stage": {"enum": list(stages)}, "options": {"type": "object"}, "native_options": {"type": "object"}, "timeout_seconds": {"type": ["number", "null"], "exclusiveMinimum": 0}, "resources": {"type": "object", "additionalProperties": False, "properties": {key: {"type": "boolean" if type(value) is bool else "string" if isinstance(value, str) else "integer" if type(value) is int else "number", "default": value} for key, value in RESOURCE_DEFAULTS.items()}}},
            "$defs": {"output_reference": reference}, "x-stage-options": stages, "x-native-options": native,
            "description": "Relative paths use the job directory. Explicit references resolve only successful earlier output roots. See x-stage-options for stage contracts; runtime also validates engine provenance and ranges."}
