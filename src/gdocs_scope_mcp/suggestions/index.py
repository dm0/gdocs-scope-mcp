"""Locate native proposals and inherited effects without flattening text."""


from dataclasses import dataclass, field

from gdocs_scope_mcp.documents.tabs import select, walk
from gdocs_scope_mcp.suggestions.models import (
    SuggestionLocation,
    SuggestionNotice,
)

STYLE_LEVELS = {
    'TITLE': 0,
    'SUBTITLE': 1,
    **{f'HEADING_{level}': level + 1 for level in range(1, 7)},
}
DIRECT_FIELDS = {
    'suggestedInsertionIds',
    'suggestedDeletionIds',
    'suggestedTextStyleChanges',
    'suggestedParagraphStyleChanges',
    'suggestedBulletChanges',
    'suggestedTableStyleChanges',
    'suggestedTableRowStyleChanges',
    'suggestedTableCellStyleChanges',
    'suggestedPositionedObjectIds',
    'suggestedSectionStyleChanges',
}
NOTICE_ID_LIMIT = 100


def _overlap(left, right):
    return left[0] < right[1] and right[0] < left[1]


def scope_ranges(document, headings=None):
    """Resolve native heading subtrees, including hidden proposals."""
    content = document.get('body', {}).get('content', [])
    end = max((item.get('endIndex', 0) for item in content), default=0)
    if headings is None:
        return [(0, end)]
    visible = document.get('_mcp_heading_levels')
    unsafe = document.get('_mcp_unsafe_headings', set())
    if unsafe.intersection(headings):
        return None
    ranges = []
    for number, item in enumerate(content):
        style = item.get('paragraph', {}).get('paragraphStyle', {})
        if style.get('headingId') not in headings:
            continue
        level = (
            visible.get(style.get('headingId'), 100)
            if visible is not None
            else STYLE_LEVELS.get(style.get('namedStyleType'), 100)
        )
        stop = end
        for following in content[number + 1 :]:
            other = following.get('paragraph', {}).get('paragraphStyle', {})
            identity = other.get('headingId')
            if visible is not None and identity not in visible:
                continue
            other_level = (
                visible.get(identity, 100)
                if visible is not None
                else STYLE_LEVELS.get(other.get('namedStyleType'), 100)
            )
            if identity and other_level <= level:
                if identity in unsafe:
                    return None
                stop = following['startIndex']
                break
        ranges.append((item['startIndex'], stop))
    if headings and len(ranges) != len(set(headings)):
        return None
    return ranges


@dataclass
class ProposalIndex:
    """Retain locations per ID; thread presence alone never proves a range."""

    locations: dict[str, list[SuggestionLocation]] = field(
        default_factory=dict
    )
    unknown: bool = False

    def add(self, sid, location):
        """Deduplicate locations without accepting malformed proposal IDs."""
        if isinstance(sid, str) and sid:
            values = self.locations.setdefault(sid, [])
            if location not in values:
                values.append(location)
        else:
            self.unknown = True

    def relation(self, sid, tab_id, ranges):
        """Return true/false/unknown for a selected native fragment."""
        if ranges == []:
            return False
        locations = self.locations.get(sid, [])
        if not locations or ranges is None:
            return None
        unknown = False
        for location in locations:
            if location.tab_id not in {None, tab_id}:
                continue
            if not ranges:
                continue
            if location.segment_id is not None:
                continue
            if location.uncertain:
                if (
                    location.start_index is None
                    or location.end_index is None
                    or any(
                        _overlap((location.start_index, location.end_index), r)
                        for r in ranges
                    )
                ):
                    unknown = True
            elif location.inherited and location.start_index is None:
                return True
            elif location.start_index is None or location.end_index is None:
                unknown = True
            elif any(
                _overlap((location.start_index, location.end_index), r)
                for r in ranges
            ):
                return True
        return None if unknown else False

    def notice(self, document, headings=None, *, unavailable=False):
        """Bound selected IDs and distinguish uncertain inherited effects."""
        ranges = scope_ranges(document, headings)
        relations = {
            sid: self.relation(sid, document.get('_mcp_tab_id'), ranges)
            for sid in self.locations
        }
        ids = sorted(
            sid for sid, match in relations.items() if match is not False
        )
        uncertain = (
            unavailable
            or self.unknown
            or ranges is None
            or bool(document.get('_mcp_unsafe_headings'))
            or any(
                location.uncertain
                for values in self.locations.values()
                for location in values
            )
        )
        selected = any(value is True for value in relations.values())
        if not selected and (
            uncertain or any(value is None for value in relations.values())
        ):
            selected = None
        if ranges == []:
            selected = False
        pending = bool(self.locations) or (None if uncertain else False)
        return SuggestionNotice(
            document_has_pending=pending,
            selected_content_has_pending=selected,
            suggestion_ids=ids[:NOTICE_ID_LIMIT],
            suggestion_ids_truncated=len(ids) > NOTICE_ID_LIMIT,
            unavailable_heading_ids=sorted(
                document.get(
                    '_mcp_unsafe_headings',
                    set(),
                )
            )[:NOTICE_ID_LIMIT],
            detection='unavailable'
            if unavailable
            else (
                'partial'
                if uncertain or None in relations.values()
                else 'complete'
            ),
            warnings=[
                'Some proposal locations or inherited effects could '
                'not be determined.'
            ]
            if uncertain or None in (relations.values())
            else [],
        )


def index_document(native):
    """Scan every tab and expand known shared definitions to their users."""
    result = ProposalIndex()
    tabs = [
        select(native, tab['tabProperties']['tabId'])
        for tab, *_ in walk(native.get('tabs', []))
    ]
    if not tabs:
        tabs = [select(native)]
    for tab in tabs:
        _scan_tab(tab, result)
    for thread in native.get('suggestions', []):
        sid = thread.get('suggestionId')
        if thread.get('status') == 'OPEN' and sid not in result.locations:
            result.add(
                sid,
                SuggestionLocation(
                    kind='thread_without_source_metadata',
                    uncertain=True,
                ),
            )
    return result


def _scan_tab(document, result):
    tab_id = document.get('_mcp_tab_id')
    paragraphs = []

    def paragraphs_in(value):
        if isinstance(value, dict):
            if 'paragraph' in value:
                paragraphs.append(value)
            for child in value.values():
                paragraphs_in(child)
        elif isinstance(value, list):
            for child in value:
                paragraphs_in(child)

    paragraphs_in(document.get('body', {}))

    def visit(value, span=(None, None), segment=None, dependency=None):
        if isinstance(value, list):
            for child in value:
                visit(child, span, segment, dependency)
            return
        if not isinstance(value, dict):
            return
        span = (
            value.get('startIndex', span[0]),
            value.get('endIndex', span[1]),
        )
        for key, child in value.items():
            if key.startswith('suggested'):
                ids = (
                    list(child)
                    if isinstance(child, dict)
                    else child
                    if isinstance(child, list)
                    else []
                )
                if not ids and child:
                    result.unknown = True
                for sid in ids:
                    location = SuggestionLocation(
                        tab_id=tab_id,
                        segment_id=segment,
                        start_index=span[0],
                        end_index=span[1],
                        kind=key,
                        inherited=dependency is not None,
                        uncertain=key not in DIRECT_FIELDS,
                    )
                    if dependency is None:
                        result.add(sid, location)
                    else:
                        _inherited(
                            result,
                            sid,
                            location,
                            dependency,
                            paragraphs=paragraphs,
                        )
                continue
            if key in {
                'lists',
                'inlineObjects',
                'positionedObjects',
                'dropdownDefinitions',
            } and isinstance(child, dict):
                for identity, definition in child.items():
                    visit(definition, (None, None), segment, (key, identity))
            elif key in {'namedStyles', 'documentStyle'}:
                visit(child, (None, None), segment, (key, None))
            elif key == 'sectionBreak' and segment is None:
                content = document.get('body', {}).get('content', [])
                stop = next(
                    (
                        item['startIndex']
                        for item in content
                        if 'sectionBreak' in item
                        and item.get('startIndex', 0) > (span[0] or 0)
                    ),
                    max(
                        (item.get('endIndex', 0) for item in content),
                        default=0,
                    ),
                )
                visit(child, (span[0] or 0, stop), segment, dependency)
            elif key in {'headers', 'footers', 'footnotes'}:
                for identity, definition in child.items():
                    visit(definition, (None, None), identity)
            elif key not in {'_mcp_tabs', 'comments', 'suggestions'}:
                visit(child, span, segment, dependency)

    # Treat shared style maps as inherited, not as an unlocated local change.
    for key, value in document.items():
        if key in {
            'suggestedDocumentStyleChanges',
            'suggestedNamedStylesChanges',
        }:
            dependency = (
                'documentStyle'
                if key.startswith('suggestedDocument')
                else 'namedStyles',
                None,
            )
            visit({key: value}, dependency=dependency)
        elif key not in {
            'documentId',
            'title',
            'revisionId',
            '_mcp_tabs',
            'suggestions',
            'comments',
        }:
            visit({key: value})


def _inherited(result, sid, location, dependency, *, paragraphs):
    collection, identity = dependency
    if collection == 'namedStyles':
        # Google renders the accepted view. Exact named-style inheritance is
        # outside our style-management scope; do not claim no local effect.
        result.add(sid, location)
        return
    if collection == 'documentStyle':
        result.add(
            sid,
            location.model_copy(
                update={
                    'uncertain': False,
                    'inherited': True,
                }
            ),
        )
        return
    matches = []
    for item in paragraphs:
        paragraph = item['paragraph']
        if collection == 'lists':
            match = paragraph.get('bullet', {}).get('listId') == identity
        else:
            # Object definitions may be referenced inside a run or chip.
            field_name = {
                'inlineObjects': 'inlineObjectId',
                'positionedObjects': 'positionedObjectIds',
                'dropdownDefinitions': 'dropdownDefinitionId',
            }[collection]

            def referenced(value, field_name=field_name):
                if isinstance(value, dict):
                    if value.get(field_name) == identity:
                        return True
                    if field_name == 'positionedObjectIds' and identity in (
                        value.get(field_name, [])
                    ):
                        return True
                    return any(referenced(v) for v in value.values())
                return (
                    any(referenced(v) for v in value)
                    if isinstance(value, list)
                    else False
                )

            match = referenced(paragraph)
        if match:
            matches.append(item)
    for item in matches:
        result.add(
            sid,
            location.model_copy(
                update={
                    'start_index': item.get('startIndex'),
                    'end_index': item.get('endIndex'),
                    'uncertain': False,
                }
            ),
        )
    if not matches and sid not in result.locations:
        # Retain document-wide presence even for an unused shared definition.
        result.add(
            sid,
            location.model_copy(
                update={
                    'start_index': 0,
                    'end_index': 0,
                    'uncertain': False,
                }
            ),
        )
