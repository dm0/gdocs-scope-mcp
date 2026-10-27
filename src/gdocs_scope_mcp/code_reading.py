"""Recover Markdown code from document markers and configurable formatting."""

import json
import re
from collections.abc import Iterator
from itertools import pairwise
from urllib.parse import quote, unquote
from uuid import uuid4

from .settings import get_settings

MARKER_PREFIX = 'gdocs-scope-mcp:code:v1:'
MAX_MARKER_LENGTH = 256
SPACING_TOLERANCE = 0.01
# Observed in API snapshots of UI-created code blocks; not an API contract.
NATIVE_CODE_BOUNDARY = '\ue907'
_MARKER = re.compile(re.escape(MARKER_PREFIX) + r'([0-9a-f]{32}):([^:]*)')


def block_marker(language: str | None, start: int, end: int) -> dict:
    """Attach a versioned language label without visible document text."""
    encoded = quote(language or '', safe='')
    name = f'{MARKER_PREFIX}{uuid4().hex}:{encoded}'
    if len(name) > MAX_MARKER_LENGTH:
        raise ValueError('Code language label is too long for a named range')
    return {'createNamedRange': {
        'name': name, 'range': {'startIndex': start, 'endIndex': end},
    }}


def _delimiter(text: str, *, minimum: int) -> str:
    """Choose backticks longer than any run contained in literal source."""
    longest = max((len(m[0]) for m in re.finditer(r'`+', text)), default=0)
    return '`' * max(minimum, longest + 1)


def code_span(text: str) -> str:
    """Encode code-span edge spaces and backticks using CommonMark padding."""
    delimiter = _delimiter(text, minimum=1)
    if text.startswith('`') or text.endswith('`') or (
        text.startswith(' ') and text.endswith(' ') and text.strip(' ')
    ):
        text = f' {text} '
    return f'{delimiter}{text}{delimiter}'


def fenced_code(text: str, language: str = '') -> str:
    """Keep literal whitespace and exclude unsafe Markdown info strings."""
    delimiter = _delimiter(text, minimum=3)
    if any(character in language for character in '\r\n`'):
        language = ''
    return f'{delimiter}{language}\n{text}\n{delimiter}\n\n'


def _color(style: dict) -> str | None:
    """Normalize Google's optional RGB fields to byte-valued hex colors."""
    rgb = style.get('foregroundColor', {}).get('color', {}).get('rgbColor')
    if rgb is None:
        return None
    return '#' + ''.join(f'{round(rgb.get(c, 0) * 255):02X}'
                         for c in ('red', 'green', 'blue'))


def inline_style(style: dict) -> bool:
    """Apply the configured font/color policy without inferring a language."""
    settings = get_settings()
    if not settings.read_inline_code:
        return False
    fonts = (settings.read_inline_code_fonts if
             settings.read_inline_code_fonts is not None else
             [settings.code_font_family])
    colors = (settings.read_inline_code_colors if
              settings.read_inline_code_colors is not None else
              [settings.inline_code_color])
    font = style.get('weightedFontFamily', {}).get('fontFamily', '')
    font_matches = font.casefold() in {f.casefold() for f in fonts}
    color_matches = _color(style) in {c.upper() for c in colors}
    return {'font': font_matches, 'color': color_matches,
            'both': font_matches and color_matches}[
                settings.read_inline_code_match]


def inline_markdown(elements: list, doc) -> str:
    """Join adjacent code runs despite unrelated emphasis or link styles."""
    result = []
    pending = ''
    for element in elements:
        if element.type == 'textRun' and inline_style(
            element.text_style.model_dump(by_alias=True, exclude_none=True),
        ) and '\u000b' not in element.content:
            pending += element.content
            continue
        if pending:
            result.append(code_span(pending))
            pending = ''
        result.append(element.to_markdown(doc))
    if pending:
        result.append(code_span(pending))
    return ''.join(result)


def _containers(content: list[dict]) -> Iterator[list[dict]]:
    """Keep table cells separate so blocks never span structural boundaries."""
    yield content
    for item in content:
        for row in item.get('table', {}).get('tableRows', []):
            for cell in row.get('tableCells', []):
                yield from _containers(cell.get('content', []))


def _paragraph_text(item: dict) -> str | None:
    """Accept contiguous text-only normal paragraphs, including blank lines."""
    paragraph = item.get('paragraph', {})
    style = paragraph.get('paragraphStyle', {})
    if (not paragraph or paragraph.get('bullet') or style.get('headingId')
            or style.get('namedStyleType', 'NORMAL_TEXT') != 'NORMAL_TEXT'):
        return None
    cursor = item['startIndex']
    chunks = []
    for element in paragraph.get('elements', []):
        if 'textRun' not in element or element.get('startIndex') != cursor:
            return None
        chunks.append(element['textRun']['content'])
        cursor = element['endIndex']
    text = ''.join(chunks)
    if cursor != item['endIndex'] or not text.endswith('\n'):
        return None
    return text


def _marked_blocks(
    doc: dict, containers: list[list[dict]],
) -> tuple[dict, set]:
    """Reject malformed, split and overlapping markers instead of guessing."""
    candidates = []
    blocked = set()
    reserved = []
    for group in doc.get('namedRanges', {}).values():
        for named in group.get('namedRanges', []):
            name = named.get('name', group.get('name', ''))
            if not name.startswith('gdocs-scope-mcp:code:'):
                continue
            spans = named.get('ranges', [])
            for span in spans:
                left = span.get('startIndex', -1)
                right = span.get('endIndex', -1)
                reserved.append((left, right))
                for content in containers:
                    blocked.update(p.get('startIndex') for p in content
                                   if p.get('startIndex', -1) < right
                                   and p.get('endIndex', -1) > left)
            match = _MARKER.fullmatch(name)
            if not match or len(spans) != 1:
                continue
            span = spans[0]
            if span.get('segmentId'):
                continue
            start, end = span.get('startIndex', -1), span.get('endIndex', -1)
            if end <= start:
                continue
            for content in containers:
                selected = [p for p in content
                            if start <= p.get('startIndex', -1) <= end]
                # An end at a paragraph start can represent a trailing blank
                # line, but must never include the next nonempty paragraph.
                selected = [p for p in selected if p['startIndex'] < end
                            or _paragraph_text(p) == '\n']
                if not selected or selected[0]['startIndex'] != start:
                    continue
                last = selected[-1]
                if end != last['endIndex'] - 1 and not (
                    len(selected) == 1 and _paragraph_text(last) == '\n'
                    and end == last['endIndex']
                ):
                    continue
                texts = [_paragraph_text(p) for p in selected]
                if any(t is None for t in texts) or any(
                    a['endIndex'] != b['startIndex']
                    for a, b in pairwise(selected)
                ):
                    continue
                candidates.append((start, end, selected, ''.join(texts)[:-1],
                                   unquote(match[2])))
    result = {}
    for start, end, selected, text, language in candidates:
        if sum(a < end and b > start for a, b in reserved) != 1:
            continue
        result[start] = fenced_code(text, language)
        result.update({p['startIndex']: '' for p in selected[1:]})
    return result, blocked


def _heuristic_signature(item: dict, text: str | None) -> tuple | None:
    """Require explicit paragraph spacing and code fonts together."""
    settings = get_settings()
    style = item.get('paragraph', {}).get('paragraphStyle', {})
    spacing = style.get('lineSpacing')
    if text is None or spacing is None or abs(
        spacing - settings.read_code_block_line_spacing * 100
    ) > SPACING_TOLERANCE:
        return None
    background = style.get('shading', {}).get('backgroundColor', {})
    if (settings.read_code_block_require_background
            and not background.get('color')):
        return None
    fonts = (settings.read_code_block_fonts if
             settings.read_code_block_fonts is not None else
             [settings.code_font_family])
    for element in item['paragraph']['elements']:
        run = element['textRun']
        if not run['content'].strip('\n'):
            continue
        font = run.get('textStyle', {}).get('weightedFontFamily', {}).get(
            'fontFamily', '',
        )
        if font.casefold() not in {f.casefold() for f in fonts}:
            return None
    return (spacing, json.dumps(background, sort_keys=True))


def _native_blocks(content: list, result: dict, blocked: set) -> None:
    """Recognize observed UI delimiters around contiguous code-font runs."""
    settings = get_settings()
    fonts = (settings.read_code_block_fonts if
             settings.read_code_block_fonts is not None else
             [settings.code_font_family])
    fonts = {font.casefold() for font in fonts}
    pending = []
    chunks = []
    for item in content:
        text = _paragraph_text(item)
        if (text is None or item.get('startIndex') in blocked
                or item.get('startIndex') in result or (pending and
                pending[-1]['endIndex'] != item['startIndex'])):
            pending, chunks = [], []
            continue
        if pending and text == NATIVE_CODE_BOUNDARY + '\n':
            # Both delimiters must have their own API text run. A matching
            # private-use character in ordinary source is not enough.
            elements = item['paragraph']['elements']
            if elements[0]['textRun']['content'] == NATIVE_CODE_BOUNDARY:
                result[pending[0]['startIndex']] = fenced_code(
                    ''.join(chunks).removesuffix('\n'),
                )
                result.update({p['startIndex']: '' for p in pending[1:]})
                result[item['startIndex']] = ''
            pending, chunks = [], []
            continue
        elements = item['paragraph']['elements']
        if not pending:
            if elements[0]['textRun']['content'] != NATIVE_CODE_BOUNDARY:
                continue
            elements = elements[1:]
            text = text.removeprefix(NATIVE_CODE_BOUNDARY)
        if NATIVE_CODE_BOUNDARY in text or not all(
            not element['textRun']['content'].strip('\n') or
            element['textRun'].get('textStyle', {}).get(
                'weightedFontFamily', {},
            ).get('fontFamily', '').casefold() in fonts
            for element in elements
        ):
            pending, chunks = [], []
            continue
        pending.append(item)
        chunks.append(text)


def _flush_heuristic(pending: list, result: dict, minimum: int) -> None:
    """Trim uncertain blank edges but retain internal blank lines."""
    while pending and not pending[0][1].strip():
        pending.pop(0)
    while pending and not pending[-1][1].strip():
        pending.pop()
    if len(pending) >= minimum:
        result[pending[0][0]['startIndex']] = fenced_code(
            ''.join(text for _, text in pending)[:-1],
        )
        result.update({p['startIndex']: '' for p, _ in pending[1:]})
    pending.clear()


def block_markdown(doc: dict) -> dict[int, str]:
    """Compute block overrides before normalizing raw API text."""
    containers = list(_containers(doc.get('body', {}).get('content', [])))
    settings = get_settings()
    result, blocked = (_marked_blocks(doc, containers)
                       if settings.code_block_named_ranges else ({}, set()))
    if not settings.read_code_block_heuristic:
        return result
    for content in containers:
        _native_blocks(content, result, blocked)
        pending = []
        signature = None

        for item in content:
            text = _paragraph_text(item)
            current = _heuristic_signature(item, text)
            if (item.get('startIndex') in result
                    or item.get('startIndex') in blocked):
                current = None
            if (current is None or current != signature or (pending
                    and pending[-1][0]['endIndex'] != item['startIndex'])):
                _flush_heuristic(pending, result,
                                 settings.read_code_block_min_lines)
            signature = current
            if current is not None:
                pending.append((item, text))
        _flush_heuristic(pending, result, settings.read_code_block_min_lines)
    return result
