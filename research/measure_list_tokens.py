"""Compare synthetic lists with an optional development tokenizer.

Run from the repository root with:
uv run --locked --with tiktoken==0.12.0 python \
research/measure_list_tokens.py
"""

import json

import tiktoken

from gdocs_scope_mcp.documents.native_models import GoogleDocument
from gdocs_scope_mcp.rich_text.parsing import markdown_to_html

SHORT = 'Проверить входные данные'
LONG = ' '.join([
    'Агент проверяет входные данные и сопоставляет результат с требованиями '
    'задачи Затем он сохраняет изменения и проверяет что структура документа '
    'и содержание каждого раздела сохранились',
] * 4)


def render_native(items: list[tuple[str, int]]) -> str:
    """Render the same text/depths through the actual document reader."""
    content = []
    index = 1
    for text, depth in items:
        end = index + len((text + '\n').encode('utf-16-le')) // 2
        content.append({
            'startIndex': index, 'endIndex': end,
            'paragraph': {
                'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
                'bullet': {'listId': 'synthetic', 'nestingLevel': depth,
                           'textStyle': {}},
                'elements': [{
                    'startIndex': index, 'endIndex': end,
                    'textRun': {'content': text + '\n', 'textStyle': {}},
                }],
            },
        })
        index = end
    return GoogleDocument.model_validate({
        'documentId': 'synthetic', 'title': 'Token measurement',
        'body': {'content': content},
        'lists': {'synthetic': {'listProperties': {
            'nestingLevels': [{'glyphType': 'DECIMAL'}] * 9,
        }}},
    }).to_markdown().rstrip()


def main() -> None:
    """Count raw fragments without MCP envelopes or surrounding content."""
    encoding = tiktoken.get_encoding('o200k_base')
    cases = [
        ('10 short items', [(SHORT, 0)] * 10),
        ('10 long items', [(LONG, 0)] * 10),
        ('8 short nested items', [(SHORT, depth)
                                  for depth in [0, 1, 2, 1, 0, 1, 2, 0]]),
    ]
    results = []
    for name, items in cases:
        markdown = '\n'.join('    ' * depth + '1. ' + text
                             for text, depth in items)
        # These controlled item texts have no embedded newlines. Remove the
        # parser's layout newlines to match the former compact HTML renderer.
        html = markdown_to_html(markdown).replace('\n', '')
        current = render_native(items)
        representations = {'markdown': markdown, 'compact_html': html,
                           'current_reader': current}
        results.append({
            'case': name, 'item_count': len(items),
            'characters_per_item': len(items[0][0]),
            'characters': {key: len(value)
                           for key, value in representations.items()},
            'tokens': {key: len(encoding.encode(value))
                       for key, value in representations.items()},
        })
    print(json.dumps({'tokenizer': 'o200k_base', 'cases': results},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
