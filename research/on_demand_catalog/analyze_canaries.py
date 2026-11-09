"""Audit the six canaries without inferring unobserved discovery events."""

import argparse
import hashlib
import json
from pathlib import Path

from probe_client import CAP, CORE, NAMESPACE, digest, model_tools, write_json


def summarize(row, events):
    """Separate correct callbacks and answers from observable search events."""
    callbacks = [e['params'] for e in events
                 if e.get('method') == 'item/tool/call']
    calls = row.get('result', {}).get('calls', [])
    palette = [c for c in calls if c['tool'] == 'docs_get_color_palette']
    blue = [entry['hex'] for call in palette
            for line in call.get('result', {}).get('rows', [])
            for entry in line if entry['name'] == 'blue']
    messages = row.get('result', {}).get('messages', [])
    completed = [e['params']['item'] for e in events
                 if e.get('method') == 'item/completed']
    search_items = [i for i in completed if 'toolsearch' in
                    i.get('type', '').lower().replace('_', '')]
    search_methods = [e['method'] for e in events
                      if 'toolsearch' in e.get('method', '')
                      .lower().replace('_', '')]
    usage = [e['params']['tokenUsage']['total'] for e in events
             if e.get('method') == 'thread/tokenUsage/updated']
    return {
        'id': row['id'], 'model': row['model'], 'arm': row['arm'],
        'status': row['status'],
        'effective_settings_match': (
            row.get('effective_model') == row['model']
            and row.get('effective_effort') == 'medium'),
        'palette_callback_valid': (
            bool(palette) and all(c['arguments'] == {} for c in palette)
            and len(blue) == len(palette) and len(set(blue)) == 1
            and all(c['tool'] in {'server_info', 'docs_get_color_palette'}
                    and c.get('namespace') == NAMESPACE for c in callbacks)),
        'palette_calls': len(palette),
        'redundant_palette_reads': max(0, len(palette) - 1),
        'answer_contains_returned_blue': bool(
            blue and any(blue[0].upper() in m.upper() for m in messages)),
        'callbacks': [{'namespace': c.get('namespace'), 'tool': c['tool'],
                       'arguments': c['arguments']} for c in callbacks],
        'completed_item_types': [i['type'] for i in completed],
        'explicit_search_items': search_items,
        'explicit_search_methods': search_methods,
        'usage': usage[-1] if usage else {},
        'usage_update_count': len(usage),
        'turn_seconds': row.get('result', {}).get('duration_seconds'),
        'actor_reaped': row.get('actor_reaped', False),
        'mcp_reaped': row.get('mcp_reaped', False),
    }


def analyze(output):
    """Verify frozen inputs and produce a descriptive compatibility audit."""
    manifest = json.loads((output / 'manifest.json').read_text())
    manifest_hash = digest(manifest)
    if manifest_hash != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Frozen manifest changed')
    for name, expected in manifest['sources'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen canary source changed')
    ledger = json.loads((output / 'ledger.json').read_text())
    scheduled = {j['id'] for j in manifest['schedule']}
    if (ledger['cap'] != CAP or len(ledger['attempts']) != CAP
            or {r['id'] for r in ledger['attempts']} != scheduled):
        raise ValueError('Expected all six distinct reserved attempts')
    eager = model_tools(manifest['catalog'], 'eager')[0]['tools']
    deferred = model_tools(manifest['catalog'], 'deferred')[0]['tools']
    for left, right in zip(eager, deferred, strict=True):
        left.pop('deferLoading')
        right.pop('deferLoading')
        if left != right:
            raise ValueError('Domain interfaces differ across arms')
    rows, hashes = [], {}
    for job in manifest['schedule']:
        directory = output / job['id']
        for name in ('result.json', 'events.json'):
            hashes[job['id'] + '/' + name] = hashlib.sha256(
                (directory / name).read_bytes()).hexdigest()
        row = json.loads((directory / 'result.json').read_text())
        if (row['id'] != job['id'] or row['model'] != job['model']
                or row['arm'] != job['arm']
                or row['status'] not in {'completed', 'failed'}):
            raise ValueError('Unexpected or unfinished canary outcome')
        events = json.loads((directory / 'events.json').read_text())
        rows.append(summarize(row, events))
    report = {
        'manifest_sha256': manifest_hash, 'attempts': CAP,
        'scope': 'One read-only canary per model/arm; descriptive only',
        'core': CORE, 'domain_interfaces_equal': True,
        'native_mcp_approval_verified': False,
        'provider_request_payload_observed': False,
        'rows': rows, 'input_hashes': hashes,
        'future_sessions_authorized': False,
    }
    write_json(output / 'canary-analysis.json', report)
    print(json.dumps(report, indent=2))
    return report


def main():
    """Read completed traces without creating a thread or calling a model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    analyze(parser.parse_args().output)


if __name__ == '__main__':
    main()
