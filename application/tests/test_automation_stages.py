from dataclasses import fields
from pathlib import Path
import json

import pytest

from application import backend
from application.automation.stages import build_stage, stage_schema, validate_stage_options
from application.automation.stages import NATIVE, _native_parser
from application.automation import stages
from application.automation.errors import ValidationError


@pytest.mark.parametrize('stage,model', [('procurement', backend.RunRequest), ('audio', backend.AudioRunRequest), ('face', backend.FaceProcessingRunRequest), ('text', backend.TextProcessingRunRequest), ('analysis', backend.AnalysisWorkflowRunRequest)])
def test_schema_covers_gui_fields(stage, model):
    assert set(stage_schema()[stage]['properties']) == {f.name for f in fields(model)} - {'internal_youtube_source', 'detected_video_source'}


@pytest.mark.parametrize('value', [True, '8', 1.5, float('inf'), float('nan')])
def test_strict_integer(value):
    with pytest.raises(ValidationError):
        validate_stage_options('face', {'source_path': 'video.mp4', 'batch_size': value}, {})


@pytest.mark.parametrize('options', [{'debug': 1}, {'sample_fps': float('nan')}, {'source_path': 42}, {'selected_source_ids': ['ok', 4]}, {'internal_youtube_source': True}, {'unknown': 'x'}])
def test_strict_options(options):
    with pytest.raises(ValidationError):
        validate_stage_options('face', options, {})


def test_face_command_preserves_gui_defaults_and_native_run_id(tmp_path):
    source = tmp_path / 'movie.mp4'
    source.write_bytes(b'fixture')
    plan = build_stage('face', {'source_path': 'movie.mp4', 'output_root': 'out', 'recursive': False}, {'run_id': 'trial'}, base_dir=tmp_path, repo_root=Path(__file__).parents[2], python_executable='python', workspace=tmp_path / 'stage', dry_run=True)
    assert plan.command[:4] == ['python', '-m', 'processing.face_analysis', str(source)]
    assert '--no-recursive' in plan.command
    assert plan.command[plan.command.index('--batch-size') + 1] == '8'
    assert plan.command[-2:] == ['--run-id', 'trial']
    assert plan.output_root == tmp_path / 'out'
    assert not (tmp_path / 'out').exists()


def test_native_parser_rejects_bad_choice(tmp_path):
    with pytest.raises(ValidationError):
        build_stage('native.face', {'args': ['input.mp4', '--device', 'bogus'], 'output_root': 'out'}, {}, base_dir=tmp_path, repo_root=Path(__file__).parents[2], python_executable='python', workspace=tmp_path / 'stage', dry_run=True)


@pytest.mark.parametrize('engine', NATIVE)
def test_every_native_parser_constructs_without_loading_models(engine):
    assert _native_parser(engine, Path(__file__).parents[2])._actions


def make_plan(tmp_path, stage, options, native=None, dry_run=True):
    return build_stage(stage, options, native or {}, base_dir=tmp_path, repo_root=Path(__file__).parents[2], python_executable='python', workspace=tmp_path / 'stage', dry_run=dry_run)


@pytest.mark.parametrize('stage,options,expected', [
    ('audio', {'include_emotions': False, 'debug': True, 'window_seconds': 4.0}, ['--skip-emotion-models', '--debug']),
    ('text', {'whisper_model': 'tiny', 'threads': 2, 'all_categories': True, 'write_graphs': False, 'force_rocksteady': True}, ['--all-categories', '--no-graphs', '--force-rocksteady']),
    ('face', {'overwrite': True, 'recursive': False, 'device': 'cpu'}, ['--overwrite', '--no-recursive']),
])
def test_processing_gui_mappings(tmp_path, stage, options, expected):
    (tmp_path / 'input.mp4').write_bytes(b'fixture')
    options.update(source_path='input.mp4', output_root='out')
    plan = make_plan(tmp_path, stage, options)
    assert all(flag in plan.command for flag in expected)
    assert str(tmp_path / 'input.mp4') in plan.command


def test_analysis_modality_and_groups_are_domain_requests(tmp_path):
    plan = make_plan(tmp_path, 'analysis', {'output_root': 'out', 'modalities': [{'name': 'audio', 'source_method': 'import', 'source_path': 'reports'}], 'speaker_groups': [{'group_id': 'g1', 'name': 'All', 'speaker_ids': ['Alice']}], 'confidence_level': .9, 'write_graphs': False})
    assert plan.command[:3] == ['python', '-m', 'analysis.workflow']
    assert plan.command[plan.command.index('--audio-source') + 1] == str(tmp_path / 'reports')
    assert '--no-graphs' in plan.command


def test_native_paths_are_config_relative(tmp_path):
    plan = make_plan(tmp_path, 'native.face', {'args': ['input.mp4', '--output-root=out', '--run-id', 'trial'], 'output_root': 'out'})
    assert str(tmp_path / 'input.mp4') in plan.command
    assert '--output-root=' + str(tmp_path / 'out') in plan.command
    assert plan.command[-2:] == ['--run-id', 'trial']


def test_native_output_handoff_must_match(tmp_path):
    with pytest.raises(ValidationError, match='same output'):
        make_plan(tmp_path, 'native.face', {'args': ['input.mp4', '--output-root', 'different'], 'output_root': 'out'})


def scan_fixture(tmp_path, monkeypatch, catalog=False):
    source = tmp_path / 'movie.mp4'
    source.write_bytes(b'fixture')
    item = backend.VideoItem('source-0001', 'Movie', 'Alice', str(source), 'file', duration_seconds=10.0, source_id='source-0001')
    scan = backend.ScanResult(str(tmp_path / 'catalog.csv') if catalog else str(source), 'catalog' if catalog else 'file', [backend.SpeakerGroup('Alice', [item])], sources=[item] if catalog else [], catalog_sha256='a' * 64 if catalog else '')
    monkeypatch.setattr(backend, 'scan_input_source', lambda *a, **kw: scan)
    return source, item, scan


def test_catalog_defaults_selection_and_reports_generated_run_root(tmp_path, monkeypatch):
    scan_fixture(tmp_path, monkeypatch, catalog=True)
    plan = make_plan(tmp_path, 'procurement', {'source_path': 'catalog.csv', 'output_root': 'out', 'mode': 'full'})
    assert plan.output_root == Path(plan.command[plan.command.index('--run-root') + 1])
    assert plan.output_root.parent == tmp_path / 'out'
    assert plan.command[plan.command.index('--source-id') + 1] == 'source-0001'
    assert plan.command[plan.command.index('--catalog-sha256') + 1] == 'a' * 64


@pytest.mark.parametrize('extra', [{'catalog_sha256': 'b' * 64}, {'selected_ids': []}, {'selected_ids': ['unknown']}])
def test_catalog_selection_is_freshly_bound(tmp_path, monkeypatch, extra):
    scan_fixture(tmp_path, monkeypatch, catalog=True)
    with pytest.raises(ValidationError):
        make_plan(tmp_path, 'procurement', {'source_path': 'catalog.csv', 'output_root': 'out', **extra})


@pytest.mark.parametrize('end', [3.0, 11.0])
def test_focus_checks_scanned_duration_before_writes(tmp_path, monkeypatch, end):
    source, item, scan = scan_fixture(tmp_path, monkeypatch)
    manifest = {'source_path': str(source), 'source_kind': 'file', 'gap_seconds': 1, 'selected_segments': [{'source_path': str(source), 'source_kind': 'file', 'speaker': 'Alice', 'start_seconds': 1, 'end_seconds': end}]}
    (tmp_path / 'focus.json').write_text(json.dumps(manifest), encoding='utf-8')
    options = {'source_path': 'movie.mp4', 'output_root': 'out', 'mode': 'manual', 'segment_manifest': 'focus.json'}
    if end > 10:
        with pytest.raises(ValidationError, match='duration'):
            make_plan(tmp_path, 'procurement', options, dry_run=False)
        assert not (tmp_path / 'stage').exists()
    else:
        plan = make_plan(tmp_path, 'procurement', options)
        assert '--manifest-sha256' in plan.command
        assert not (tmp_path / 'stage').exists()
        execution = make_plan(tmp_path, 'procurement', options, dry_run=False)
        assert (tmp_path / 'stage' / 'focus_segments.json').is_file()
        assert execution.command == plan.command


def test_youtube_dry_run_does_not_materialize(tmp_path, monkeypatch):
    scan = backend.ScanResult('https://www.youtube.com/watch?v=abcdefghijk', 'youtube', [])
    monkeypatch.setattr(backend, 'scan_input_source', lambda *a, **kw: scan)
    monkeypatch.setattr(backend, 'prepare_source_for_run', lambda *a, **kw: pytest.fail('Dry run materialized YouTube'))
    plan = make_plan(tmp_path, 'procurement', {'source_path': scan.source_path, 'output_root': 'out'})
    assert 'youtube_materialization' in plan.details
    assert not (tmp_path / 'stage').exists()


def test_native_text_config_is_normalized_private_and_dry_run_read_only(tmp_path):
    config = tmp_path / 'custom.json'
    config.write_text(json.dumps({'input_path': 'media', 'dictionaries': ['file:custom.dic']}), encoding='utf-8')
    original = config.read_bytes()
    options = {'args': ['--config', 'custom.json', '--output-root', 'out'], 'output_root': 'out'}
    plan = make_plan(tmp_path, 'native.text', options)
    assert not (tmp_path / 'stage').exists()
    executed = make_plan(tmp_path, 'native.text', options, dry_run=False)
    assert executed.command == plan.command
    normalized = json.loads((tmp_path / 'stage' / 'text_native_config.json').read_text(encoding='utf-8'))
    assert normalized['input_path'] == str(tmp_path / 'media')
    assert normalized['dictionaries'] == ['file:' + str(tmp_path / 'custom.dic')]
    assert config.read_bytes() == original


def test_ordinary_text_dictionary_paths_and_conflicting_native_config(tmp_path):
    (tmp_path / 'movie.mp4').write_bytes(b'fixture')
    options = {'source_path': 'movie.mp4', 'output_root': 'out', 'dictionaries': ['file:custom.dic']}
    plan = make_plan(tmp_path, 'text', options)
    assert 'file:' + str(tmp_path / 'custom.dic') in plan.command
    (tmp_path / 'config.json').write_text(json.dumps({'write_graphs': False}), encoding='utf-8')
    with pytest.raises(ValidationError, match='language_policy only'):
        make_plan(tmp_path, 'text', options, {'config': 'config.json'})


@pytest.mark.parametrize('mutate', ['foreign', 'overlap', 'hash', 'speaker'])
def test_focus_rejects_untrusted_selection_before_write(tmp_path, monkeypatch, mutate):
    source, _, _ = scan_fixture(tmp_path, monkeypatch)
    segment = {'source_path': 'movie.mp4', 'source_kind': 'file', 'speaker': 'Alice', 'start_seconds': 1, 'end_seconds': 3}
    payload = {'source_path': 'movie.mp4', 'source_kind': 'file', 'selected_segments': [segment]}
    options = {'source_path': 'movie.mp4', 'output_root': 'out', 'mode': 'manual', 'segment_manifest': 'focus.json'}
    if mutate == 'foreign':
        segment['source_path'] = 'foreign.mp4'
    elif mutate == 'overlap':
        payload['selected_segments'].append(dict(segment))
    elif mutate == 'hash':
        options['segment_manifest_sha256'] = 'a' * 64
    else:
        options['selected_speakers'] = ['Bob']
    (tmp_path / 'focus.json').write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValidationError):
        make_plan(tmp_path, 'procurement', options, dry_run=False)
    assert not (tmp_path / 'stage').exists()


def test_analysis_automatic_profile_binds_fresh_context(tmp_path, monkeypatch):
    captured = []
    def discover(modalities):
        assert modalities[0].source_path == tmp_path / 'reports'
        return {'sourceManifest': str(tmp_path / 'fresh_manifest.json'), 'sourceManifestSha256': 'b' * 64}
    def builder(request, **kwargs):
        captured.append(request)
        return ['python', '-m', 'analysis.workflow', '--output-root', str(request.output_root)]
    monkeypatch.setattr(backend, 'discover_analysis_profile_context', discover)
    monkeypatch.setitem(stages.BUILDERS, 'analysis', builder)
    options = {'output_root': 'out', 'modalities': [{'name': 'audio', 'source_method': 'import', 'source_path': 'reports'}]}
    plan = make_plan(tmp_path, 'analysis', options, {'profile_options': {'automatic_group_field': 'Country', 'sort_fields': ['Country']}})
    assert captured[0].analysis_profile.automatic_group_field == 'Country'
    assert captured[0].analysis_profile.source_manifest_sha256 == 'b' * 64
    assert plan.details['source_manifest_sha256'] == 'b' * 64


@pytest.mark.parametrize('profile', [{'unknown': True}, {'sort_fields': [42]}, {'metadata_filters': {'Country': 'Ireland'}}])
def test_profile_options_strict(profile):
    with pytest.raises(ValidationError):
        validate_stage_options('analysis', {'modalities': []}, {'profile_options': profile})


def test_profile_options_conflicts_with_legacy_groups():
    with pytest.raises(ValidationError, match='mutually exclusive'):
        validate_stage_options('analysis', {'modalities': [], 'speaker_groups': [{'group_id': 'g', 'name': 'All', 'speaker_ids': ['a']}]}, {'profile_options': {}})


@pytest.mark.parametrize('secret_args', [['--api-key', 'DUMMY_PRIVATE'], ['--api-key=DUMMY_PRIVATE'], ['--sample-arg=--api-key=DUMMY_PRIVATE'], ['--full-video-arg', '--password=DUMMY_PRIVATE']])
def test_credentials_rejected_before_job_persistence(tmp_path, secret_args):
    from application.automation.config import load_job
    job = tmp_path / 'job.json'
    job.write_text(json.dumps({'schema_version': 1, 'stage': 'native.pipeline', 'options': {'output_root': 'out', 'args': ['source.docx', '--output-root', 'out', *secret_args]}}), encoding='utf-8')
    with pytest.raises(ValidationError) as error:
        load_job(job)
    assert 'DUMMY_PRIVATE' not in str(error.value)
    assert list(tmp_path.iterdir()) == [job]


@pytest.mark.parametrize('flag', ['--single-video-json', '--child-run-root', '--child-result-json', '--child-index', '--child-total'])
def test_native_internal_child_flags_rejected_before_build(flag):
    with pytest.raises(ValidationError):
        validate_stage_options('native.clean-speaker', {'args': [flag, 'value'], 'output_root': 'out'}, {})


def test_native_subcommand_named_input_and_option_terminator(tmp_path):
    plan = make_plan(tmp_path, 'native.audio', {'args': ['batch', 'batch', '--output', 'out'], 'output_root': 'out'})
    assert plan.command[3:5] == ['batch', str(tmp_path / 'batch')]
    plan = make_plan(tmp_path, 'native.face', {'args': ['--output-root', 'out', '--', '-input.mp4'], 'output_root': 'out'})
    assert plan.command[-2:] == ['--', str(tmp_path / '-input.mp4')]


@pytest.mark.parametrize('inline', [False, True])
def test_native_advanced_paths_and_output_contract(tmp_path, inline):
    profile = {'format_version': 1, 'source_manifest': {'path': 'manifest.json', 'sha256': 'a' * 64}, 'automatic_group_field': None, 'sort_fields': [], 'manual_groups': [], 'metadata_filters': {}}
    extra = ['--analysis-profile-json=' + json.dumps(profile)] if inline else ['--analysis-profile-json', json.dumps(profile)]
    plan = make_plan(tmp_path, 'native.analysis', {'args': ['--output-root', 'out', '--audio-source', 'reports', '--audio-method', 'import', *extra], 'output_root': 'out'})
    from analysis.workflow import request_from_cli
    assert request_from_cli(plan.command[3:]).analysis_profile.source_manifest == tmp_path / 'manifest.json'
    assert str(tmp_path / 'manifest.json') in plan.details['input_paths']
    extra = ['--extractor=custom.py', '--output=job.json'] if inline else ['--extractor', 'custom.py', '--output', 'job.json']
    plan = make_plan(tmp_path, 'native.docx-sampling', {'args': ['source.docx', '--speaker-output-root', 'out', *extra], 'output_root': 'out'})
    assert str(tmp_path / 'job.json') in plan.details['output_paths']
    assert str(tmp_path / 'custom.py') in plan.details['input_paths']
    assert str(tmp_path / 'source.docx') in plan.details['input_paths']


def test_native_default_docx_output_is_reported(tmp_path):
    plan = make_plan(tmp_path, 'native.docx-sampling', {'args': ['source.docx', '--speaker-output-root', 'out'], 'output_root': 'out'})
    assert str(tmp_path / 'source_with_extraction_links.docx') in plan.details['output_paths']


def test_path_adapter_calls_guard_before_normalization(tmp_path, monkeypatch):
    from application.automation import config
    def guard(value, base_dir):
        assert str(value).replace('\\', '/').endswith('alias/../input.mp4')
        raise ValidationError('guard observed alias before normalization')
    monkeypatch.setattr(config, 'absolute_path', guard)
    with pytest.raises(ValidationError, match='observed alias'):
        stages._path('alias/../input.mp4', tmp_path)


def test_real_windows_junction_dotdot_rejected(tmp_path):
    import sys
    if sys.platform != 'win32':
        pytest.skip('Windows junction regression')
    import _winapi
    target = tmp_path / 'target'
    target.mkdir()
    _winapi.CreateJunction(str(target), str(tmp_path / 'alias'))
    with pytest.raises((ValidationError, ValueError), match='junction|reparse|symbolic'):
        make_plan(tmp_path, 'native.local', {'args': ['--source', 'alias/../input.mp4', '--mode', 'full', '--output-root', 'out'], 'output_root': 'out'})


@pytest.mark.parametrize('flag', ['--extractor-arg=--output=job.json', '--sample-arg=--download-root=job.json', '--full-video-arg=--output=job.json'])
def test_nested_output_controls_rejected_before_persistence(flag):
    with pytest.raises(ValidationError, match='forwarding'):
        validate_stage_options('native.pipeline', {'args': ['source.docx', '--output-root', 'out', flag], 'output_root': 'out'}, {})


def test_native_pipeline_auxiliary_output_and_input_config(tmp_path):
    plan = make_plan(tmp_path, 'native.pipeline', {'args': ['source.docx', '--output-root', 'out', '--download-root', 'separate', '--config', 'settings.env', '--audited-docx', 'audited.docx'], 'output_root': 'out'})
    assert str(tmp_path / 'separate') in plan.details['output_paths']
    assert {str(tmp_path / 'source.docx'), str(tmp_path / 'settings.env'), str(tmp_path / 'audited.docx')} <= set(plan.details['input_paths'])


def test_native_schema_allows_coordinator_injected_output_root():
    assert stage_schema()['native.face']['required'] == ['args']
    validate_stage_options('native.face', {'args': ['source.mp4', '--output-root', 'out']}, {})
