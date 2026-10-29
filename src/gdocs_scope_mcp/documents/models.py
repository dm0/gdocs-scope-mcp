"""Models owned by documents.models."""

import re
from collections.abc import Generator, Sequence
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
)
from typing_extensions import Self

from gdocs_scope_mcp.documents.styles import (
    HEADING_LEVELS,
    HEADING_ORDER_COMPACT,
)
from gdocs_scope_mcp.suggestions.models import SuggestionNotice


class DocumentOutlineItem(BaseModel):
    """A document section (heading)"""

    title: Annotated[str, Field(description='Heading title')]
    id: Annotated[str, Field(description='Heading id')]
    level: Annotated[str, Field(description='Heading level')]
    ancestor_ids: Annotated[
        list[str], Field(description='Parent headings')
    ] = []

    @property
    def level_index(self) -> int:
        """Return the relative nesting order of this outline item."""
        return HEADING_ORDER_COMPACT.get(self.level, len(HEADING_LEVELS))



class DocumentParagraph(BaseModel):
    """Retain a paragraph with source indices and rendered content."""

    start_index: int
    end_index: int
    text: str
    markdown: str
    table_cell_end_index: int | None = None
    # Python offset, original API UTF-16 start, unmodified run content.
    text_map: list[tuple[int, int, str]] = Field(
        default_factory=list, exclude=True,
    )



class SearchResult(BaseModel):
    """Locate matched text within its paragraph and heading section."""

    paragraph: DocumentParagraph
    section: 'DocumentSection'
    start_index: int
    end_index: int



class DocumentSection(DocumentOutlineItem):
    """An extended version that includes full parsed document details"""

    sections: list[Self] = []
    paragraphs: list[DocumentParagraph] = []
    parent: Annotated[Self | None, Field(exclude=True)] = None

    def descendants(self) -> Generator[Self, None, None]:
        """Yield nested sections in document order."""
        for child in self.sections:
            yield child
            yield from child.descendants()

    def subtree(self) -> Generator[Self, None, None]:
        """Yield this section followed by all nested sections."""
        yield self
        for child in self.sections:
            yield from child.subtree()

    def _find_text(
        self,
        search: str,
        case_sensitive: bool = True,
        first: bool = False,
        regex: bool = False,
    ) -> list[SearchResult]:
        if not case_sensitive and not regex:
            search = search.lower()
        flags = 0 if case_sensitive else re.IGNORECASE
        results = []
        for par in self.paragraphs:
            text = par.text if case_sensitive or regex else par.text.lower()
            pos = 0
            if regex:
                if first:
                    if match := re.search(search, text, flags=flags):
                        results.append(
                            SearchResult(
                                paragraph=par,
                                section=self,
                                start_index=match.start(),
                                end_index=match.end(),
                            )
                        )
                        return results
                    continue
                results.extend(
                    [
                        SearchResult(
                            paragraph=par,
                            section=self,
                            start_index=match.start(),
                            end_index=match.end(),
                        )
                        for match in re.finditer(search, text, flags=flags)
                    ]
                )
            else:
                while 0 <= (pos := text.find(search, pos)) < len(text):
                    results.append(
                        SearchResult(
                            paragraph=par,
                            section=self,
                            start_index=pos,
                            end_index=pos + len(search),
                        )
                    )
                    pos += 1
                    if first:
                        return results
        for child in self.sections:
            found = child._find_text(search, case_sensitive, first, regex)
            results.extend(found)
            if first and len(found) > 0:
                return found
        return results

    def find_first(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> SearchResult | None:
        """Find the first matching text in this scope and its descendants."""
        results = self._find_text(
            search, case_sensitive, first=True, regex=regex
        )
        return results[0] if results else None

    def find_all(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> list[SearchResult]:
        """Find all matching text in this scope and its descendants."""
        return self._find_text(
            search, case_sensitive, first=False, regex=regex
        )

    @property
    def text(self):
        """Return the plain text of this section without nested sections."""
        return ''.join([par.text for par in self.paragraphs])

    @property
    def markdown(self):
        """Return the Markdown of this section without nested sections."""
        return ''.join([par.markdown for par in self.paragraphs])

    def subtree_markdown(self) -> str:
        """Render this section and its descendants as Markdown."""
        return ''.join(
            [
                self.markdown,
                *[child.subtree_markdown() for child in self.sections],
            ]
        )

    def subtree_text(self) -> str:
        """Render this section and its descendants as plain text."""
        return ''.join(
            [self.text, *[child.subtree_text() for child in self.sections]]
        )



class DocumentBase(BaseModel):
    """Store document identity and revision metadata."""

    title: Annotated[str, Field(description='Document title')]
    revision_id: Annotated[
        str | None, Field(description='Document revision id'),
    ]
    document_id: Annotated[str, Field(description='Document id')]
    tab_id: str | None = None
    tab_title: str | None = None



class TabInfo(BaseModel):
    """Expose a flat tab hierarchy suitable for explicit agent selection."""

    tab_id: str
    title: str
    parent_tab_id: str | None
    depth: int
    index: int



class DocumentOutline(DocumentBase):
    """Document outline"""

    sections: Sequence[DocumentOutlineItem] = []
    tabs: list[TabInfo] = Field(default_factory=list)
    suggestions: SuggestionNotice = Field(default_factory=SuggestionNotice)



class DocumentTree(DocumentBase):
    """Represent nested sections with a heading ID lookup."""

    sections: Sequence[DocumentSection] = []
    headings: Annotated[dict[str, DocumentSection], Field(exclude=True)]

    def descendants(self) -> Generator[DocumentSection, None, None]:
        """Yield nested sections in document order."""
        for child in self.sections:
            yield child
            yield from child.descendants()

    def _find_text(
        self,
        search: str,
        case_sensitive: bool = True,
        first: bool = False,
        regex: bool = False,
    ) -> list[SearchResult]:
        results = []
        for child in self.sections:
            found = child._find_text(
                search, case_sensitive, first, regex=regex
            )
            results.extend(found)
            if first and len(found) > 0:
                return found
        return results

    def find_first(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> SearchResult | None:
        """Find the first matching text in this scope and its descendants."""
        results = self._find_text(
            search, case_sensitive, first=True, regex=regex
        )
        return results[0] if results else None

    def find_all(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> list[SearchResult]:
        """Find all matching text in this scope and its descendants."""
        return self._find_text(
            search, case_sensitive, first=False, regex=regex
        )

    def tree_markdown(self) -> str:
        """Render all document sections as Markdown."""
        return ''.join([child.subtree_markdown() for child in self.sections])

    def tree_text(self) -> str:
        """Render all document sections as plain text."""
        return ''.join([child.subtree_text() for child in self.sections])



class DocumentReadSection(BaseModel):
    """Identify a returned subtree or the document preamble."""

    heading_id: str | None = Field(
        description='Root heading ID, or null for content before any heading.',
    )
    markdown: str = Field(
        description='Markdown including nested subsections and heading ID '
        'anchors; preamble content contains no heading root.',
    )



class DocumentSubset(DocumentBase):
    """Return identified document sections and selection diagnostics."""

    sections: list[DocumentReadSection] = Field(
        description='Non-overlapping section subtrees in document order. '
        'Whole-tab reads include a preamble entry with heading_id=null.',
    )
    suggestions: SuggestionNotice = Field(default_factory=SuggestionNotice)
    tab_count: int = Field(
        default=0, ge=0, description='Total root and nested tabs in the '
        'document, including the selected tab. One means the only tab; '
        'zero means tab metadata is unavailable in a legacy response. '
        'Call docs_get_tree for the complete tab inventory.',
    )
    unknown_heading_ids: list[str] = Field(
        default_factory=list,
        description='Unresolved requested IDs, deduplicated in request order.',
    )
    selected_headings: Annotated[
        Sequence[str] | None,
        Field(
            description='Effective root heading IDs in document order, with '
            'duplicates and selected descendants removed; null for a '
            'whole-tab read, [] for an empty selection.'
        ),
    ]
    partial: Annotated[
        bool,
        Field(
            description='Whether heading selection was requested within '
            'the selected tab. False means the whole selected tab, '
            'not all document tabs. See tab_count for other tabs.'
        ),
    ] = False

