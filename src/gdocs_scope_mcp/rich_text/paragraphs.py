"""Internal rich_text.paragraphs responsibilities."""

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString, PageElement
from pydantic import ValidationError

from gdocs_scope_mcp.code_highlighting import code_shading, code_spans
from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.native_models import (
    GoogleDocumentColor,
    GoogleDocumentLink,
    GoogleDocumentOptionalColor,
    GoogleDocumentParagraphStyle,
    GoogleDocumentRgbColor,
    GoogleDocumentTextRun,
    GoogleDocumentTextStyle,
    GoogleDocumentWeightedFontFamily,
)
from gdocs_scope_mcp.documents.styles import (
    GoogleDocumentAlignment,
    GoogleDocumentBaselineOffset,
    GoogleDocumentNamedStyleType,
)
from gdocs_scope_mcp.entities import chip_input, insertion_request
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.rich_text.models import (
    InsertionChip,
    InsertionCodeRun,
    InsertionImage,
    InsertionParagraph,
    InsertionTable,
)
from gdocs_scope_mcp.rich_text.validation import (
    IMAGE_URI_MAX_BYTES,
    image_failure,
    unsupported_list,
    unsupported_table,
)
from gdocs_scope_mcp.settings import get_code_settings
from gdocs_scope_mcp.text_indices import utf16_length


def _convert_image(element: Tag, start: int) -> InsertionImage:
    """Validate an image and convert pixel dimensions to points."""
    uri = str(element.get('src', ''))
    try:
        parsed = urlsplit(uri)
        valid = (
            parsed.scheme.lower() in {'http', 'https'} and parsed.hostname
            and not parsed.username and not parsed.password
            and len(uri.encode('utf-8')) <= IMAGE_URI_MAX_BYTES
            and not re.search(r'[\s\x00-\x1f\x7f]', uri)
        )
    except ValueError:
        valid = False
    if not valid:
        image_failure('Image src must be an absolute HTTP(S) URL of at '
                       'most 2 kB, without whitespace or credentials.')
    if any(element.get(key) for key in ('style', 'srcset', 'sizes')):
        image_failure('CSS image styling and responsive image sources are '
                       'unsupported.')
    size = {}
    for dimension in ('width', 'height'):
        if dimension not in element.attrs:
            continue
        value = str(element[dimension]).strip()
        if not re.fullmatch(r'\d+(?:\.\d+)?(?:px)?', value):
            image_failure('Image dimensions must be positive pixel numbers.')
        pixels = float(value.removesuffix('px'))
        if not 0 < pixels < float('inf'):
            image_failure('Image dimensions must be finite and positive.')
        size[dimension] = {'magnitude': pixels * 0.75, 'unit': 'PT'}
    return InsertionImage(
        start_index=start, end_index=start + 1, uri=uri, object_size=size,
    )


def _convert_list(
    element: Tag, start: int, *, level: int = 0, list_key: int | None = None,
    component_path: tuple[int, ...] = (),
) -> list[InsertionParagraph]:
    """Preserve logical item membership and paragraph roles in source order."""
    if list_key is None:
        list_key = start
    if element.name == 'ol' and str(element.get('start', '1')) != '1':
        unsupported_list('Custom ordered-list starting numbers are '
                          'unsupported.')
    result = []
    for item in element.find_all('li', recursive=False):
        if item.find('table') is not None:
            unsupported_table('Tables inside lists are unsupported.')
        if item.find('pre') is not None:
            unsupported_list('Code blocks inside list items are unsupported.')
        item_key = start
        item_paragraphs = 0
        blocks = []

        def flush(blocks=blocks, item_key=item_key, item=item):
            """Convert a paragraph while preserving its logical item role."""
            nonlocal start, item_paragraphs
            paragraph = InsertionParagraph(
                start_index=start, elements=[],
                paragraph_style=GoogleDocumentParagraphStyle(
                    named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
                ),
            )
            extra = _convert_page_elements(blocks, paragraph)
            for part in [paragraph, *extra]:
                if not len(part):
                    continue
                part.list_key = list_key
                part.list_component_path = component_path
                part.item_key = item_key
                part.nesting_level = level
                part.continuation = item_paragraphs > 0
                part.loose_list = bool(element.find('p', recursive=False)
                                       or item.find('p', recursive=False))
                part.bullet_preset = (
                    'NUMBERED_DECIMAL_ALPHA_ROMAN' if element.name == 'ol'
                    else 'BULLET_DISC_CIRCLE_SQUARE'
                )
                result.append(part)
                start = part.start_index + len(part)
                item_paragraphs += 1
            blocks.clear()

        for child in item.children:
            if isinstance(child, Tag) and child.name in {'ul', 'ol'}:
                flush()
                if not item_paragraphs:
                    unsupported_list('List items must start with a nonempty '
                                      'ordinary paragraph.')
                child_path = component_path
                if child.name != element.name:
                    child_path += (start,)
                children = _convert_list(
                    child, start, level=level + 1, list_key=list_key,
                    component_path=child_path,
                )
                result.extend(children)
                if children:
                    start = children[-1].start_index + len(children[-1])
            elif isinstance(child, Tag) and child.name == 'p':
                flush()
                blocks.append(child)
                flush()
            else:
                if isinstance(child, Tag) and (
                    child.name in {'blockquote', 'div', 'hr', 'input'}
                    or re.fullmatch(r'h\d+', child.name)
                ):
                    unsupported_list('Only ordinary paragraphs and nested '
                                      'lists are supported inside items.')
                blocks.append(child)
        flush()
        if not item_paragraphs:
            unsupported_list('List items must contain a nonempty paragraph.')
    return result


def _collect_styles(
    element: PageElement, stop: PageElement
) -> GoogleDocumentTextStyle:
    style = GoogleDocumentTextStyle()
    parent = element.parent
    while parent and parent != stop:
        if parent.name in ['b', 'strong']:
            style.bold = True
        if parent.name in ['i', 'em']:
            style.italic = True
        if parent.name == 'u':
            style.underline = True
        if parent.name in ['s', 'del']:
            style.strikethrough = True
        if parent.name == 'code':
            settings = get_code_settings()
            style.weighted_font_family = GoogleDocumentWeightedFontFamily(
                font_family=settings.code_font_family,
            )
            color = settings.inline_code_color.removeprefix('#')
            style.foreground_color = GoogleDocumentOptionalColor(
                color=GoogleDocumentColor(rgb_color=GoogleDocumentRgbColor(
                    red=int(color[:2], 16) / 255,
                    green=int(color[2:4], 16) / 255,
                    blue=int(color[4:], 16) / 255,
                )),
            )
        if parent.name == 'a' and parent.get('href'):
            style.link = GoogleDocumentLink(url=parent['href'])
        if parent.name == 'sup':
            style.baseline_offset = GoogleDocumentBaselineOffset.SUPERSCRIPT
        if parent.name == 'sub':
            style.baseline_offset = GoogleDocumentBaselineOffset.SUBSCRIPT
        parent = parent.parent
    return style


def _convert_page_elements(
    elements: Iterable[PageElement], paragraph: InsertionParagraph,
    *, table_converter=None,
) -> list[InsertionParagraph | InsertionTable]:
    added = []
    last = paragraph
    for element in elements:
        if isinstance(element, NavigableString) or (
            isinstance(element, Tag) and element.name == 'br'
        ):
            content = ('\u000b' if isinstance(element, Tag) else str(element))
            start_index = last.start_index + len(last)
            text_run = GoogleDocumentTextRun(
                content=content,
                start_index=start_index,
                text_style=_collect_styles(element, element),
            )
            if not len(text_run):
                continue
            end_index = start_index + len(text_run)
            text_run.end_index = end_index
            last.elements.append(text_run)
            last.end_index = end_index
            continue
        if isinstance(element, Tag):
            if element.has_attr('data-mcp-entity'):
                try:
                    entity = chip_input(element.attrs)
                except (ValidationError, ValueError, KeyError):
                    raise ToolFailureError(EditFailedResponse(
                        code='INVALID_ARGUMENT',
                        description='Invalid smart-chip HTML attributes.',
                        suggested_action='Use the data-mcp-entity and '
                        'identity properties emitted by docs_read; labels '
                        'alone cannot define a native chip.',
                    )) from None
                if element.find(attrs={'data-mcp-entity': True}):
                    raise ToolFailureError(EditFailedResponse(
                        code='INVALID_ARGUMENT',
                        description='Nested smart-chip HTML is unsupported.',
                        suggested_action='Use separate inline smart chips.',
                    ))
                kind, payload = insertion_request(entity)
                start = last.start_index + len(last)
                last.elements.append(InsertionChip(
                    start_index=start, end_index=start + 1,
                    request_kind=kind, payload=payload,
                ))
                last.end_index = start + 1
                continue
            if element.name == 'table':
                start = last.start_index + len(last)
                if table_converter is None:
                    unsupported_table('Nested tables are unsupported.')
                added.append(table_converter(element, start))
                last = InsertionParagraph(
                    start_index=start, end_index=start, elements=[],
                    paragraph_style=GoogleDocumentParagraphStyle(),
                )
                added.append(last)
                continue
            if element.name == 'pre':
                # Mistune adds one terminal newline to a fenced block. The
                # surrounding paragraph break represents that terminator;
                # all other whitespace must survive unchanged.
                content = element.get_text().removesuffix('\n')
                start = last.start_index + len(last)
                code = element.find('code')
                classes = code.get('class', []) if code else []
                language = next((name.removeprefix('language-')
                                 for name in classes
                                 if name.startswith('language-')), None)
                runs = []
                end = start
                for value, style in code_spans(content, language):
                    run = InsertionCodeRun(
                        start_index=end, end_index=end + utf16_length(value),
                        content=value, text_style=style,
                    )
                    runs.append(run)
                    end = run.end_index
                last = InsertionParagraph(
                    start_index=start, end_index=end, elements=runs,
                    code_block=True, code_language=language,
                    paragraph_style=GoogleDocumentParagraphStyle(
                        named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
                        line_spacing=(
                            get_code_settings().code_block_line_spacing * 100
                        ),
                        shading=code_shading(run.text_style for run in runs),
                    ),
                )
                added.append(last)
                continue
            if element.name == 'img':
                start = last.start_index + len(last)
                last.elements.append(_convert_image(element, start))
                last.end_index = start + 1
                continue
            if element.name == 'picture':
                image_failure('HTML picture/source selection is unsupported; '
                               'use a single img with src.')
            if element.name in {'ul', 'ol'}:
                added.extend(_convert_list(
                    element, last.start_index + len(last),
                ))
                last = added[-1] if added else paragraph
                continue
            if element.name == 'p':
                align = GoogleDocumentAlignment.ALIGNMENT_UNSPECIFIED

                if (
                    element.has_attr('style')
                    and 'text-align' in element['style']
                ):
                    if 'center' in element['style']:
                        align = GoogleDocumentAlignment.CENTER
                    elif 'right' in element['style']:
                        align = GoogleDocumentAlignment.END
                    elif 'justify' in element['style']:
                        align = GoogleDocumentAlignment.JUSTIFIED

                added.append(
                    InsertionParagraph(
                        start_index=last.start_index + len(last),
                        elements=[],
                        paragraph_style=GoogleDocumentParagraphStyle(
                            named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
                            alignment=align,
                        ),
                    )
                )
            elif match := re.match(r'h(?P<level>\d+)', element.name):
                # FIXME: Implement
                added.append(
                    InsertionParagraph(
                        start_index=last.start_index + len(last),
                        elements=[],
                        paragraph_style=GoogleDocumentParagraphStyle(
                            named_style_type=GoogleDocumentNamedStyleType.from_level(
                                int(match['level'])
                            )
                        ),
                    )
                )
            # FIXME: Implement other supported elements
            last = added[-1] if added else paragraph
            added.extend(_convert_page_elements(
                element.children, last, table_converter=table_converter,
            ))
            continue
        # Unsupported element kind
        # TODO: Log this
        print(f'Skipped: {element}')
        continue
    return added


def parse_html(
    html: str, start: int = 0, *, table_converter=None,
) -> list[InsertionParagraph | InsertionTable]:
    """Convert HTML into indexed paragraphs and structural table plans."""
    bs = BeautifulSoup(html, 'html.parser')
    current_index = start
    paragraphs: list[InsertionParagraph | InsertionTable] = [
        InsertionParagraph(
            start_index=current_index,
            elements=[],
            paragraph_style=GoogleDocumentParagraphStyle(
                named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT
            ),
        )
    ]

    paragraphs.extend(_convert_page_elements(
        bs.contents, paragraphs[-1], table_converter=table_converter,
    ))
    return paragraphs
