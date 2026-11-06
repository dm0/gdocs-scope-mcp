"""Protect scope, literal characters and styles in the reviewed sensitivity."""

from copy import deepcopy

import pytest

from .test_study_corpus import adjudication


def paragraph(text):
    """Represent literal characters independently of display markup."""
    return {'style': {}, 'characters': [[char, {}] for char in text + '\n']}


@pytest.mark.parametrize('defect', [None, 'protected', 'style', 'literal',
                                  'extra_paragraph', 'position'])
def test_only_new_paragraph_at_expected_position_can_lose_a_period(defect):
    """Repeated existing text must never inherit insertion permissions."""
    initial = {'tabs': [{'id': 't', 'paragraphs': [
        paragraph('Anchor'), paragraph('**Done**'),
    ]}], 'comments': []}
    expected = deepcopy(initial)
    expected['tabs'][0]['paragraphs'].insert(1, paragraph('**Done**'))
    case = {'request': 'Insert the literal paragraph **Done** after Anchor.',
            'oracle': [{'tool': 'docs_insert_after', 'arguments': {
                'anchor': 'Anchor', 'text': '**Done**', 'rich': False,
            }}]}
    allowed = adjudication.permissions(case, [initial, expected])[-1]
    assert allowed[0] == {('t', 1)}
    actual = deepcopy(expected)
    actual['tabs'][0]['paragraphs'][1] = paragraph('**Done**.')
    if defect == 'protected':
        actual['tabs'][0]['paragraphs'][2] = paragraph('**Done**.')
    elif defect == 'style':
        actual['tabs'][0]['paragraphs'][1]['characters'][-2][1]['bold'] = True
    elif defect == 'literal':
        actual['tabs'][0]['paragraphs'][1] = paragraph('Done.')
    elif defect == 'extra_paragraph':
        actual['tabs'][0]['paragraphs'].append(paragraph('Unexpected'))
    elif defect == 'position':
        actual['tabs'][0]['paragraphs'].reverse()
    before = deepcopy(actual)
    reviewed = adjudication.normalized(actual, expected, allowed)
    assert (reviewed == expected) == (defect is None)
    assert actual == before


@pytest.mark.parametrize('defect', [None, 'extra_post', 'wrong_action',
                                  'wrong_status', 'protected_text'])
def test_reopen_action_text_keeps_status_and_other_posts_exact(defect):
    """The rule also covers action text while preserving closed history."""
    initial = {'tabs': [], 'comments': [{
        'id': 'c', 'resolved': True,
        'replies': [{'action': 'RESOLVE', 'text': 'Closed history'}],
    }]}
    expected = deepcopy(initial)
    expected['comments'][0]['resolved'] = False
    expected['comments'][0]['replies'].append({
        'action': 'REOPEN', 'text': 'Need review',
    })
    case = {'request': 'Reopen with action text Need review.', 'oracle': [{
        'tool': 'docs_reopen_comment',
        'arguments': {'comment_id': 'c', 'reply': 'Need review'},
    }]}
    allowed = adjudication.permissions(case, [initial, expected])[-1]
    actual = deepcopy(expected)
    actual['comments'][0]['replies'][-1]['text'] += '.'
    if defect == 'extra_post':
        actual['comments'][0]['replies'].append({'action': None, 'text': 'x'})
    elif defect == 'wrong_action':
        actual['comments'][0]['replies'][-1]['action'] = 'RESOLVE'
    elif defect == 'wrong_status':
        actual['comments'][0]['resolved'] = True
    elif defect == 'protected_text':
        actual['comments'][0]['replies'][0]['text'] += '.'
    assert (adjudication.normalized(actual, expected, allowed)
            == expected) == (defect is None)


def test_quoted_targets_require_another_adjudication():
    """Fail closed rather than relaxing an explicitly quoted exact string."""
    with pytest.raises(ValueError, match='Quoted targets'):
        adjudication.permissions({'request': 'Insert "Exact".',
                                  'oracle': []}, [{}])
