"""Strict JSON adapters over the desktop requests and existing native CLIs."""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import math
import os
import re
import types
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import get_args, get_origin, get_type_hints
from collections.abc import Mapping

from application import backend
from .errors import ValidationError


MODELS = {'procurement': backend.RunRequest, 'audio': backend.AudioRunRequest,
          'face': backend.FaceProcessingRunRequest, 'text': backend.TextProcessingRunRequest,
          'analysis': backend.AnalysisWorkflowRunRequest}
INTERNAL = {'internal_youtube_source', 'detected_video_source'}
BUILDERS = {'procurement': backend.build_run_command, 'audio': backend.build_audio_command,
            'face': backend.build_face_processing_command, 'text': backend.build_text_processing_command,
            'analysis': backend.build_analysis_workflow_command}
ADVANCED = {'procurement': {'allow_external_local_paths': bool, 'reference_face_dir': Path,
                            'run_final_output_validation': bool},
            'face': {'run_id': str}, 'text': {'from_stage': str, 'to_stage': str, 'config': Path, 'run_id': str},
            'audio': {}, 'analysis': {'profile_options': backend.AnalysisProfile}}
# Only these installed engines may be launched. Parser declarations are read from
# their source without importing engine modules or triggering model initialization.
NATIVE = {
    'local': ('application.local_videos', 'application/local_videos.py', 'parse_args'),
    'focus': ('application.manual_segments', 'application/manual_segments.py', 'parse_args'),
    'catalog': ('procurement.catalog_runner', 'procurement/catalog_runner.py', 'build_parser'),
    'clean-speaker': ('procurement.procurement_beta.cli', 'procurement/procurement_beta/cli.py', 'parse_args'),
    'pipeline': ('procurement.run_pipeline', 'procurement/run_pipeline.py', 'parse_args'),
    'docx-sampling': ('procurement.video_sampling.run_docx_extractions', 'procurement/video_sampling/run_docx_extractions.py', 'main'),
    'audio': ('processing.audio_analysis.audio_pipeline', 'processing/audio_analysis/audio_pipeline/cli.py', 'build_parser'),
    'face': ('processing.face_analysis', 'processing/face_analysis/__main__.py', 'main'),
    'text': ('processing.text_analysis', 'processing/text_analysis/__main__.py', 'main'),
    'analysis': ('analysis.workflow', 'analysis/workflow.py', 'build_parser'),
    'analysis-audio': ('analysis.audio', 'analysis/audio.py', 'build_parser'),
    'analysis-face': ('analysis.native_face', 'analysis/native_face.py', 'build_parser'),
    'analysis-imotions': ('analysis.imotions', 'analysis/imotions.py', 'parse_args'),
}


@dataclass(frozen=True)
class StagePlan:
    command: list[str]
    output_root: Path
    details: dict[str, object] = field(default_factory=dict)


def _path(value: str | Path, base_dir: Path) -> Path:
    from .config import absolute_path
    return absolute_path(value, base_dir)


def _validate_native_boundary(args):
    # Runs while loading the submitted job, before any evidence is persisted.
    # Never include submitted arguments or values in these diagnostics.
    secret = re.compile(r'(?:^|[=\s])--(?:api[-_]key|youtube[-_]api[-_]key|hf[-_]token|hugging[-_]?face[-_]token|access[-_]token|token|password|credentials?)(?:[=\s]|$)', re.I)
    private = {'--single-video-json', '--child-result-json', '--child-run-root', '--child-index', '--child-total'}
    forwarding = {'--sample-arg', '--full-video-arg', '--extractor-arg'}
    for token in args:
        if secret.search(token):
            raise ValidationError('Credentials must use the existing environment/store, never native arguments.')
    for token in args:
        flag = token.partition('=')[0]
        if flag in private:
            raise ValidationError('Internal child-entry controls are not supported by automation stages.')
        if flag in forwarding:
            raise ValidationError('Unbounded native argument forwarding is not supported by automation stages; use explicit stage controls or the standalone native CLI.')


def _schema(annotation):
    args, origin = get_args(annotation), get_origin(annotation)
    if origin is types.UnionType:
        return {'anyOf': [_schema(a) for a in args]}
    if annotation is type(None):
        return {'type': 'null'}
    if annotation is Path:
        return {'type': 'string', 'minLength': 1}
    if annotation in (str, bool, int, float):
        return {'type': {str: 'string', bool: 'boolean', int: 'integer', float: 'number'}[annotation]}
    if origin in (tuple, list):
        return {'type': 'array', 'items': _schema(args[0])}
    if origin is Mapping:
        return {'type': 'object', 'additionalProperties': _schema(args[1])}
    if annotation is backend.AnalysisProfile:
        return {'anyOf': [{'type': 'object'}, {'type': 'string', 'minLength': 1}]}
    if is_dataclass(annotation):
        return _model_schema(annotation)
    raise RuntimeError(f'Unsupported request annotation: {annotation}')


def _model_schema(model):
    hints = get_type_hints(model)
    return {'type': 'object', 'additionalProperties': False,
            'properties': {f.name: _schema(hints[f.name]) for f in fields(model) if f.name not in INTERNAL},
            'required': [f.name for f in fields(model) if f.default is MISSING and f.default_factory is MISSING]}


def stage_schema() -> dict:
    result = {stage: _model_schema(model) for stage, model in MODELS.items()}
    for stage, model in MODELS.items():
        result[stage]['required'] = ['modalities' if stage == 'analysis' else 'source_path']
        for request_field in fields(model):
            if request_field.name in INTERNAL:
                continue
            default = request_field.default
            if default is MISSING and request_field.default_factory is not MISSING:
                default = request_field.default_factory()
            if default is not MISSING:
                result[stage]['properties'][request_field.name]['default'] = list(default) if isinstance(default, tuple) else default
    result['procurement']['properties']['mode']['default'] = 'standard'
    for engine in NATIVE:
        result[f'native.{engine}'] = {'type': 'object', 'additionalProperties': False,
            'properties': {'args': {'type': 'array', 'items': {'type': 'string'}}, 'output_root': {'type': 'string', 'minLength': 1}},
            'required': ['args']}
    return result


def native_options_schema() -> dict:
    result = {stage: {'type': 'object', 'additionalProperties': False,
                    'properties': {key: _schema(value) for key, value in options.items()}}
            for stage, options in ADVANCED.items()}
    member = {'type': 'object', 'additionalProperties': False, 'required': ['type', 'id'],
              'properties': {'type': {'enum': ['speaker', 'source']}, 'id': {'type': 'string'}}}
    group = {'type': 'object', 'additionalProperties': False, 'required': ['id', 'name', 'members'],
             'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'}, 'members': {'type': 'array', 'items': member}}}
    result['analysis']['properties']['profile_options'] = {'type': 'object', 'additionalProperties': False,
        'properties': {'automatic_group_field': {'type': ['string', 'null']},
                       'sort_fields': {'type': 'array', 'items': {'type': 'string'}},
                       'manual_groups': {'type': 'array', 'items': group},
                       'metadata_filters': {'type': 'object', 'additionalProperties': {'type': 'array', 'items': {'type': 'string'}}}}}
    return result


def _profile_payload(options, source_manifest, digest):
    allowed = {'automatic_group_field', 'sort_fields', 'manual_groups', 'metadata_filters'}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValidationError('profile_options accepts automatic_group_field, sort_fields, manual_groups, and metadata_filters only')
    return {'format_version': 1, 'source_manifest': {'path': str(source_manifest), 'sha256': digest},
            'automatic_group_field': None, 'sort_fields': [], 'manual_groups': [], 'metadata_filters': {}, **options}


def _check(value, annotation, label):
    args, origin = get_args(annotation), get_origin(annotation)
    if origin is types.UnionType:
        for option in args:
            try:
                _check(value, option, label)
                return
            except ValidationError:
                pass
        raise ValidationError(f'{label} has an invalid type or value')
    if annotation is type(None):
        valid = value is None
    elif annotation in (str, Path):
        valid = isinstance(value, str) and '\x00' not in value and (annotation is str or bool(value.strip()))
    elif annotation is bool:
        valid = type(value) is bool
    elif annotation is int:
        valid = type(value) is int
    elif annotation is float:
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
    elif origin in (tuple, list):
        valid = isinstance(value, list)
        if valid:
            for i, item in enumerate(value):
                _check(item, args[0], f'{label}[{i}]')
    elif origin is Mapping:
        valid = isinstance(value, dict)
        if valid:
            for key, item in value.items():
                _check(key, args[0], label)
                _check(item, args[1], f'{label}.{key}')
    elif annotation is backend.AnalysisProfile:
        valid = isinstance(value, (dict, str)) and bool(value)
        if isinstance(value, dict):
            from analysis.profile import profile_from_payload
            try:
                profile_from_payload(value)
            except (ValueError, TypeError) as exc:
                raise ValidationError(str(exc)) from exc
    elif is_dataclass(annotation):
        _check_model(value, annotation, label, required=True)
        return
    else:
        raise RuntimeError(f'Unsupported annotation {annotation}')
    if not valid:
        raise ValidationError(f'{label} has an invalid type or value')


def _check_model(options, model, label, *, required=False):
    if not isinstance(options, dict):
        raise ValidationError(f'{label} must be an object')
    hints = get_type_hints(model)
    for name, value in options.items():
        if name not in hints or name in INTERNAL:
            raise ValidationError(f'Unknown {label} option: {name}')
        _check(value, hints[name], f'{label}.{name}')
    if required:
        missing = set(_model_schema(model)['required']) - options.keys()
        if missing:
            raise ValidationError(f'Missing {label} options: {", ".join(sorted(missing))}')


def validate_stage_options(stage, options, native_options) -> None:
    if not isinstance(options, dict) or not isinstance(native_options, dict):
        raise ValidationError('options and native_options must be objects')
    if stage.startswith('native.'):
        if stage[7:] not in NATIVE:
            raise ValidationError(f'Unknown native engine: {stage}')
        if set(options) - {'args', 'output_root'} or native_options:
            raise ValidationError('Native stages accept args and output_root only')
        _check(options.get('args'), list[str], 'args')
        _validate_native_boundary(options['args'])
        if 'output_root' in options:
            _check(options['output_root'], Path, 'output_root')
        return
    if stage not in MODELS:
        raise ValidationError(f'Unknown stage: {stage}')
    _check_model(options, MODELS[stage], stage)
    required = 'modalities' if stage == 'analysis' else 'source_path'
    if required not in options:
        raise ValidationError(f'{stage} requires {required}')
    for name, value in native_options.items():
        if name not in ADVANCED[stage]:
            raise ValidationError(f'Unknown native option for {stage}: {name}')
        if stage == 'analysis' and name == 'profile_options':
            if options.get('analysis_profile') is not None or options.get('speaker_groups'):
                raise ValidationError('profile_options is mutually exclusive with analysis_profile and speaker_groups')
            _check(_profile_payload(value, 'source_manifest.json', 'a' * 64), backend.AnalysisProfile, 'profile_options')
        else:
            _check(value, ADVANCED[stage][name], f'native_options.{name}')


def _convert(value, annotation, base_dir):
    if value is None:
        return None
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType:
        return _convert(value, next(a for a in args if a is not type(None)), base_dir)
    if annotation is Path:
        return _path(value, base_dir)
    if origin in (tuple, list):
        return origin(_convert(v, args[0], base_dir) for v in value)
    if annotation is backend.AnalysisProfile:
        from analysis.profile import profile_from_payload
        if isinstance(value, str):
            filename = _path(value, base_dir)
            return profile_from_payload(json.loads(filename.read_text(encoding='utf-8')), relative_to=filename.parent)
        return profile_from_payload(value, relative_to=base_dir)
    if is_dataclass(annotation):
        hints = get_type_hints(annotation)
        return annotation(**{k: _convert(v, hints[k], base_dir) for k, v in value.items()})
    return value


def _bind_catalog(values, scan, selection_key):
    if scan is None or not scan.catalog_sha256:
        if values.get(selection_key) or values.get('catalog_sha256'):
            raise ValidationError('Source selection requires a sealed catalog source')
        return
    digest = scan.catalog_sha256.casefold()
    if values.get('catalog_sha256') and values['catalog_sha256'].casefold() != digest:
        raise ValidationError('Catalog SHA-256 does not match the fresh source scan')
    available = [str(item.source_id or item.id) for item in scan.sources]
    selected = values.get(selection_key)
    if selected is None or selection_key not in values:
        selected = available
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(available):
        raise ValidationError('Choose unique SourceIDs present in the fresh catalog scan')
    values[selection_key] = selected if selection_key == 'selected_ids' else tuple(selected)
    values['catalog_sha256'] = digest


def _focus(values, scan, workspace, dry_run, original_source):
    from application import launcher, manual_segments
    filename = values.get('segment_manifest')
    if filename is None:
        raise ValidationError('Focus requires segment_manifest')
    with filename.open('rb') as handle:
        raw = handle.read(manual_segments.MAX_FOCUS_MANIFEST_BYTES + 1)
    if len(raw) > manual_segments.MAX_FOCUS_MANIFEST_BYTES:
        raise ValidationError('Focus manifest exceeds the native size limit')
    digest = hashlib.sha256(raw).hexdigest()
    expected = values.get('segment_expected_source') or original_source
    supplied = values.get('segment_manifest_sha256')
    if supplied and supplied.casefold() != digest:
        raise ValidationError('Focus manifest SHA-256 mismatch')
    if not backend.source_references_match(expected, original_source):
        raise ValidationError('Focus expected source differs from requested source')
    original = json.loads(raw.decode('utf-8-sig'))
    original_identity = original.get('source_path') if isinstance(original, dict) else None
    if not isinstance(original_identity, str) or not original_identity.strip():
        raise ValidationError('Focus manifest requires source_path')
    payload = manual_segments.load_focus_manifest(filename, expected_sha256=digest, expected_source=original_identity)
    identity = original_identity if backend.run_docx_extractions.get_youtube_video_id(original_identity) else str(_path(original_identity, filename.parent))
    if not backend.source_references_match(identity, expected):
        raise ValidationError('Focus manifest source differs from the fresh scan')
    payload['source_path'] = identity
    for segment in payload.get('selected_segments', []):
        if isinstance(segment, dict) and isinstance(segment.get('source_path'), str) and segment['source_path'] and not backend.run_docx_extractions.get_youtube_video_id(segment['source_path']):
            segment['source_path'] = str(_path(segment['source_path'], filename.parent))
    state = launcher.LauncherState()
    state.set_allowed_media_items([v for group in scan.groups for v in group.videos] + scan.sources)
    state.set_allowed_catalog_scan(scan)
    payload['selected_segments'] = launcher.validate_segment_manifest(payload,
        selected_speakers=values.get('selected_speakers'), require_scanned_source=True, scan_state=state)
    if values.get('selected_ids'):
        if any(segment.get('source_id') not in values['selected_ids'] for segment in payload['selected_segments']):
            raise ValidationError('Focus segment belongs to an unselected catalog SourceID')
    payload['processing_source_path'] = str(values['source_path'])
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    target = workspace / 'focus_segments.json'
    if not dry_run:
        workspace.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    values.update(segment_manifest=target, segment_manifest_sha256=hashlib.sha256(data).hexdigest(), segment_expected_source=str(expected))


def _native_parser(engine, repo_root):
    """Evaluate only native argparse declarations, never their execution body."""
    _, relative, function = NATIVE[engine]
    filename = repo_root / relative
    tree = ast.parse(filename.read_text(encoding='utf-8-sig'))
    namespace = {'argparse': argparse, 'Path': Path, 'str': str, 'int': int, 'float': float,
                 '__file__': str(filename), '__doc__': ast.get_docstring(tree), 'os': os,
                 'WorkflowError': ValidationError}
    # Reuse literal native choices, including Text's imported stage/model lists.
    for source in (tree, ast.parse((repo_root / 'processing/text_analysis/pipeline.py').read_text(encoding='utf-8-sig'))):
        for node in source.body:
            if isinstance(node, ast.Assign):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        namespace[target.id] = value
    if engine == 'audio':
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'add_common_options')
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(filename), 'exec'), namespace)
    if engine == 'analysis':
        parser_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_WorkflowArgumentParser')
        exec(compile(ast.Module(body=[parser_class], type_ignores=[]), str(filename), 'exec'), namespace)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
    prefix = []
    for node in fn.body:
        if isinstance(node, ast.Return) or any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'parse_args' for n in ast.walk(node)):
            break
        if not prefix and not (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'parser' for target in node.targets)):
            continue
        prefix.append(node)
    exec(compile(ast.Module(body=prefix, type_ignores=[]), str(filename), 'exec'), namespace)
    parser = namespace['parser']
    parser.allow_abbrev = False
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                child.allow_abbrev = False
    return parser


def _parse_native(engine, args, repo_root, *, parser=None):
    parser = parser or _native_parser(engine, repo_root)
    stream = io.StringIO()
    try:
        with contextlib.redirect_stderr(stream), contextlib.redirect_stdout(stream):
            parsed = parser.parse_args(args)
    except SystemExit as exc:
        raise ValidationError(stream.getvalue().strip() or 'Native help is not a workflow stage') from exc
    for name, value in vars(parsed).items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValidationError(f'Native {name} must be finite')
    return parsed


def _native_paths(parser, args, base_dir):
    """Resolve supplied native path arguments using the same config directory."""
    actions = list(parser._actions)
    by_option = {flag: action for action in actions for flag in action.option_strings}
    path_names = NATIVE_STRING_PATHS
    positional = [action for action in actions if not action.option_strings]
    result = []
    index = 0
    positional_index = 0
    options_finished = False
    def convert(value, action):
        if (action.type is Path or action.dest in path_names) and not backend.run_docx_extractions.get_youtube_video_id(value):
            return str(_path(value, base_dir))
        if action.dest == 'dictionary' and value.startswith('file:'):
            return 'file:' + str(_path(value[5:], base_dir))
        if action.dest == 'analysis_profile_json' and value:
            from analysis.profile import profile_from_payload, profile_payload
            payload = json.loads(value)
            profile = profile_from_payload(payload, relative_to=base_dir)
            guarded_manifest = _path(payload['source_manifest']['path'], base_dir)
            payload = profile_payload(profile)
            payload['source_manifest']['path'] = str(guarded_manifest)
            return json.dumps(payload, ensure_ascii=False)
        return value
    while index < len(args):
        token = args[index]
        if token == '--' and not options_finished:
            options_finished = True
            result.append(token)
            index += 1
            continue
        flag, separator, inline = token.partition('=')
        action = None if options_finished else by_option.get(flag)
        if action is not None:
            if separator:
                result.append(flag + '=' + convert(inline, action))
            elif action.nargs == 0:
                result.append(token)
            else:
                result.extend([token, convert(args[index + 1], action)])
                index += 1
        elif positional_index < len(positional):
            action = positional[positional_index]
            if isinstance(action, argparse._SubParsersAction):
                result.append(token)
                active = action.choices[token]
                actions = list(active._actions)
                by_option = {flag: item for item in actions for flag in item.option_strings}
                positional = [item for item in actions if not item.option_strings]
                positional_index = 0
            else:
                result.append(convert(token, action))
                positional_index += 1
        else:
            result.append(token)
        index += 1
    return result


NATIVE_STRING_PATHS = {'source', 'input', 'input_video', 'input_folder', 'catalog', 'docx_path',
                       'expected_source', 'output', 'output_root', 'run_root', 'speaker_output_root', 'extractor'}
NATIVE_OUTPUTS = {'output', 'output_root', 'run_root', 'speaker_output_root', 'download_root'}


def _native_path_contract(parser, parsed, engine, output, repo_root):
    inputs, outputs = set(), {str(output)}
    actions = list(parser._actions)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            selected = action.choices.get(getattr(parsed, action.dest, ''))
            if selected is not None:
                actions.extend(selected._actions)
    for action in actions:
        value = getattr(parsed, action.dest, None)
        if value is None:
            continue
        if action.type is Path or action.dest in NATIVE_STRING_PATHS:
            for entry in value if isinstance(value, list) else [value]:
                if not entry or backend.run_docx_extractions.get_youtube_video_id(str(entry)):
                    continue
                # Unspecified extractor defaults are relative to its installed module.
                base = repo_root / 'procurement/video_sampling' if action.dest == 'extractor' else repo_root
                (outputs if action.dest in NATIVE_OUTPUTS else inputs).add(str(_path(entry, base)))
        elif action.dest == 'dictionary':
            inputs.update(str(_path(v[5:], repo_root)) for v in value or [] if v.startswith('file:'))
        elif action.dest == 'analysis_profile_json' and value:
            inputs.add(str(_path(json.loads(value)['source_manifest']['path'], repo_root)))
    if engine == 'docx-sampling' and not parsed.output:
        source = Path(parsed.docx_path)
        outputs.add(str(source.with_name(source.stem + '_with_extraction_links.docx')))
    return {'input_paths': sorted(inputs), 'output_paths': sorted(outputs)}


def _read_text_config(filename):
    with filename.open('rb') as handle:
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValidationError('Text config exceeds 1 MiB')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValidationError('Text config must be an object')
    from processing.text_analysis.pipeline import load_text_processing_config
    load_text_processing_config(filename)
    return value, hashlib.sha256(raw).hexdigest()


def _native_text_config(args, workspace, dry_run):
    """Bind config-contained paths to that config and copy only into job storage."""
    args = list(args)
    for index in range(len(args) - 1, -1, -1):
        token = args[index]
        if token == '--config' or token.startswith('--config='):
            filename = Path(args[index + 1] if token == '--config' else token.partition('=')[2])
            config, digest = _read_text_config(filename)
            for key in ('input_path', 'whisper_root', 'selected_whisper_root', 'prepared_root', 'selected_csv_root', 'extra_csv_root', 'postprocessing_root'):
                if key in config:
                    config[key] = str(_path(config[key], filename.parent))
            if 'dictionaries' in config:
                config['dictionaries'] = ['file:' + str(_path(v[5:], filename.parent)) if v.startswith('file:') else v for v in config['dictionaries']]
            target = workspace / 'text_native_config.json'
            if not dry_run:
                workspace.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            if token == '--config':
                args[index + 1] = str(target)
            else:
                args[index] = '--config=' + str(target)
            inputs = [str(filename)]
            if config.get('input_path'):
                inputs.append(config['input_path'])
            inputs.extend(v[5:] for v in config.get('dictionaries', []) if v.startswith('file:'))
            return args, {'text_config_source': str(filename), 'text_config_sha256': digest, 'config_input_paths': inputs}
    return args, {}


def build_stage(stage: str, options: dict, native_options: dict, *, base_dir: Path,
                repo_root: Path, python_executable: str, workspace: Path, dry_run: bool = False) -> StagePlan:
    validate_stage_options(stage, options, native_options)
    try:
        return _build(stage, dict(options), dict(native_options), base_dir=_path(base_dir, Path.cwd()),
                      repo_root=repo_root, python_executable=python_executable, workspace=workspace, dry_run=dry_run)
    except (ValueError, TypeError, OSError, KeyError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(str(exc)) from exc


def _build(stage, options, native_options, *, base_dir, repo_root, python_executable, workspace, dry_run):
    if not options.get('output_root'):
        raise ValidationError('output_root is required (the workflow supplies a default)')
    output = _path(options['output_root'], base_dir)
    if stage.startswith('native.'):
        engine = stage[7:]
        parser = _native_parser(engine, repo_root)
        _parse_native(engine, options['args'], repo_root, parser=parser)
        args = _native_paths(parser, options['args'], base_dir)
        parsed = _parse_native(engine, args, repo_root, parser=parser)
        output_names = ('speaker_output_root',) if engine == 'docx-sampling' else ('run_root', 'output_root', 'output')
        actual = next((getattr(parsed, name, None) for name in output_names if getattr(parsed, name, None) is not None), None)
        if not any(arg.partition('=')[0] in tuple('--' + name.replace('_', '-') for name in output_names) for arg in args) or actual is None or _path(actual, base_dir) != output:
            raise ValidationError('Native args must explicitly select the same output directory as output_root')
        details = {'native_engine': engine, **_native_path_contract(parser, parsed, engine, output, repo_root)}
        if engine == 'text':
            args, config_details = _native_text_config(args, workspace, dry_run)
            details.update(config_details)
            details['input_paths'] = sorted(set(details['input_paths']) | set(details.pop('config_input_paths', [])))
        return StagePlan([python_executable, '-m', NATIVE[engine][0], *args], output, details)
    model = MODELS[stage]
    hints = get_type_hints(model)
    raw_source = options.get('source_path', '')
    youtube_id = backend.run_docx_extractions.get_youtube_video_id(raw_source) if raw_source else None
    values = {key: value if stage == 'procurement' and youtube_id and key == 'source_path'
              else _convert(value, hints[key], base_dir) for key, value in options.items()}
    if stage == 'text' and 'dictionaries' in values:
        values['dictionaries'] = tuple('file:' + str(_path(v[5:], base_dir)) if v.startswith('file:') else v for v in values['dictionaries'])
    values['output_root'] = output
    inputs = {str(value) for name, value in values.items() if name != 'output_root' and isinstance(value, Path)}
    if youtube_id:
        inputs.discard(str(values.get('source_path')))
    inputs.update(str(modality.source_path) for modality in values.get('modalities', ()))
    inputs.update(value[5:] for value in values.get('dictionaries', ()) if value.startswith('file:'))
    if isinstance(options.get('analysis_profile'), str):
        inputs.add(str(_path(options['analysis_profile'], base_dir)))
    details = {}
    builder_root = repo_root
    if stage == 'procurement':
        values.setdefault('mode', 'standard')
        if values.get('segment_expected_source') and not backend.run_docx_extractions.get_youtube_video_id(values['segment_expected_source']):
            values['segment_expected_source'] = str(_path(values['segment_expected_source'], base_dir))
        scan_source = raw_source if youtube_id else values.get('source_path')
        if scan_source is None:
            raise ValidationError('source_path is required')
        scan = backend.scan_input_source(str(scan_source), enrich_youtube=not dry_run)
        inputs.update(str(_path(item.source_path, base_dir)) for item in scan.sources
                      if item.source_path and not backend.run_docx_extractions.get_youtube_video_id(item.source_path))
        _bind_catalog(values, scan, 'selected_ids')
        if youtube_id:
            builder_root = workspace
            values['internal_youtube_source'] = True
            values['source_path'] = _path(workspace / '_local' / 'youtube_sources' / f'youtube_{youtube_id}.docx', base_dir)
            details['youtube_materialization'] = str(values['source_path'])
            if not dry_run:
                values['source_path'] = backend.prepare_source_for_run(raw_source, workspace)
        if values['mode'] == 'manual':
            _focus(values, scan, workspace, dry_run, str(scan_source))
    elif stage in ('audio', 'face', 'text'):
        if 'source_path' not in values:
            raise ValidationError('source_path is required')
        source = values['source_path']
        if not source.exists():
            raise ValidationError(f'Source does not exist: {source}')
        scan = backend.scan_audio_catalog_run(source) if source.is_dir() else None
        _bind_catalog(values, scan, 'selected_source_ids')
        if stage == 'audio':
            values.setdefault('mode', 'batch' if source.is_dir() else 'single')
    if stage == 'analysis' and 'profile_options' in native_options:
        from analysis.profile import profile_from_payload
        context = backend.discover_analysis_profile_context(values['modalities'])
        values['analysis_profile'] = profile_from_payload(_profile_payload(native_options.pop('profile_options'), context['sourceManifest'], context['sourceManifestSha256']))
        details.update(source_manifest=context['sourceManifest'], source_manifest_sha256=context['sourceManifestSha256'])
    request = model(**values)
    if values.get('analysis_profile') is not None:
        inputs.add(str(values['analysis_profile'].source_manifest))
    command = BUILDERS[stage](request, repo_root=builder_root, python_executable=Path(python_executable))
    for name, value in native_options.items():
        if name == 'config':
            value = _path(value, base_dir)
            config, digest = _read_text_config(value)
            if set(config) - {'language_policy'}:
                raise ValidationError('Ordinary Text native config may supply language_policy only; use ordinary request options or native.text for complete native JSON config control')
            details.update(text_config_source=str(value), text_config_sha256=digest)
        elif ADVANCED[stage][name] is Path:
            value = _path(value, base_dir)
        if isinstance(value, Path):
            inputs.add(str(value))
        flag = '--' + name.replace('_', '-')
        if type(value) is bool:
            if value:
                command.append(flag)
        else:
            command.extend([flag, str(value)])
    if native_options:
        engine = stage
        if stage == 'procurement':
            engine = 'catalog' if '--run-root' in command else 'clean-speaker' if request.mode == 'clean-speaker-beta' else 'focus' if request.mode == 'manual' else 'local'
        _parse_native(engine, command[3:], repo_root)
    if '--run-root' in command:
        output = Path(command[command.index('--run-root') + 1])
    # Procurement/audio builders historically resolve paths. Restore lexical
    # spelling so native ownership/reparse checks see the supplied path.
    path_fields = ('source_path', 'output_root', 'segment_manifest', 'beta_reference_audio')
    replacements = {str(v.resolve()): str(v) for k in path_fields if isinstance((v := values.get(k)), Path)}
    command = [replacements.get(token, token) for token in command]
    outputs = {str(output)}
    for index, token in enumerate(command[:-1]):
        if token in {'--output', '--download-root'}:
            outputs.add(command[index + 1])
    details.update(input_paths=sorted(inputs), output_paths=sorted(outputs))
    return StagePlan(command, output, details)
