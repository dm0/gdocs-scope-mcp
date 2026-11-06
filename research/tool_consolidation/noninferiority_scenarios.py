"""Sample fresh task instances from the declared 25-template benchmark mix."""

import random
import re
from copy import deepcopy

from study_scenarios import MAIN, PILOT

SEED = 59150020261106
INSTANCES_PER_TEMPLATE = 10
LABELS = [
    'Checklist', 'Welcome', 'International', 'Domestic', 'Checkpoint',
    'Launch',
    'Archive', 'Exercises', 'Answers', 'Reading', 'Incident', 'Evidence',
    'Button', 'Link', 'Payment', 'Delivery', 'Citation', 'Budget',
    'Operations',
    'Reference', 'Recovery', 'Rollback', 'Supplier', 'Orders', 'Purchase',
    'Release', 'Acceptance', 'Findings', 'Audit', 'Appendix', 'Approved',
    'Alpha', 'Beta', 'Reviews', 'Details', 'Notes', 'Archived', 'Storage',
    'South', 'North',
    'Signals', 'Stable', 'Minutes', 'Meeting', 'Terminology', 'Handover',
    'Wording', 'Summary', 'Draft', 'Final', 'Protected', 'Intake', 'Sample',
    'Queue', 'Ready', 'Pending', 'done', 'local',
]
PATTERN = re.compile(r'\b(' + '|'.join(sorted(LABELS, key=len, reverse=True))
                     + r')\b', re.IGNORECASE)


def replace_labels(value, marker):
    """Rename labels consistently, preserving operations and literal markup."""
    if isinstance(value, dict):
        return {key: replace_labels(child, marker)
                for key, child in value.items()}
    if isinstance(value, list):
        return [replace_labels(child, marker) for child in value]
    if isinstance(value, str):
        return PATTERN.sub(lambda match: match.group() + '-' + marker, value)
    return value


def corpus():
    """Create 250 paired instances, not 250 independent semantic templates."""
    rng = random.Random(SEED)
    result = []
    for template in [*MAIN, *PILOT]:
        for instance in range(INSTANCES_PER_TEMPLATE):
            marker = f'{rng.getrandbits(32):08x}'
            case = replace_labels(deepcopy(template), marker)
            case['id'] = f'ni-{template["id"]}-{instance:02}'
            case['family'] = template['family']
            case['template'] = template['id']
            case['sample_marker'] = marker
            case['fixture']['title'] = 'Synthetic study task ' + marker
            for tab in case['fixture']['tabs']:
                prefix = [{'text': f'Control record {marker} {i}'}
                          for i in range(rng.randint(1, 4))]
                tail = [{'text': f'Unchanged record {marker} {i}'}
                        for i in range(rng.randint(1, 4))]
                tab['paragraphs'] = prefix + tab['paragraphs'] + tail
            # Vary native insertion paths, including the repaired plain path.
            for call in case['oracle']:
                if call['tool'].startswith(('docs_insert', 'docs_append')):
                    if 'rich' not in call['arguments']:
                        call['arguments']['rich'] = bool(rng.getrandbits(1))
                    if template['id'] in {'m05', 'm16'} and instance == 0:
                        call['arguments']['rich'] = False
            if case['answer_contains']:
                number = rng.randrange(10000, 99999)
                batch = f'WH-{number}-{marker[:2].upper()}'
                case = replace_batch(case, batch)
                case['answer_heading_id'] = next(
                    p['heading_id'] for tab in case['fixture']['tabs']
                    for p in tab['paragraphs']
                    if p['text'].startswith('Delivery-')
                    and p.get('heading_id')
                )
            result.append(case)
    return result


def replace_batch(value, batch):
    """Keep each read-only answer fresh and consistent with its source."""
    if isinstance(value, dict):
        return {key: replace_batch(child, batch)
                for key, child in value.items()}
    if isinstance(value, list):
        return [replace_batch(child, batch) for child in value]
    if isinstance(value, str):
        return value.replace('WH-7294-Z', batch)
    return value
