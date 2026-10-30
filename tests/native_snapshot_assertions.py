"""Compare live snapshots without temporary image download URLs."""


from copy import deepcopy

from bs4 import BeautifulSoup

from gdocs_scope_mcp.rich_text.parsing import markdown_to_html


def _stable_sections(sections):
    """Retain rendered content, literal code and stable image attributes."""
    result = deepcopy(sections)
    for section in result:
        html = BeautifulSoup(markdown_to_html(section['markdown']),
                             'html.parser')
        for image in html.find_all('img'):
            source = image.get('src')
            if isinstance(source, str) and source.startswith(
                ('https://', 'http://'),
            ):
                image['src'] = '<temporary image download URL>'
        section['markdown'] = str(html)
    return result


def assert_read_sections_equivalent(before, after):
    """Require equal rendered sections apart from renewable image sources.

    Use alongside native snapshot preservation checks, which retain image
    identity, source URI, geometry and order. Markdown is parsed first so image
    examples inside code remain literal text and are never normalized.
    """
    differences = _differing_paths(_stable_sections(before),
                                   _stable_sections(after))
    assert not differences, differences


def _stable_tabs(tabs):
    """Keep image identity, source, geometry and styling on a private copy."""
    result = deepcopy(tabs)
    for tab in result:
        document = tab.get('documentTab', {})
        for collection, properties in (
            ('inlineObjects', 'inlineObjectProperties'),
            ('positionedObjects', 'positionedObjectProperties'),
        ):
            for obj in document.get(collection, {}).values():
                image = obj.get(properties, {}).get(
                    'embeddedObject', {},
                ).get('imageProperties', {})
                # Google documents contentUri as a temporary (default 30 min)
                # download URL, not image identity. Keep the field's presence.
                # https://developers.google.com/workspace/docs/api/reference/
                # rest/v1/documents#ImageProperties
                if isinstance(image.get('contentUri'), str):
                    image['contentUri'] = '<temporary image download URL>'
        if 'childTabs' in tab:
            tab['childTabs'] = _stable_tabs(tab['childTabs'])
    return result


def _differing_paths(before, after, path=''):
    """Locate changes without logging document text or signed URLs."""
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        return [
            changed
            for key in sorted(before.keys() | after.keys())
            for changed in (
                _differing_paths(before[key], after[key], f'{path}/{key}')
                if key in before and key in after else [f'{path}/{key}']
            )
        ]
    if isinstance(before, list):
        if len(before) != len(after):
            return [path + '/length']
        return [
            changed
            for index, (left, right) in enumerate(zip(before, after))
            for changed in _differing_paths(left, right, f'{path}/{index}')
        ]
    return [] if before == after else [path]


def assert_tabs_unchanged(before, after):
    """Require unchanged native content and report differing field paths."""
    differences = _differing_paths(_stable_tabs(before), _stable_tabs(after))
    assert not differences, differences
