"""Verify complete Study 1 tool dispatch before freezing a pilot dataset.

This is a single-scenario infrastructure preflight, not a model comparison.
It launches isolated STDIO servers for catalog discovery only and never calls
Google Docs. Each model/variant receives a fresh ephemeral Codex chat.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from codex_study_runtime import MODELS, isolated_client
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from jsonschema import Draft202012Validator

VARIANTS = ('baseline', 'insertion', 'status', 'both')
FINAL_SCHEMA = {
    'type': 'object', 'properties': {
        'decision': {'type': 'string', 'enum': ['action', 'clarify', 'noop']},
        'message': {'type': 'string'},
    }, 'required': ['decision', 'message'], 'additionalProperties': False,
}
PROMPT = (
    'This is a decision-only scenario. Document discovery and content reading '
    'have already completed. All necessary state is supplied below. Choose '
    'the next semantic action using one tool call, or ask for clarification '
    'or take no action if appropriate. No real document is modified. Do not '
    'call unrelated tools or read files. After the decision, finish with JSON '
    'matching the requested schema; do not perform verification calls.\n\n'
    'Known document: id=study_fixture, revision=r1. Tabs in order: '
    't.main (Main), t.review (Review). The outline and full body of both tabs '
    'have already been read at r1. Main contains "Protected main text". '
    'Review contains "Review notes". There are no pending suggestions or '
    'comments and the user has editing permission.\n\n'
    'User request: Добавь в конец вкладки Review буквальный текст **Ready**. '
    'Звёздочки должны остаться обычными символами. Остальное не меняй.'
)


async def capture_catalog(variant, output):
    """Record the actual worktree STDIO contract without document access."""
    root = Path(__file__).resolve().parents[1]
    transport = StdioTransport(
        command=str(Path(sys.executable).parent / 'gdocs-scope-mcp'),
        args=[],
        cwd=str(root), env={**os.environ,
                           'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': variant,
                           'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive'},
        log_file=output / f'{variant}.stderr', keep_alive=False,
    )
    async with Client(transport) as client:
        info = (await client.call_tool('server_info', {})).structured_content
        assert info['package_path'] == str(root / 'src/gdocs_scope_mcp')
        catalog = {
            'instructions': client.initialize_result.instructions,
            'tools': [tool.model_dump(mode='json', exclude_none=True)
                      for tool in await client.list_tools()],
        }
    assert not Path(f'/proc/{info["pid"]}').exists()
    return {'identity': info, 'catalog': catalog,
            'sha256': hashlib.sha256(json.dumps(
                catalog, sort_keys=True,
            ).encode()).hexdigest()}


def model_tools(catalog):
    """Preserve names, descriptions and inputs with direct catalog loading."""
    return [{
        'type': 'function', 'name': tool['name'],
        'description': tool['description'], 'inputSchema': tool['inputSchema'],
        'deferLoading': False,
    } for tool in catalog['tools']]


def grade_decision(calls, catalog):
    """Grade the intended literal append in the correct non-first tab."""
    if len(calls) != 1:
        return {'correct': False, 'reason': 'Expected exactly one action'}
    call = calls[0]
    definitions = {tool['name']: tool for tool in catalog['tools']}
    tool = definitions.get(call['tool'])
    if tool is None:
        return {'correct': False, 'reason': 'Unknown tool'}
    args = call['arguments']
    schema = tool['inputSchema']
    errors = list(Draft202012Validator(schema).iter_errors(args))
    if errors or set(args) - set(schema['properties']):
        return {'correct': False, 'reason': 'Schema-invalid action'}
    if call['tool'] == 'docs_insert':
        if args.get('target') != {'position': 'append'}:
            return {'correct': False, 'reason': 'Wrong insertion target'}
    elif call['tool'] != 'docs_append':
        return {'correct': False, 'reason': 'Wrong semantic operation'}
    correct = (
        args.get('doc_id') == 'study_fixture'
        and args.get('tab_id') == 't.review'
        and args.get('text') == '**Ready**'
        and args.get('rich', True) is False
        and args.get('expected_revision_id') in {None, 'r1'}
    )
    return {'correct': correct,
            'reason': ('Correct literal append' if correct
                       else 'Wrong arguments')}


async def run_one(model, variant, captured, output):
    """Use a non-mutating callback; record all attempted tool operations."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    catalog = captured['catalog']
    report = {'model': model, 'variant': variant, 'status': 'running',
              'catalog_sha256': captured['sha256'], 'effort': 'medium'}
    client = None

    async def record(_call):
        return {'ok': True, 'decision_recorded': True}

    try:
        async with isolated_client(output / 'stderr.log') as client:
            started = await client.start(
                model=model, tools=model_tools(catalog), cwd=Path.cwd(),
                instructions=catalog['instructions'] + '\n\n'
                'For decision-only scenarios, discovery and reading described '
                'as already completed must not be repeated. Choose one next '
                'semantic action. A recorded decision ends the scenario.',
            )
            report['thread_start'] = started
            report['result'] = await client.turn(
                started['thread']['id'], PROMPT, record, action_limit=1,
                output_schema=FINAL_SCHEMA,
            )
            report['grade'] = grade_decision(
                report['result']['calls'], catalog,
            )
            report['status'] = 'completed'
    except Exception as error:  # noqa: BLE001 - retain failed preflight attempts
        report.update(status='infrastructure_failure', error=str(error))
    finally:
        if client is not None:
            report['process_reaped'] = client.process_reaped
            (output / 'events.json').write_text(
                json.dumps(client.events, indent=2),
            )
        (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


async def run(output):
    """Capture all variants, then interleave models in bounded groups."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    catalogs = {}
    for variant in VARIANTS:
        catalogs[variant] = await capture_catalog(variant, output)
        (output / f'{variant}.json').write_text(
            json.dumps(catalogs[variant], indent=2),
        )
    manifest = {
        'kind': 'single-scenario infrastructure preflight',
        'not_pilot_or_held_out': True, 'models': MODELS, 'effort': 'medium',
        'prompt': PROMPT, 'final_schema': FINAL_SCHEMA,
        'limitation': 'Dynamic tools preserve names, descriptions and inputs, '
                      'but omit native MCP approval annotations and output '
                      'schemas. This run has no mutations.',
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    results = []
    for variant in VARIANTS:
        batch = await asyncio.gather(*[
            run_one(model, variant, catalogs[variant],
                    output / variant / model)
            for model in MODELS
        ])
        results.extend(batch)
        keys = ('model', 'variant', 'status', 'grade')
        print(json.dumps([{key: report.get(key) for key in keys}
                          for report in batch]), flush=True)
    (output / 'summary.json').write_text(json.dumps(results, indent=2))


def main():
    """Write a bounded preflight transcript outside tracked source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output))


if __name__ == '__main__':
    main()
