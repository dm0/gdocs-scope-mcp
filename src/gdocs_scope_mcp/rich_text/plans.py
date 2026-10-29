"""Plan native tables and fill cells using indices read back from Google."""

# Deferred imports separate the paragraph converter and structural planner.
from copy import deepcopy
from dataclasses import dataclass

from gdocs_scope_mcp.rich_text.models import InsertionImage, InsertionTable
from gdocs_scope_mcp.rich_text.paragraph_requests import (
    compile_paragraphs as gpars_to_requests,
    paragraph_text as inserted_text_from_requests,
)


@dataclass
class TableInsertionPlan:
    """Store prevalidated blocks for a multi-batch native insertion."""

    blocks: list
    start: int
    newline_before: bool

    def paragraph_requests(self, paragraphs: list, start: int) -> list[dict]:
        """Rebase paragraph/run positions at the current native cursor."""

        paragraphs = deepcopy(paragraphs)
        cursor = start
        for paragraph in paragraphs:
            offset = cursor - paragraph.start_index
            paragraph.start_index += offset
            paragraph.end_index += offset
            for run in paragraph.elements:
                run.start_index += offset
                run.end_index += offset
            cursor += len(paragraph)
        return gpars_to_requests(
            paragraphs, newline_before=self.newline_before,
        )

    def request_groups(self):
        """Yield paragraph groups and tables without changing source order."""
        paragraphs = []
        for block in self.blocks:
            if isinstance(block, InsertionTable):
                if paragraphs:
                    yield paragraphs
                    paragraphs = []
                yield block
            elif len(block) or block.code_block:
                paragraphs.append(block)
        if paragraphs:
            yield paragraphs

    def iter_requests(self):
        """Expose prevalidated image requests to temporary-upload staging."""
        for block in self.blocks:
            if isinstance(block, InsertionTable):
                for row in block.cells:
                    for cell in row:
                        yield from cell.requests
            elif len(block) or block.code_block:
                yield from self.paragraph_requests([block], self.start)

    def replace_image_uri(self, old: str, new: str) -> None:
        """Replace staged sources in both table cells and body paragraphs."""

        for request in self.iter_requests():
            image = request.get('insertInlineImage')
            if image and image['uri'] == old:
                image['uri'] = new
        for block in self.blocks:
            if not isinstance(block, InsertionTable):
                for run in block.elements:
                    if isinstance(run, InsertionImage) and run.uri == old:
                        run.uri = new

    def text(self) -> str:
        """Render native paragraph text, excluding table structural indices."""

        text = ''
        for group in self.request_groups():
            if isinstance(group, InsertionTable):
                text += '\n' + ''.join(cell.text.replace('\u000b', '\n') + '\n'
                                      for row in group.cells for cell in row)
            else:
                text += inserted_text_from_requests(
                    self.paragraph_requests(group, self.start),
                )
        return text
