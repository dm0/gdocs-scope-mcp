"""Verify baseline resets precede only explicitly requested input styles."""

import pytest

from gdocs_scope_mcp.rich_text.compiler import markdown_to_requests


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('markup', [
    'Plain🦷', '# Title', '## Subtitle', '###### Heading 4',
    '<p style="text-align: center;">Centered</p>',
    '- Parent\n  - Child🦷',
    '```python\nreturn 1\n```',
    '[**Bold🦷**](https://example.com) and `code`',
])
def test_every_inserted_paragraph_resets_inherited_formatting(
    markup, newline_before,
):
    """Use wildcard resets for unknown direct properties as well as spacing."""
    requests = markdown_to_requests(
        markup, start=12, newline_before=newline_before,
    )
    resets = [(i, r['updateTextStyle']) for i, r in enumerate(requests)
              if r.get('updateTextStyle', {}).get('fields') == '*']
    paragraphs = [(i, r['updateParagraphStyle'])
                  for i, r in enumerate(requests)
                  if 'updateParagraphStyle' in r]
    assert resets
    for index, reset in resets:
        assert reset['textStyle'] == {}
        assert reset['range']['startIndex'] < reset['range']['endIndex']
        assert any(i < index and r.get('deleteParagraphBullets', {}).get(
            'range') == reset['range'] for i, r in enumerate(requests))
        assert any(p['range'] == reset['range'] and p['fields'] == '*'
                   for _, p in paragraphs)
        # A later baseline reset must never erase earlier explicit styles.
        for previous in requests[:index]:
            update = previous.get('updateTextStyle', {})
            if not update.get('textStyle'):
                continue
            span = update['range']
            assert (span['endIndex'] <= reset['range']['startIndex']
                    or span['startIndex'] >= reset['range']['endIndex'])


@pytest.mark.parametrize('newline_before', [False, True])
def test_explicit_styles_follow_baseline_resets(newline_before):
    """Keep explicit emphasis and links after resetting surrounding text."""
    requests = markdown_to_requests(
        'Plain **bold🦷** and [link](https://example.com)\n\nLast',
        start=12, newline_before=newline_before,
    )
    resets = [r['updateTextStyle'] for r in requests
              if r.get('updateTextStyle', {}).get('fields') == '*']
    assert len(resets) == 2  # noqa: PLR2004
    assert [r['updateTextStyle']['textStyle'] for r in requests
            if r.get('updateTextStyle', {}).get('textStyle')] == [
        {'bold': True}, {'link': {'url': 'https://example.com'}},
    ]
