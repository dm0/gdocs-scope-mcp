"""Convert markdown (with HTML) into google requests"""


from rich.syntax import Syntax

from gdocs_scope_mcp.rich_text.models import (
    InsertionTable,
)
from gdocs_scope_mcp.rich_text.paragraph_requests import (
    compile_paragraphs,
    paragraph_text,
)
from gdocs_scope_mcp.rich_text.parsing import (
    html_to_gpars,
    markdown_to_html,
)
from gdocs_scope_mcp.rich_text.plans import TableInsertionPlan

# isort: split


def markdown_to_requests(
    markdown: str, start: int = 0, *, newline_before: bool = True
) -> list[dict] | TableInsertionPlan:
    """Convert Markdown with breaks suited to the insertion side."""
    html = markdown_to_html(markdown)
    gpars = html_to_gpars(html, start)
    return gpars_to_requests(gpars, newline_before=newline_before)


def gpars_to_requests(paragraphs, *, newline_before=True):
    """Compose pure paragraph requests or a pure structural insertion plan."""
    if any(isinstance(p, InsertionTable) for p in paragraphs):
        return TableInsertionPlan(
            blocks=paragraphs, start=paragraphs[0].start_index,
            newline_before=newline_before,
        )
    return compile_paragraphs(paragraphs, newline_before=newline_before)


def inserted_text_from_requests(requests):
    """Render planned text without performing network operations."""
    if isinstance(requests, TableInsertionPlan):
        return requests.text()
    return paragraph_text(requests)


if __name__ == '__main__':
    import argparse

    import rich

    console = rich.get_console()

    parser = argparse.ArgumentParser()
    parser.add_argument('md')

    args = parser.parse_args()

    console.print('HTML:')
    html = markdown_to_html(args.md)
    console.print(Syntax(html, 'html'))

    console.print('PARAGRAPHS:')
    gpars = html_to_gpars(html)
    for r in gpars:
        console.print(
            r.model_dump(
                mode='json',
                exclude_defaults=True,
                exclude_unset=True,
                by_alias=True,
            )
        )

    console.print('MD:')
    md = ''.join([r.to_markdown(None) for r in gpars])
    console.print(Syntax(md, 'md'))

    console.print('REQUESTS:')
    requests = gpars_to_requests(gpars)
    for r in requests:
        console.print(r)
