"""Fit unsized images to supported paged body paragraph layouts."""

import math


def _points(dimension):
    """Accept finite native point dimensions without guessing other units."""
    if not isinstance(dimension, dict) or dimension.get('unit') != 'PT':
        return None
    value = dimension.get('magnitude', 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _layout(document, index):
    """Resolve one ordinary body paragraph and its containing section."""
    style = document.get('documentStyle', {})
    if style.get('documentFormat', {}).get('documentMode') == 'PAGELESS':
        return None
    section = {}
    source = None
    for item in document.get('body', {}).get('content', []):
        if item.get('startIndex', 0) > index:
            break
        if 'sectionBreak' in item:
            section = item['sectionBreak'].get('sectionStyle', {})
        if (
            item.get('startIndex', 0) <= index < item.get('endIndex', 0)
            and 'paragraph' in item
        ):
            source = item['paragraph']
    if source is None or len(section.get('columnProperties', [])) > 1:
        return None
    page = style.get('pageSize', {})
    flipped = section.get('flipPageOrientation',
                          style.get('flipPageOrientation', False))
    dimension = 'height' if flipped else 'width'
    width = _points(page.get(dimension))
    margins = [
        _points(section.get(side, style.get(side)))
        for side in ('marginLeft', 'marginRight')
    ]
    if width is None or any(value is None for value in margins):
        return None
    return width - sum(margins), source


def paragraph_width(document, index, paragraph):
    """Resolve inherited styles and formatting applied by the insertion."""
    layout = _layout(document, index)
    if layout is None:
        return None
    width, source = layout
    overrides = paragraph.paragraph_style.model_dump(
        mode='json',
        by_alias=True,
        exclude_unset=True,
        exclude_defaults=True,
    )
    direct = source.get('paragraphStyle', {})
    named = {
        style.get('namedStyleType'): style.get('paragraphStyle', {})
        for style in document.get('namedStyles', {}).get('styles', [])
    }
    kind = overrides.get(
        'namedStyleType', direct.get('namedStyleType', 'NORMAL_TEXT')
    )
    effective = {
        **named.get('NORMAL_TEXT', {}),
        **named.get(kind, {}),
        **direct,
        **overrides,
    }
    if paragraph.bullet_preset:
        # The converter creates native lists from leading nesting tabs. Google
        # uses half-inch steps; continuation paragraphs set the same indent.
        effective['indentStart'] = {
            'magnitude': 36 * (paragraph.nesting_level + 1),
            'unit': 'PT',
        }
        effective['indentFirstLine'] = effective['indentStart']
    elif source.get('bullet'):
        bullet = source['bullet']
        levels = (
            document.get('lists', {})
            .get(bullet.get('listId'), {})
            .get(
                'listProperties',
                {},
            )
            .get('nestingLevels', [])
        )
        depth = bullet.get('nestingLevel', 0)
        if depth >= len(levels):
            return None
        effective = {
            **effective,
            **{
                key: value
                for key, value in levels[depth].items()
                if key.startswith('indent') and key not in direct
            },
        }
    indents = [
        _points(effective.get(key, {'unit': 'PT'}))
        for key in ('indentStart', 'indentFirstLine', 'indentEnd')
    ]
    if any(value is None for value in indents):
        return None
    start, first, end = indents
    width -= max(start, first) + end
    return width if math.isfinite(width) and width > 0 else None


def fit_images(requests, paragraphs, document, index):
    """Set only missing sizes; native Google computes aspect-ratio height."""
    # Lazy imports keep the converter and execution planner independent.
    from .md2requests import InsertionImage  # noqa: PLC0415

    images = (
        request['insertInlineImage']
        for request in requests
        if 'insertInlineImage' in request
    )
    for paragraph in paragraphs:
        width = None
        for element in paragraph.elements:
            if not isinstance(element, InsertionImage):
                continue
            request = next(images)
            if request.get('objectSize'):
                continue
            if width is None:
                width = paragraph_width(document, index, paragraph)
            if width is not None:
                request['objectSize'] = {
                    'width': {'magnitude': width, 'unit': 'PT'},
                }
