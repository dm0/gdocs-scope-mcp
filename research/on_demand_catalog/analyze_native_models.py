"""Audit the sixty native-model traces and summarize paired loading effects."""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from local_responses import callable_names
from probe_client import MODELS, digest, write_json

T975 = (None, 12.706205, 4.302653, 3.182446, 2.776445, 2.570582,
        2.446912, 2.364624, 2.306004, 2.262157)
METRICS = ('input_tokens', 'cached_tokens', 'output_tokens',
           'turn_seconds', 'palette_calls', 'search_calls')


def continuous(values):
    """Return sample variance and a two-sided Student t mean interval."""
    values = [v for v in values if v is not None]
    n = len(values)
    if not n:
        return {'n': 0, 'mean': None, 'variance': None, 'ci95': None}
    mean = statistics.mean(values)
    if n == 1:
        return {'n': n, 'mean': mean, 'variance': None, 'ci95': None}
    variance = statistics.variance(values)
    half = T975[n - 1] * math.sqrt(variance / n)
    return {'n': n, 'mean': mean, 'variance': variance,
            'ci95': [mean - half, mean + half]}


def wilson(successes, total):
    """Describe single-task success uncertainty without ceiling collapse."""
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total
                         + z * z / (4 * total * total)) / denominator
    return [center - half, min(1.0, center + half)]


def raw_items(events):
    """Deduplicate streamed history items by their stable wire identity."""
    result, seen = [], set()
    for event in events:
        if event.get('method') != 'rawResponseItem/completed':
            continue
        item = event['params']['item']
        key = (item['type'], item.get('id'), item.get('call_id'))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def summarize(row, events):
    """Grade real native calls separately from exposure and search evidence."""
    items = raw_items(events)
    definitions = next((i.get('tools', []) for i in items
                        if i['type'] == 'additional_tools'), None)
    initial = None if definitions is None else [
        n for ns, n in callable_names(definitions)
        if ns == 'mcp__native_probe' or n.startswith('mcp__native_probe__')]
    searches = [i for i in items if i['type'] == 'tool_search_call']
    malformed_searches = [i for i in items if i['type'] == 'function_call'
                          and i.get('namespace') == 'tool_search'
                          and i.get('name') == 'tool_search_tool']
    loaded = [i for i in items if i['type'] == 'tool_search_output']
    native = [e['params']['item'] for e in events
              if e.get('method') == 'item/completed'
              and e['params']['item'].get('type') == 'mcpToolCall']
    palette = [i for i in native if i['tool'] == 'docs_get_color_palette']
    successful_palette = [i for i in palette if i['status'] == 'completed'
                          and i['arguments'] == {}
                          and i.get('result', {}).get('structuredContent')]
    blue = [entry['hex'] for call in successful_palette
            for line in call['result']['structuredContent'].get('rows', [])
            for entry in line if entry['name'] == 'blue']
    safe = {'server_info', 'docs_get_color_palette'}
    forbidden = [i for i in items if i['type'] == 'function_call'
                 and not ((i.get('namespace') == 'mcp__native_probe'
                           and i['name'] in safe)
                          or (i.get('namespace') in (None, 'functions')
                              and i['name'] in {
                                  'mcp__native_probe__' + n for n in safe}))]
    blocked = [c for c in row['server_calls'] if not c['allowed']]
    usage = [e['params']['tokenUsage']['total'] for e in events
             if e.get('method') == 'thread/tokenUsage/updated']
    usage = usage[-1] if usage else {}
    messages = row.get('result', {}).get('messages', [])
    matches = (len(initial) == (36 if row['arm'] == 'eager' else 0)
               if initial is not None else False)
    if row['arm'] == 'deferred':
        matches = matches and bool(searches and loaded) and any(
            name == 'docs_get_color_palette'
            for i in loaded for _ns, name in callable_names(i['tools']))
    settings = row.get('effective', {})
    success = (row['status'] == 'completed' and bool(blue)
               and all(b.upper() == '#0000FF' for b in blue)
               and any('#0000FF' in m.upper() for m in messages)
               and not forbidden and not blocked and not row.get('approvals'))
    return {
        **{k: row[k] for k in ('id', 'model', 'arm', 'repeat', 'status')},
        'success': success, 'exposure_verified': bool(matches),
        'initial_native_schemas': None if initial is None else len(initial),
        'search_calls': (len(searches) + len(malformed_searches)
                         if definitions is not None else None),
        'native_search_calls': len(searches),
        'unsupported_search_calls': len(malformed_searches),
        'loaded_outputs': len(loaded), 'palette_calls': len(palette),
        'forbidden_calls': len(forbidden), 'blocked_calls': len(blocked),
        'settings_match': settings == {'model': row['model'],
                                      'modelProvider': 'openai',
                                      'reasoningEffort': 'medium'},
        'actor_reaped': row.get('actor_reaped', False),
        'mcp_reaped': row.get('mcp_reaped', False),
        'input_tokens': usage.get('inputTokens'),
        'cached_tokens': usage.get('cachedInputTokens'),
        'output_tokens': usage.get('outputTokens'),
        'turn_seconds': row.get('result', {}).get('duration_seconds'),
    }


def analyze(output):
    """Check immutable inputs and preserve raw-evidence hashes privately."""
    manifest = json.loads((output / 'manifest.json').read_text())
    if digest(manifest) != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Manifest changed')
    for name, expected in manifest['sources'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen source changed')
    ledger = json.loads((output / 'ledger.json').read_text())
    rows, hashes = [], {}
    for row in ledger['attempts']:
        directory = output / row['id']
        saved = json.loads((directory / 'result.json').read_text())
        if saved != row:
            raise ValueError('Ledger and result differ')
        events = json.loads((directory / 'events.json').read_text())
        rows.append(summarize(row, events))
        for name in ('events.json', 'result.json', 'calls.jsonl'):
            path = directory / name
            if path.exists():
                hashes[str(path.relative_to(output))] = hashlib.sha256(
                    path.read_bytes()).hexdigest()
    groups = {}
    for model in MODELS:
        groups[model] = {}
        for arm in ('eager', 'deferred'):
            selected = [r for r in rows if r['model'] == model
                        and r['arm'] == arm and r['status'] == 'completed']
            successes = sum(r['success'] for r in selected)
            groups[model][arm] = {
                'completed': len(selected), 'successes': successes,
                'success_ci95': wilson(successes, len(selected)),
                **{k: continuous([r[k] for r in selected]) for k in METRICS},
            }
        pairs = {}
        for repeat in range(10):
            selected = {r['arm']: r for r in rows if r['model'] == model
                        and r['repeat'] == repeat
                        and r['status'] == 'completed'}
            if set(selected) == {'eager', 'deferred'}:
                pairs[repeat] = selected
        groups[model]['paired_deferred_minus_eager'] = {
            k: continuous([p['deferred'][k] - p['eager'][k]
                           for p in pairs.values()
                           if p['deferred'][k] is not None
                           and p['eager'][k] is not None]) for k in METRICS}
    report = {'manifest_sha256': digest(manifest), 'attempts': len(rows),
              'scope': 'One repeated palette task; descriptive comparison',
              'groups': groups, 'rows': rows, 'hashes': hashes}
    write_json(output / 'native-model-analysis.json', report)
    print(json.dumps({'attempts': len(rows), 'successes': sum(r['success']
                     for r in rows), 'groups': groups}, indent=2))
    return report


def main():
    """Analyze saved evidence without opening a model or MCP connection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    analyze(parser.parse_args().output)


if __name__ == '__main__':
    main()
