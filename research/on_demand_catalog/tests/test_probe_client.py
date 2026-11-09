"""Check exposure parity and pre-inference authorization boundaries."""

import asyncio
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

PATH = Path(__file__).parents[1] / 'probe_client.py'
SPEC = importlib.util.spec_from_file_location('on_demand_probe', PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_loading_policy_keeps_interfaces_identical():
    """Only eager/deferred exposure may vary, never a callable definition."""
    catalog = {'tools': [
        {'name': name, 'description': 'Synthetic capability',
         'inputSchema': {'type': 'object'}}
        for name in (*probe.CORE, 'docs_get_color_palette')
    ]}
    untouched = deepcopy(catalog)
    eager = probe.model_tools(catalog, 'eager')
    deferred = probe.model_tools(catalog, 'deferred')
    assert catalog == untouched
    assert not any(t['deferLoading'] for t in eager)
    assert [t['name'] for t in deferred if t['deferLoading']] == [
        'docs_get_color_palette',
    ]
    for left, right in zip(eager, deferred, strict=True):
        left.pop('deferLoading')
        right.pop('deferLoading')
        assert left == right
    with pytest.raises(ValueError, match='Unknown loading arm'):
        probe.model_tools(catalog, 'unknown')


def test_cli_run_requires_explicit_six_session_opt_in(tmp_path):
    """An accidental run command cannot start a model or reserve a trial."""
    result = subprocess.run(
        [sys.executable, str(PATH), 'run', '--output', str(tmp_path)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert 'explicit --authorized-sessions 6' in result.stderr
    assert not (tmp_path / 'ledger.json').exists()


def test_canary_permissions_and_product_identity():
    """A discovered tool must not allow document access or malformed calls."""
    definitions = {'server_info': {'inputSchema': {
        'type': 'object', 'additionalProperties': False,
    }}}
    assert probe.validate_call({'tool': 'server_info', 'arguments': {}},
                               definitions) == ('server_info', {})
    for name in ('docs_read', 'docs_insert', 'docs_delete_comment'):
        with pytest.raises(ValueError, match='permission scope'):
            probe.validate_call({'tool': name, 'arguments': {}}, definitions)
    with pytest.raises(ValidationError):
        probe.validate_call({'tool': 'server_info', 'arguments': {'bad': 1}},
                            definitions)
    with pytest.raises(ValueError, match='Product source changed'):
        probe.verify_identity({'source_fingerprint': 'new'},
                              {'source_fingerprint': 'frozen'})


def test_resume_skips_every_prior_reservation(monkeypatch, tmp_path):
    """Even a failed canary is never silently replaced on resume."""
    jobs = [{'id': str(i)} for i in range(probe.CAP)]
    manifest = {'session_cap': probe.CAP, 'sources': {},
                'schedule': jobs, 'catalog': {'tools': []}}
    probe.write_json(tmp_path / 'manifest.json', manifest)
    (tmp_path / 'manifest.sha256').write_text(probe.digest(manifest))
    probe.write_json(tmp_path / 'ledger.json', {
        'cap': probe.CAP,
        'attempts': [{**j, 'status': 'failed'} for j in jobs],
    })

    def forbidden():
        raise AssertionError('No new runtime is allowed')

    monkeypatch.setattr(probe, 'runtime', forbidden)
    asyncio.run(probe.run(tmp_path))
    ledger = json.loads((tmp_path / 'ledger.json').read_text())
    assert len(ledger['attempts']) == probe.CAP
