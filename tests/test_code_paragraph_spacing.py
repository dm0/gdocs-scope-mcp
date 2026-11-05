"""Check code-block spacing against nonzero inherited paragraph intervals."""

import pytest

from gdocs_scope_mcp.rich_text.compiler import (
    inserted_text_from_requests,
    markdown_to_requests,
)
from gdocs_scope_mcp.text_indices import utf16_length


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('html', [False, True])
@pytest.mark.parametrize('code', [
    '', 'single🦷', 'first🦷\nlast', '\nfirst\n\n\tlast  \n\n', '\n\n',
])
def test_code_spacing_preserves_only_outer_intervals(
    code, html, newline_before,
):
    """Replay updates with nonzero named-style spacing and indents."""
    block = (f'<pre><code>{code}\n</code></pre>' if html
             else f'```\n{code}\n```')
    requests = markdown_to_requests(
        f'Before🦷\n\n{block}\n\nAfter', start=12,
        newline_before=newline_before,
    )
    inserted = inserted_text_from_requests(requests)
    expected = f'Before🦷\n{code}\nAfter'
    assert inserted == ('\n' + expected if newline_before else expected + '\n')
    # Resolve absent direct properties from a deliberately nonzero named style.
    baseline = {'spaceAbove': {'magnitude': 12, 'unit': 'PT'},
                'spaceBelow': {'magnitude': 18, 'unit': 'PT'},
                'indentFirstLine': {'magnitude': 24, 'unit': 'PT'}}
    rows = []
    position = 12
    for line in inserted.split('\n')[:-1]:
        end = position + utf16_length(line) + 1
        rows.append((position, end, baseline.copy()))
        position = end
    # newline_before leaves After's existing terminal newline outside the text.
    if newline_before:
        rows.append((position, position + utf16_length('After') + 1,
                     baseline.copy()))
    for request in requests:
        for kind in ('updateTextStyle', 'updateParagraphStyle'):
            if kind in request:
                span = request[kind]['range']
                assert span['startIndex'] < span['endIndex']
        update = request.get('updateParagraphStyle')
        if update is None:
            continue
        left, right = (update['range'][key]
                       for key in ('startIndex', 'endIndex'))
        for start, end, style in rows:
            if left >= end or right <= start:
                continue
            if update['fields'] == '*':
                style.clear()
                style.update(baseline)
            style.update(update['paragraphStyle'])
    first = 2 if newline_before else 1
    code_rows = rows[first:first + len(code.split('\n'))]
    for index, (_, _, style) in enumerate(code_rows):
        assert style['spaceAbove']['magnitude'] == (12 if index == 0 else 0)
        assert style['spaceBelow']['magnitude'] == (
            18 if index == len(code_rows) - 1 else 0
        )
        assert style['indentFirstLine'] == baseline['indentFirstLine']
    for _, _, style in rows[:first] + rows[first + len(code_rows):]:
        assert all(style[key] == value for key, value in baseline.items())


@pytest.mark.parametrize('newline_before', [False, True])
def test_adjacent_code_blocks_have_independent_spacing(newline_before):
    """Keep each block's boundaries separate even without intervening prose."""
    requests = markdown_to_requests(
        '```\nfirst🦷\nsecond\n```\n\n```\nthird\nlast🦷\n```',
        start=12, newline_before=newline_before,
    )
    inserted = inserted_text_from_requests(requests)
    spacing = [r['updateParagraphStyle'] for r in requests
               if r.get('updateParagraphStyle', {}).get('fields')
               in {'spaceAbove', 'spaceBelow'}]
    assert len(spacing) == 4  # noqa: PLR2004
    for update in spacing:
        left, right = (update['range'][key] - 12
                       for key in ('startIndex', 'endIndex'))
        selected = inserted.encode('utf-16-le')[left * 2:right * 2].decode(
            'utf-16-le',
        )
        assert selected in {'first🦷\n', 'second', 'third\n', 'last🦷'}
