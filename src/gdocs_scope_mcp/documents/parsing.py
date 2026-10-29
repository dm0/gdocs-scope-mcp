"""Internal documents.parsing operations."""


from copy import deepcopy
from dataclasses import dataclass

from gdocs_scope_mcp.documents.models import (
    DocumentParagraph,
    DocumentSection,
    DocumentTree,
)
from gdocs_scope_mcp.documents.native_models import (
    GoogleDocument,
    GoogleDocumentParagraph,
    GoogleDocumentSmartChip,
    GoogleDocumentTable,
)
from gdocs_scope_mcp.documents.styles import GoogleDocumentNamedStyleType


@dataclass
class TextRun:
    """Store plain text and its inclusive/exclusive document indices."""

    text: str
    start: int  # Document index (inclusive)
    end: int  # Document index (exclusive)


@dataclass
class Paragraph:
    """Store source indices and plain text for an editable paragraph."""

    text: str
    style: str
    start: int  # Start of paragraph including leading newline-like element
    end: int  # End of paragraph (exclusive)
    runs: list[TextRun]


def extract_paragraphs(doc: dict) -> list[Paragraph]:
    """Extract paragraphs with full structure from a Docs API response."""
    paragraphs = []
    for elem in doc.get('body', {}).get('content', []):
        if 'paragraph' not in elem:
            continue
        para = elem['paragraph']
        style = para.get('paragraphStyle', {}).get(
            'namedStyleType', 'NORMAL_TEXT'
        )
        runs = []
        full_text = ''
        for pe in para.get('elements', []):
            if 'textRun' in pe:
                content = pe['textRun']['content']
                runs.append(
                    TextRun(
                        text=content,
                        start=pe['startIndex'],
                        end=pe['endIndex'],
                    )
                )
                full_text += content
        # Strip trailing newline for display (Google Docs always ends
        # paragraphs with \n)
        display_text = full_text.rstrip('\n')
        paragraphs.append(
            Paragraph(
                text=display_text,
                style=style,
                start=elem['startIndex'],
                end=elem['endIndex'],
                runs=runs,
            )
        )
    return paragraphs


def paragraph_text_map(elements: list[dict]) -> list[tuple[int, int, str]]:
    """Keep original run positions while omitting non-text display elements."""
    text_map = []
    offset = 0
    for element in elements:
        if 'textRun' in element:
            text = element['textRun']['content']
            text_map.append((offset, element['startIndex'], text))
            offset += len(text)
    return text_map


def table_source_paragraphs(table: dict) -> list[DocumentParagraph]:
    """Retain cell paragraphs and their terminal boundaries in source order."""
    paragraphs = []
    for row in table['tableRows']:
        for cell in row['tableCells']:
            for item in cell['content']:
                if 'paragraph' in item:
                    text_map = paragraph_text_map(
                        item['paragraph']['elements'],
                    )
                    paragraphs.append(DocumentParagraph(
                        start_index=item['startIndex'],
                        end_index=item['endIndex'],
                        text=''.join(run[2] for run in text_map),
                        text_map=text_map,
                        markdown='',
                        table_cell_end_index=cell['endIndex'] - 1,
                    ))
                elif 'table' in item:
                    paragraphs.extend(table_source_paragraphs(item['table']))
    return paragraphs


def parse_document_tree(doc: dict) -> DocumentTree:
    """Extract document hierarchy from a Docs API response."""

    # Dummy section if there is text before headings
    last: DocumentSection = DocumentSection(
        title='',
        id='',
        level=GoogleDocumentNamedStyleType.NORMAL_TEXT.compact,
        paragraphs=[
            DocumentParagraph(start_index=0, end_index=0, text='', markdown='')
        ],
    )
    top_level: list[DocumentSection] = [last]

    # Model validators flatten API payloads in place; retain source text first.
    source_maps = [
        paragraph_text_map(
            source.get('paragraph', {}).get('elements', []),
        )
        for source in doc['body']['content']
    ]
    table_paragraphs = {
        source['startIndex']: table_source_paragraphs(source['table'])
        for source in doc['body']['content'] if 'table' in source
    }
    google_doc = GoogleDocument.model_validate(deepcopy(doc))

    headings = {}

    for text_map, elem in zip(
        source_maps, google_doc.body.content, strict=True,
    ):
        if not isinstance(elem, GoogleDocumentParagraph):
            # Display markup does not extend the preceding editable paragraph.
            last.paragraphs[-1].markdown += elem.to_markdown(google_doc)
            if isinstance(elem, GoogleDocumentTable):
                last.paragraphs.extend(table_paragraphs[elem.start_index])
            continue
        paragraph = DocumentParagraph(
            start_index=elem.start_index,
            end_index=elem.end_index,
            # Rendered paragraph separators are not editable source characters.
            text=''.join(run[2] for run in text_map),
            text_map=text_map,
            markdown=elem.to_markdown(google_doc),
        )
        if elem.paragraph_style.heading_id is None:
            last.paragraphs.append(paragraph)
            continue

        title = paragraph.text
        if any(isinstance(element, GoogleDocumentSmartChip)
               for element in elem.elements):
            title = ''.join(element.to_text(google_doc)
                            for element in elem.elements)
            if paragraph.text.endswith('\n'):
                title += '\n'
        section = DocumentSection(
            title=title,
            id=elem.paragraph_style.heading_id,
            level=elem.paragraph_style.named_style_type.compact,
            ancestor_ids=[],
            paragraphs=[paragraph],
            sections=[],
        )

        headings[section.id] = section

        # Nest under correct parent
        parent = last
        # Traverse up
        if parent.level_index > section.level_index:
            while parent and parent.level_index >= section.level_index:
                parent = parent.parent
        # The same level => use sibling parent
        elif parent.level_index == section.level_index:
            parent = parent.parent

        section.parent = parent
        if parent is not None:
            parent.sections.append(section)
            section.ancestor_ids = [*parent.ancestor_ids, parent.id]
        else:
            top_level.append(section)

        last = section
    # Remove dummy section if empty
    if not top_level[0].markdown:
        top_level = top_level[1:]
    return DocumentTree(
        sections=top_level,
        headings=headings,
        title=google_doc.title,
        revision_id=google_doc.revision_id,
        document_id=google_doc.document_id,
        tab_id=doc.get('_mcp_tab_id'), tab_title=doc.get('_mcp_tab_title'),
    )
