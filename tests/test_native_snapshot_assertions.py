"""Ensure live cleanup checks distinguish URL rotation from document edits."""


from copy import deepcopy

import pytest

from .native_snapshot_assertions import assert_tabs_unchanged


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
