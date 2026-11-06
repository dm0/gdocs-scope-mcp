"""Prepare and run the explicitly approved, resumable 1080-session study."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import random
import signal
import subprocess
import time
from pathlib import Path

from codex_study_runtime import MODELS, StudyAgentError, isolated_client
from jsonschema import Draft202012Validator
from study_execution import (
    ROOT,
    failure,
    fixture_backend,
    model_state,
    reference_states,
    translated,
)
from study_scenarios import corpus
from terminal_period_adjudication import normalized, permissions
from tool_consolidation_preflight import (
    FINAL_SCHEMA,
    VARIANTS,
    capture_catalog,
    model_tools,
)

SEED = 20261106
CAP = 1080
PRIOR_ATTEMPTS = 241
TOTAL_CAP = 1321
LIVE_CASES = {'m01', 'm08', 'm11', 'm15', 'm20'}
LEVELS = ('decision', 'end_to_end')
EXECUTION_SOURCES = (
    'codex_study_runtime.py', 'tool_consolidation_preflight.py',
    'study_scenarios.py', 'study_fixture_api.py', 'study_fixture_server.py',
    'study_execution.py', 'study_live.py', 'run_reduced_study.py',
    'terminal_period_adjudication.py',
    'adjudications/unquoted-terminal-periods.json',
    '../../tests/probes/table_server.py',
    '../../tests/live_document_state.py',
)
READ_TOOLS = {
    'docs_get_tree', 'docs_read', 'docs_read_comments', 'docs_tabs_list',
}
ENVIRONMENT_FAILURES = {
    'AUTHENTICATION_REQUIRED', 'AUTH_CONFIGURATION_ERROR', 'RATE_LIMITED',
    'QUOTA_EXCEEDED', 'TEMPORARILY_UNAVAILABLE', 'REVISION_UNAVAILABLE',
}
POLICY = (
    'Study permission scope: operate only on the document identified by the '
    'request. Direct text edits, comment status and explicit text color '
    'changes are allowed. Do not create suggestions, external files, uploads, '
    'images, chips or tables, authorize accounts, or access other documents. '
    'The controller enforces these same permissions for every catalog. '
    'Use native tool names and IDs from current reads. Do not access files '
    'or unrelated tools. The final message must describe the result '
    'or ask the user for necessary clarification. '
    'For decision-only tasks, all supplied discovery/reads already happened; '
    'choose the next action, clarification or no-op without repeating them. '
    'A recorded decision ends a decision-only task; do not verify it.'
)


def digest(value):
    """Hash reproducible JSON independently of indentation or key order."""
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    """Persist study data in its owner-private artifact directory."""
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def schedule(stage):
    """Pair models/variants within scenario/level/repeat blocks."""
    blocks = [(case['id'], model, level, repeat)
              for case in corpus(stage) for model in MODELS for level in LEVELS
              for repeat in range(1 if stage == 'pilot' else 2)]
    rng = random.Random(SEED + (0 if stage == 'pilot' else 1))
    rng.shuffle(blocks)
    jobs = []
    for case_id, model, level, repeat in blocks:
        variants = list(VARIANTS)
        rng.shuffle(variants)
        for variant in variants:
            jobs.append({
                'id': (f'restart-001-{stage}-{case_id}-{model}-'
                       f'{level}-{repeat}-{variant}'),
                'stage': stage, 'case': case_id, 'model': model,
                'level': level,
                'repeat': repeat, 'variant': variant,
                'backend': ('live' if stage == 'main' and case_id in LIVE_CASES
                            and level == 'end_to_end' and repeat == 1
                            else 'fixture'),
            })
    return jobs


def source_hashes():
    """Retain the exact executable research source snapshot."""
    return {name: hashlib.sha256((Path(__file__).parent / name).read_bytes())
            .hexdigest() for name in EXECUTION_SOURCES}


def ordered_tools(catalog, case_id, repeat):
    """Counterbalance semantic groups equally across paired variants."""
    tools = model_tools(catalog)
    groups = {}
    for tool in tools:
        name = tool['name']
        group = ('insertion' if name in {'docs_append', 'docs_insert_before',
                                        'docs_insert_after', 'docs_insert'}
                 else 'status' if name in {'docs_resolve_comment',
                                           'docs_reopen_comment',
                                           'docs_comment_status'} else name)
        groups.setdefault(group, []).append(tool)
    seed = int(digest([SEED, case_id, repeat])[:16], 16)
    rng = random.Random(seed)
    keys = sorted(groups)
    rng.shuffle(keys)
    for key, group in groups.items():
        random.Random(seed + int(digest(key)[:16], 16)).shuffle(group)
    return [tool for key in keys for tool in groups[key]]


def prior_checkpoint(directory):
    """Bind the restart budget to the immutable first campaign ledger."""
    directory = directory.resolve()
    ledger_bytes = (directory / 'ledger.json').read_bytes()
    ledger = json.loads(ledger_bytes)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if digest(manifest) != (directory / 'manifest.sha256').read_text().strip():
        raise ValueError('Prior manifest changed')
    if len(ledger['attempts']) != PRIOR_ATTEMPTS:
        raise ValueError('Restart requires the approved 241 prior attempts')
    return {
        'directory': str(directory), 'attempts': len(ledger['attempts']),
        'ledger_sha256': hashlib.sha256(ledger_bytes).hexdigest(),
        'manifest_sha256': digest(manifest),
    }


async def prepare(output, previous):
    """Freeze datasets, catalogs, schedules and reference states."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (output / 'manifest.json').exists():
        raise ValueError('An existing study manifest cannot be overwritten')
    prior = prior_checkpoint(previous)
    if output.resolve() == previous.resolve():
        raise ValueError('Restart must preserve the previous campaign')
    catalogs = {}
    for variant in VARIANTS:
        catalogs[variant] = await capture_catalog(variant, output)
    datasets = {stage: corpus(stage) for stage in ('pilot', 'main')}
    references = {}
    semaphore = asyncio.Semaphore(4)

    async def reference(case):
        async with semaphore:
            references[case['id']] = await reference_states(
                case, 'baseline', output / 'reference' / case['id'],
            )

    await asyncio.gather(*[reference(case) for cases in datasets.values()
                           for case in cases])
    # Native gold is calibrated before model trials, not chosen after outcomes.
    from study_live import native_reference  # noqa: PLC0415
    live_directory = output / 'live-references'
    live_directory.mkdir(mode=0o700)
    live_semaphore = asyncio.Semaphore(3)

    async def calibrate(case):
        async with live_semaphore:
            await native_parity(case)

    async def native_parity(case):
        native = await native_reference(case, live_directory / case['id'])
        require_frozen_source(native['identity'], catalogs['baseline'])
        async with fixture_backend(
            case, 'baseline', output / 'parity' / case['id'],
        ) as (backend, _identity):
            semantic = [await backend.state(semantic=True)]
            for call in case['oracle']:
                await backend.call(translated(call, 'baseline'))
                semantic.append(await backend.state(semantic=True))
        if native['semantic'] != semantic:
            write_json(live_directory / (case['id'] + '-mismatch.json'), {
                'native': native['semantic'], 'fixture': semantic,
            })
            raise RuntimeError(
                'Native fixture parity failed for ' + case['id'],
            )
        write_json(live_directory / (case['id'] + '.json'), native)
        print(json.dumps({'native_parity': case['id'], 'passed': True}),
              flush=True)
    cases = [case for entries in datasets.values() for case in entries]
    results = await asyncio.gather(*(calibrate(c) for c in cases),
                                   return_exceptions=True)
    failures = [{'case': case['id'], 'error': str(result)}
                for case, result in zip(cases, results, strict=True)
                if isinstance(result, BaseException)]
    if failures:
        write_json(output / 'native-conformance-errors.json', failures)
        raise RuntimeError('Native conformance failed: '
                           + json.dumps(failures))
    protocol = (ROOT / 'docs/development/tool-interface-evaluation.md'
                ).read_bytes()
    (output / 'protocol.md').write_bytes(protocol)
    manifest = {
        'version': 2, 'campaign': 'restart-001', 'seed': SEED,
        'session_cap': CAP, 'total_session_cap': TOTAL_CAP, 'prior_run': prior,
        'protocol_sha256': hashlib.sha256(protocol).hexdigest(),
        'models': MODELS, 'effort': 'medium',
        'codex_cli': subprocess.check_output(['codex', '--version'],
                                            cwd=ROOT, text=True).strip(),
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                          cwd=ROOT, text=True).strip(),
        'sources': source_hashes(), 'datasets': datasets,
        'dataset_hashes': {stage: digest(cases)
                           for stage, cases in datasets.items()},
        'catalogs': catalogs, 'references': references,
        'schedules': {stage: schedule(stage) for stage in datasets},
        'policy': POLICY, 'final_schema': FINAL_SCHEMA,
        'budgets': {'domain_calls': 16, 'decision_calls': 1,
                    'turn_seconds': 120, 'output_tokens': 4096,
                    'native_turn_seconds': 240,
                    'scripted_clarifications': 1,
                    'automatic_model_retries': 0},
        'live_cases': sorted(LIVE_CASES),
        'native_conformance_cases': sorted(c['id'] for c in cases),
        'native_document_policy': 'unique disposable document per native job',
        'grading': {
            'primary': 'native state with user-approved optional final period',
            'exact_state': 'retained as a diagnostic',
            'observer_reads': 'initial, after mutating calls and final',
            'prior_outcomes': 'preserved separately, never pooled',
        },
        'decision_criteria': {
            'primary': 'both minus baseline first-action correctness',
            'minimum_effect': 0.03, 'final_success_margin': -0.02,
            'confidence': 0.95, 'bootstrap_clusters': 'scenario family',
            'no_default_adoption_without_human_audit': True,
        },
    }
    write_json(output / 'manifest.json', manifest)
    (output / 'manifest.sha256').write_text(digest(manifest) + '\n')
    write_json(output / 'ledger.json', {
        'attempts': [], 'cap': CAP, 'prior_attempts': prior['attempts'],
        'total_cap': TOTAL_CAP,
    })
    print(json.dumps({'manifest_sha256': digest(manifest),
                      'dataset_hashes': manifest['dataset_hashes'],
                      'pilot_sessions': len(manifest['schedules']['pilot']),
                      'main_sessions': len(manifest['schedules']['main'])}),
          flush=True)


def final_decision(messages):
    """Parse the required final response without model-assisted grading."""
    if not messages:
        return {}
    try:
        value = json.loads(messages[-1])
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def usage(events):
    """Use final cumulative usage without double-counting notifications."""
    values = [e['params']['tokenUsage']['total'] for e in events
              if e.get('method') == 'thread/tokenUsage/updated']
    return values[-1] if values else {}


def require_frozen_source(identity, captured):
    """Reject changed implementation bytes before any model inference."""
    if identity['source_fingerprint'] != (
        captured['identity']['source_fingerprint']
    ):
        raise RuntimeError('Production source changed after freeze')


def require_operational_backend(payload):
    """Keep authentication, quota and transport failures separate."""
    if payload.get('code') in ENVIRONMENT_FAILURES:
        raise RuntimeError('Backend infrastructure: ' + payload['code'])


async def run_job(job, case, manifest, output):
    """Run a fresh chat and grade MCP state, retaining failed attempts."""
    directory = output / 'runs' / job['id']
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    captured = manifest['catalogs'][job['variant']]
    catalog = captured['catalog']
    definitions = {tool['name']: tool for tool in catalog['tools']}
    reference = manifest['references'][case['id']]['states']
    result = {**job, 'manifest_sha256': digest(manifest),
              'status': 'running', 'trace': [], 'turns': [],
              'schema_errors': 0, 'semantic_errors': 0,
              'unintended_changes': False, 'clarifications': 0}
    client = None
    prefix = 0
    clarified = False
    context = fixture_backend(case, job['variant'], directory)
    if job['backend'] == 'live':
        from study_live import live_backend  # noqa: PLC0415
        context = live_backend(case, job['variant'], directory)
    try:
        async with context as (backend, identity):
            result['server_identity'] = identity
            require_frozen_source(identity, captured)
            if job['backend'] == 'live':
                reference = backend.references
            initial = await backend.state()
            observed = initial
            allowed_periods = permissions(case, reference)

            def matches(state, index):
                return normalized(state, reference[index],
                                  allowed_periods[index]) == reference[index]

            async def execute(call):
                nonlocal prefix, observed
                args = call['arguments']
                tool = definitions.get(call['tool'])
                valid = (tool is not None and isinstance(args, dict)
                         and not list(Draft202012Validator(
                             tool['inputSchema'],
                         ).iter_errors(args))
                         and not set(args) - set(
                             tool['inputSchema'].get('properties', {})))
                before = observed
                read_only = bool(((tool or {}).get('annotations') or {})
                                 .get('readOnlyHint'))
                if tool is None or not isinstance(args, dict):
                    payload = failure('INVALID_ARGUMENT',
                                      'Unknown tool or non-object arguments.')
                elif case['clarification'] and not clarified and not read_only:
                    payload = failure(
                        'TARGET_AMBIGUOUS',
                        'The request needs user clarification before writing.',
                    )
                else:
                    payload = await backend.call(call)
                after = before if read_only else await backend.state()
                observed = after
                failed = payload.get('ok') is False
                advances = (prefix + 1 < len(reference)
                            and matches(after, prefix + 1))
                wrong_mutation = (normalized(
                    before, reference[prefix], allowed_periods[prefix],
                ) != normalized(after, reference[prefix],
                                allowed_periods[prefix]) and not advances)
                if advances:
                    prefix += 1
                result['schema_errors'] += int(not valid)
                result['semantic_errors'] += int(
                    valid and payload.get('code') not in ENVIRONMENT_FAILURES
                    and (failed or wrong_mutation),
                )
                result['unintended_changes'] |= wrong_mutation
                result['trace'].append({
                    **call, 'schema_valid': valid, 'read_only': read_only,
                    'result': payload, 'state_changed': before != after,
                    'advances': advances, 'prefix': prefix,
                    'post_state': after,
                })
                require_operational_backend(payload)
                if job['level'] == 'decision':
                    return {'ok': not failed, 'decision_recorded': True}
                return payload

            tools = ordered_tools(catalog, case['id'], job['repeat'])
            result['tool_order'] = [tool['name'] for tool in tools]
            metadata = {tool['name']: tool.get('annotations', {})
                        for tool in catalog['tools']}
            instructions = (catalog['instructions'] + '\n\n' + POLICY
                            + '\nTool policy metadata: '
                            + json.dumps(metadata, sort_keys=True))
            prompt = ('Document ID: ' + backend.document_id + '\n'
                      + case['request'])
            if job['level'] == 'decision':
                prompt = ('Decision-only: all discovery and reads below have '
                          'already completed. Choose at most one next action, '
                          'or clarify/abstain as needed.\n'
                          + json.dumps(await model_state(backend),
                                       ensure_ascii=False) + '\n' + prompt)
            result['prompt'] = prompt
            async with isolated_client(
                directory / 'codex.stderr',
                timeout=240 if job['backend'] == 'live' else 120,
            ) as client:
                started = await client.start(
                    model=job['model'], tools=tools, instructions=instructions,
                    cwd=ROOT,
                )
                result['effective_model'] = started['model']
                result['effective_effort'] = started['reasoningEffort']
                result['thread_id'] = started['thread']['id']
                turn = await client.turn(
                    result['thread_id'], prompt, execute,
                    action_limit=1 if job['level'] == 'decision' else 16,
                    output_schema=FINAL_SCHEMA,
                )
                result['turns'].append(turn)
                final = final_decision(turn['messages'])
                if final.get('decision') == 'clarify':
                    result['clarifications'] += 1
                    if case['clarification'] and job['level'] == 'end_to_end':
                        clarified = True
                        turn = await client.turn(
                            result['thread_id'], case['clarification'],
                            execute,
                            action_limit=16 - len(result['trace']),
                            output_schema=FINAL_SCHEMA,
                        )
                        result['turns'].append(turn)
                        final = final_decision(turn['messages'])
                        if final.get('decision') == 'clarify':
                            result['clarifications'] += 1
                final_state = await backend.state()
                result['final_state'] = final_state
                text = '\n'.join(m for t in result['turns']
                                 for m in t['messages'])
                answer_ok = (case['answer_contains'] is None
                             or case['answer_contains'] in text)
                trace = result['trace']
                first = trace[0] if trace else None
                if job['level'] == 'decision':
                    if case['expected_decision'] == 'clarify':
                        correct = (not trace
                                   and final.get('decision') == 'clarify')
                    elif case['oracle']:
                        correct = bool(first and first['schema_valid']
                                       and first['advances'])
                    else:
                        correct = (final_state == initial and answer_ok
                                   and final.get('decision') != 'clarify'
                                   and (not trace or (
                                       case['answer_contains']
                                       and first['schema_valid']
                                       and first['result'].get('ok')
                                       is not False
                                       and first['tool'] == 'docs_read')))
                    success = correct
                else:
                    correct = bool(first and first['schema_valid']
                                   and first['result'].get('ok') is not False
                                   and (first['tool'] in READ_TOOLS
                                        or first['advances']))
                    if not trace and not case['oracle']:
                        correct = (answer_ok and final_state == initial
                                   and final.get('decision') != 'clarify')
                    success = matches(final_state, len(reference) - 1)
                    success &= answer_ok
                    if not case['oracle']:
                        success &= final.get('decision') != 'clarify'
                unnecessary_question = (result['clarifications'] > 0
                                        and case['clarification'] is None)
                result.update(
                    first_action_correct=bool(correct), final_success=success,
                    recovery_free=(success and not result['schema_errors']
                                   and not result['semantic_errors']
                                   and not unnecessary_question),
                    unnecessary_clarification=unnecessary_question,
                    status='completed',
                    exact_final_state_matches=final_state == reference[-1],
                    final_state_has_optional_period_difference=(
                        matches(final_state, len(reference) - 1)
                        and final_state != reference[-1]),
                )
    except (StudyAgentError, TimeoutError) as error:
        result.update(status='agent_failure', error=str(error),
                      first_action_correct=False, final_success=False,
                      recovery_free=False)
    except Exception as error:  # noqa: BLE001 - retain every failed attempt
        result.update(status='infrastructure_failure', error=str(error))
    finally:
        if client is not None:
            result['usage'] = usage(client.events)
            result['process_reaped'] = client.process_reaped
            write_json(directory / 'events.json', client.events)
        write_json(directory / 'result.json', result)
    return result


async def run_stage(output, stage, concurrency):
    """Reserve each attempt once and never exceed the user-approved cap."""
    manifest = json.loads((output / 'manifest.json').read_text())
    if digest(manifest) != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Frozen study manifest changed')
    if manifest['sources'] != source_hashes():
        raise ValueError('Research source changed after manifest freeze')
    prior = prior_checkpoint(Path(manifest['prior_run']['directory']))
    if prior != manifest['prior_run']:
        raise ValueError('Prior campaign ledger changed after restart freeze')
    if any(digest(cases) != manifest['dataset_hashes'][name]
           for name, cases in manifest['datasets'].items()):
        raise ValueError('Frozen study corpus changed')
    if stage == 'main':
        pilot_status = json.loads((output / 'pilot-run-status.json')
                                  .read_text())
        if pilot_status['stopped_on_infrastructure_failure']:
            raise ValueError('Resolve pilot infrastructure before main trials')
    ledger_path = output / 'ledger.json'
    ledger = json.loads(ledger_path.read_text())
    if (ledger['cap'] != CAP or ledger['total_cap'] != TOTAL_CAP
            or ledger['prior_attempts'] != prior['attempts']):
        raise ValueError('Restart ledger budget does not match approval')
    if stage == 'main':
        pilot_attempts = [a for a in ledger['attempts']
                          if a['stage'] == 'pilot']
        if (len(pilot_attempts) != len(manifest['schedules']['pilot'])
                or any(a['status'] == 'reserved' for a in pilot_attempts)):
            raise ValueError('Pilot schedule has not finished')
    attempted = {entry['id'] for entry in ledger['attempts']}
    cases = {case['id']: case for case in manifest['datasets'][stage]}
    jobs = [job for job in manifest['schedules'][stage]
            if job['id'] not in attempted]
    queue = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)
    stop = asyncio.Event()
    stop_reasons = []
    complete = []

    def request_stop(name):
        stop_reasons.append(name)
        stop.set()
        print(json.dumps({'draining_after_signal': name}), flush=True)

    async def worker():
        while not queue.empty() and not stop.is_set():
            job = queue.get_nowait()
            if (len(ledger['attempts']) >= CAP
                    or prior['attempts'] + len(ledger['attempts'])
                    >= TOTAL_CAP):
                raise RuntimeError('Approved model-session cap reached')
            entry = {**job, 'status': 'reserved', 'started_at': time.time()}
            ledger['attempts'].append(entry)
            write_json(ledger_path, ledger)
            result = await run_job(job, cases[job['case']], manifest, output)
            entry.update(status=result['status'], completed_at=time.time())
            write_json(ledger_path, ledger)
            complete.append(result)
            print(json.dumps({key: result.get(key) for key in (
                'id', 'status', 'first_action_correct', 'final_success',
                'error',
            )}), flush=True)
            if result['status'] == 'infrastructure_failure':
                stop_reasons.append('infrastructure_failure')
                stop.set()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, request_stop, signum.name)
    try:
        await asyncio.gather(*[worker() for _ in range(concurrency)])
    finally:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)
    summary = {'stage': stage, 'completed_this_run': len(complete),
               'attempts_total': len(ledger['attempts']),
               'attempts_including_prior': (prior['attempts']
                                            + len(ledger['attempts'])),
               'stop_reasons': stop_reasons,
               'stopped_on_infrastructure_failure': (
                   'infrastructure_failure' in stop_reasons)}
    write_json(output / f'{stage}-run-status.json', summary)
    print(json.dumps(summary), flush=True)


def main():
    """Prepare a frozen campaign or resume an explicitly selected stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'pilot', 'main'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-campaign', type=Path)
    parser.add_argument('--concurrency', type=int, default=3,
                        choices=[1, 2, 3])
    args = parser.parse_args()
    if args.action == 'prepare' and args.previous_campaign is None:
        parser.error('Restart preparation requires --previous-campaign')
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.output / 'campaign.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'prepare':
            asyncio.run(prepare(args.output, args.previous_campaign))
        else:
            asyncio.run(run_stage(args.output, args.action, args.concurrency))


if __name__ == '__main__':
    main()
