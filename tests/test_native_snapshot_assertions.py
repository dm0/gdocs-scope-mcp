"""Ensure live cleanup checks distinguish URL rotation from document edits."""


from copy import deepcopy

import pytest

from .native_snapshot_assertions import (
    assert_read_sections_equivalent,
    assert_tabs_unchanged,
)


@pytest.fixture
def read_sections():
    """Mix actual images with source-like text that must stay significant."""
    return [{'heading_id': 'heading', 'markdown': (
        '## Heading\n\nKeep this text.\n\n'
        '<img src="https://temporary.example/old" alt="first" width="100">'
        '<img src="https://temporary.example/second" alt="second">\n\n'
        '[Link](https://link.example/original)\n\n'
        '```html\n<img src="https://code.example/original">\n```\n\n'
        '`<img src="https://inline.example/original">`'
    )}]


def test_read_sections_allow_rotated_image_urls(read_sections):
    """Renewable URLs can differ without changing either input snapshot."""
    original = deepcopy(read_sections)
    after = deepcopy(read_sections)
    after[0]['markdown'] = after[0]['markdown'].replace(
        'https://temporary.example/old', 'https://temporary.example/renewed',
    )
    assert_read_sections_equivalent(read_sections, after)
    assert read_sections == original
    assert 'https://temporary.example/renewed' in after[0]['markdown']


@pytest.mark.parametrize(('old', 'new'), [
    ('Keep this text.', 'Changed text.'),
    ('## Heading', '### Heading'),
    ('alt="first"', 'alt="changed"'),
    ('width="100"', 'width="200"'),
    ('alt="first"', 'alt="second"'),
    ('src="https://temporary.example/old"', ''),
    ('https://temporary.example/old', ''),
    ('https://link.example/original', 'https://link.example/changed'),
    ('https://code.example/original', 'https://code.example/changed'),
    ('https://inline.example/original', 'https://inline.example/changed'),
])
def test_read_sections_reject_other_changes(read_sections, old, new):
    """Keep content, image attributes, hyperlinks and code in comparisons."""
    after = deepcopy(read_sections)
    after[0]['markdown'] = after[0]['markdown'].replace(old, new)
    with pytest.raises(AssertionError) as error:
        assert_read_sections_equivalent(read_sections, after)
    assert 'https://' not in str(error.value)


def test_read_sections_reject_changed_heading_identity(read_sections):
    """Matching rendered content cannot hide a different selected section."""
    after = deepcopy(read_sections)
    after[0]['heading_id'] = 'another-heading'
    with pytest.raises(AssertionError):
        assert_read_sections_equivalent(read_sections, after)


@pytest.fixture(params=['inline', 'positioned'])
def image_tabs(request):
    """Include nested tabs and both native image placement kinds."""
    kind = request.param
    return [{
        'tabProperties': {'tabId': 'parent', 'title': 'Parent'},
        'childTabs': [{
            'tabProperties': {'tabId': 'child', 'title': 'Child'},
            'documentTab': {
                'body': {'content': [{'paragraph': {'elements': [{
                    'textRun': {'content': 'Keep this text\n'},
                }]}}]},
                f'{kind}Objects': {'image-id': {
                    'objectId': 'image-id',
                    f'{kind}ObjectProperties': {'embeddedObject': {
                        'size': {'width': {'magnitude': 100, 'unit': 'PT'}},
                        'imageProperties': {
                            'contentUri': 'https://temporary.example/old',
                            'sourceUri': 'https://source.example/original',
                            'cropProperties': {'offsetLeft': 0},
                        },
                    }},
                }},
            },
        }],
    }]


def embedded(tabs):
    """Select the fixture image independently of its placement kind."""
    document = tabs[0]['childTabs'][0]['documentTab']
    collection = next(key for key in document if key.endswith('Objects'))
    obj = document[collection]['image-id']
    properties = next(key for key in obj if key.endswith('Properties'))
    return obj[properties]['embeddedObject']


def test_rotated_download_url_preserves_content(image_tabs):
    """The reproduced API-only URL change must not fail cleanup checks."""
    original = deepcopy(image_tabs)
    after = deepcopy(image_tabs)
    embedded(after)['imageProperties']['contentUri'] = (
        'https://temporary.example/renewed'
    )
    assert_tabs_unchanged(image_tabs, after)
    assert image_tabs == original
    assert embedded(after)['imageProperties']['contentUri'].endswith('renewed')


@pytest.mark.parametrize('change', [
    'source', 'crop', 'size', 'text', 'tab', 'remove_image', 'remove_url',
    'unrelated_content_uri',
])
def test_real_changes_still_fail_with_private_diagnostics(image_tabs, change):
    """Never hide an image replacement, layout edit or unrelated field."""
    after = deepcopy(image_tabs)
    child = after[0]['childTabs'][0]
    image = embedded(after)
    if change == 'source':
        image['imageProperties']['sourceUri'] = 'https://source.example/new'
    elif change == 'crop':
        image['imageProperties']['cropProperties']['offsetLeft'] = 0.25
    elif change == 'size':
        image['size']['width']['magnitude'] = 200
    elif change == 'text':
        child['documentTab']['body']['content'] = []
    elif change == 'tab':
        child['tabProperties']['title'] = 'Changed'
    elif change == 'remove_image':
        document = child['documentTab']
        collection = next(key for key in document if key.endswith('Objects'))
        del document[collection]['image-id']
    elif change == 'remove_url':
        del image['imageProperties']['contentUri']
    else:
        child['documentTab']['body']['contentUri'] = 'private value'
    with pytest.raises(AssertionError) as error:
        assert_tabs_unchanged(image_tabs, after)
    assert 'private value' not in str(error.value)
    assert 'https://' not in str(error.value)
