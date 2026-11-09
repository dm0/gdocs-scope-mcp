"""Apply the user's post-hoc period rule without relaxing protected state."""

from copy import deepcopy

from bs4 import BeautifulSoup

from gdocs_scope_mcp.rich_text.parsing import markdown_to_html

INSERT_TOOLS = {'docs_append', 'docs_insert_before', 'docs_insert_after',
                'docs_insert_at_heading'}
STATUS_TOOLS = {'docs_resolve_comment', 'docs_reopen_comment'}
READ_TOOLS = {'docs_get_tree', 'docs_read', 'docs_read_comments',
              'docs_tabs_list'}


def paragraph_text(paragraph):
    """Read the frozen canonical paragraph without its terminal newline."""
    return ''.join(c[0] for c in paragraph.get('characters', [])).rstrip('\n')


def heading_end(paragraphs, start):
    """Find a native heading's subtree boundary in the frozen body corpus."""
    level = paragraphs[start]['style']['namedStyleType']
    for index in range(start + 1, len(paragraphs)):
        candidate = paragraphs[index]['style'].get('namedStyleType', '')
        if candidate.startswith('HEADING_') and candidate <= level:
            return index
    return len(paragraphs)


def insertion_position(call, before):
    """Resolve the inserted paragraph from the gold operation's target."""
    args = call['arguments']
    tab = next(t for t in before['tabs']
               if t['id'] == args.get('tab_id', before['tabs'][0]['id']))
    paragraphs = tab['paragraphs']
    if call['tool'] == 'docs_append':
        return tab['id'], len(paragraphs)
    start, end = 0, len(paragraphs)
    if args.get('heading_id'):
        start = next(i for i, p in enumerate(paragraphs)
                     if p['style'].get('headingId') == args['heading_id'])
        end = heading_end(paragraphs, start)
    if call['tool'] == 'docs_insert_at_heading':
        if args['position'] != 'after_subtree':
            raise ValueError('Only frozen after-subtree cases are supported')
        return tab['id'], end
    match = next(i for i in range(start, end)
                 if args['anchor'] in paragraph_text(paragraphs[i]))
    return tab['id'], match + int(call['tool'] == 'docs_insert_after')


def permissions(case, references):
    """Locate only new paragraphs and action posts in this frozen corpus."""
    if any(mark in case['request'] for mark in ('"', '«', '»', '“', '”', '`')):
        raise ValueError('Quoted targets need their own human adjudication')
    paragraphs, posts = set(), set()
    result = [(set(), set())]
    if sum(c['tool'] in INSERT_TOOLS for c in case['oracle']) > 1:
        raise ValueError('Multiple insertions need coordinate tracking')
    for index, call in enumerate(case['oracle'], 1):
        before, after = references[index - 1:index + 1]
        if call['tool'] in INSERT_TOOLS:
            text = call['arguments']['text']
            if call['arguments'].get('rich', True):
                text = BeautifulSoup(markdown_to_html(text),
                                     'html.parser').get_text().rstrip('\n')
            identifier, position = insertion_position(call, before)
            tab = next(t for t in after['tabs'] if t['id'] == identifier)
            if paragraph_text(tab['paragraphs'][position]) != text:
                raise ValueError('Frozen insertion position does not match')
            paragraphs.add((identifier, position))
        if call['tool'] in STATUS_TOOLS and call['arguments'].get('reply'):
            identifier = call['arguments']['comment_id']
            thread = next(t for t in after['comments']
                          if t['id'] == identifier)
            posts.add((identifier, len(thread['replies']) - 1))
        result.append((set(paragraphs), set(posts)))
    return result


def paragraph_period(actual, expected):
    """Normalize one final period only when its style matches adjacent text."""
    actual_chars = actual.get('characters', [])
    expected_chars = expected.get('characters', [])
    actual_text = ''.join(c[0] for c in actual_chars)
    expected_text = ''.join(c[0] for c in expected_chars)
    if (expected_text.endswith('\n') and not expected_text.endswith('.\n')
            and actual_text == expected_text[:-1] + '.\n'
            and len(actual_chars) > 2  # noqa: PLR2004
            and actual_chars[-2][1] == actual_chars[-3][1]):
        actual_chars.pop(-2)
    elif (expected_text.endswith('.\n')
          and actual_text == expected_text[:-2] + '\n'
          and len(expected_chars) > 2  # noqa: PLR2004
          and expected_chars[-2][1] == expected_chars[-3][1]):
        actual_chars.insert(len(actual_chars) - 1,
                            deepcopy(expected_chars[-2]))


def normalized(state, reference, allowed):
    """Preserve unrelated characters, styles, locations and action posts."""
    state = deepcopy(state)
    if state is None:
        return None
    paragraphs, posts = allowed
    expected_tabs = {tab['id']: tab for tab in reference['tabs']}
    for tab in state['tabs']:
        for position, paragraph in enumerate(tab['paragraphs']):
            if (tab['id'], position) in paragraphs:
                expected = expected_tabs[tab['id']]['paragraphs'][position]
                paragraph_period(paragraph, expected)
    expected_threads = {t['id']: t for t in reference['comments']}
    for thread in state['comments']:
        for position, post in enumerate(thread['replies']):
            if (thread['id'], position) not in posts:
                continue
            expected = expected_threads[thread['id']]['replies'][position]
            if post['action'] != expected['action']:
                continue
            text = expected['text']
            alternative = text[:-1] if text.endswith('.') else text + '.'
            if post['text'] == alternative:
                post['text'] = text
    return state


def regrade(row, case, references):
    """Derive reviewed metrics while leaving all source traces untouched."""
    eligible = any(
        c['tool'] in INSERT_TOOLS or (c['tool'] in STATUS_TOOLS
                                     and c['arguments'].get('reply'))
        for c in case['oracle']
    )
    if row['status'] != 'completed' or not eligible:
        return row
    allowed = permissions(case, references)
    row = deepcopy(row)
    before, prefix, errors, unintended = references[0], 0, 0, False
    advances = []
    for call in row['trace']:
        after = call['post_state']
        advance = (prefix + 1 < len(references) and normalized(
            after, references[prefix + 1], allowed[prefix + 1],
        ) == references[prefix + 1])
        wrong = (not advance and normalized(
            before, references[prefix], allowed[prefix],
        ) != normalized(after, references[prefix], allowed[prefix]))
        errors += bool(call['schema_valid']
                       and (call['result'].get('ok') is False or wrong))
        unintended |= wrong
        prefix += int(advance)
        advances.append(advance)
        before = after
    first = row['trace'][0] if row['trace'] else None
    if row['level'] == 'decision':
        if case['expected_decision'] != 'clarify':
            row['first_action_correct'] = bool(
                first and first['schema_valid'] and advances[0])
        row['final_success'] = row['first_action_correct']
    else:
        row['first_action_correct'] = bool(
            first and first['schema_valid']
            and first['result'].get('ok') is not False
            and (first['tool'] in READ_TOOLS or advances[0]))
        row['final_success'] = normalized(
            row['final_state'], references[-1], allowed[-1],
        ) == references[-1]
    row['semantic_errors'] = errors
    row['unintended_changes'] = unintended
    row['recovery_free'] = (row['final_success'] and not row['schema_errors']
                            and not errors
                            and not row['unnecessary_clarification'])
    return row
