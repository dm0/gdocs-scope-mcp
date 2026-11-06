"""Static, opt-in Study 1 adapters over the unchanged baseline tools."""

from inspect import getdoc
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from gdocs_scope_mcp.comment_models import (
    ReopenCommentResponse,
    ResolveCommentResponse,
)
from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.receipts import (
    AppendSucceedResponse,
    InsertSucceedResponse,
)
from gdocs_scope_mcp.documents.tabs import TabId
from gdocs_scope_mcp.tool_inputs import (
    CodeBlockStyle,
    CodeBlockThemeBackground,
    CommentActionText,
    ExpectedRevision,
    NonemptyText,
    TableBorders,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema

WRITE_ANNOTATIONS = {
    'readOnlyHint': False, 'destructiveHint': False,
    'idempotentHint': False, 'openWorldHint': True,
}


class AppendTarget(BaseModel):
    """Select the current end of the selected tab, without anchor fields."""

    model_config = ConfigDict(extra='forbid')
    position: Literal['append']


class AnchorTarget(BaseModel):
    """Select a unique paragraph anchor with optional heading scope."""

    model_config = ConfigDict(extra='forbid')
    position: Literal['before', 'after']
    anchor: NonemptyText
    heading_id: str | None = None


InsertionTarget = Annotated[
    AppendTarget | AnchorTarget, Field(discriminator='position'),
]


def register_insertion(mcp, append, before, after):
    """Replace only the three insertion tools before exposing the catalog."""
    tools = {'append': append, 'before': before, 'after': after}
    description = (
        'Insert paragraphs using a typed target. '
        'target={"position":"append"} selects the selected tab end; '
        'target={"position":"before" or "after","anchor":"unique text",'
        '"heading_id": optional heading ID} selects a paragraph. '
        'Append forbids anchor and heading_id. Heading subtree boundaries '
        'use docs_insert_at_heading instead.\n\n'
        + '\n\n'.join(f'{position.upper()} semantics:\n{getdoc(tool)}'
                       for position, tool in tools.items())
    )
    for tool in tools.values():
        getattr(mcp, 'local_provider', mcp).remove_tool(tool.__name__)

    @mcp.tool(
        description=description,
        output_schema=tool_response_schema(
            AppendSucceedResponse | InsertSucceedResponse,
        ),
        annotations=WRITE_ANNOTATIONS,
    )
    def docs_insert(
        doc_id: str, text: str, target: InsertionTarget, rich: bool = True, *,
        tab_id: TabId | None = None,
        upload_local_images: bool = False, table_borders: TableBorders = True,
        code_block_style: CodeBlockStyle | None = None,
        code_block_theme_background: CodeBlockThemeBackground | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> AppendSucceedResponse | InsertSucceedResponse | EditFailedResponse:
        """Delegate to the baseline adapter without changing its receipt."""
        kwargs = {
            'rich': rich, 'tab_id': tab_id,
            'upload_local_images': upload_local_images,
            'table_borders': table_borders,
            'code_block_style': code_block_style,
            'code_block_theme_background': code_block_theme_background,
            'expected_revision_id': expected_revision_id,
        }
        if isinstance(target, AnchorTarget):
            kwargs.update(anchor=target.anchor, heading_id=target.heading_id)
        return tools[target.position](doc_id=doc_id, text=text, **kwargs)


def register_status(mcp, resolve, reopen):
    """Replace resolve/reopen without combining destructive comment actions."""
    tools = {'resolve': resolve, 'reopen': reopen}
    description = (
        'Change a native comment thread status. action is resolve or reopen; '
        'optional reply belongs to the same action post.\n\n'
        + '\n\n'.join(f'{action.upper()} semantics:\n{getdoc(tool)}'
                       for action, tool in tools.items())
    )
    for tool in tools.values():
        getattr(mcp, 'local_provider', mcp).remove_tool(tool.__name__)

    @mcp.tool(
        description=description,
        output_schema=tool_response_schema(
            ResolveCommentResponse | ReopenCommentResponse,
        ),
        annotations=WRITE_ANNOTATIONS,
    )
    def docs_comment_status(
        doc_id: str, comment_id: NonemptyText,
        action: Literal['resolve', 'reopen'], reply: CommentActionText = '', *,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> ResolveCommentResponse | ReopenCommentResponse | EditFailedResponse:
        """Use the same action post, revision policy and persistence checks."""
        return tools[action](
            doc_id, comment_id, reply,
            expected_revision_id=expected_revision_id,
        )


def variant_instructions(instructions: str, variant: str) -> str:
    """Use active names in instructions; preserve the baseline verbatim."""
    if variant in {'insertion', 'both'}:
        for name in ('docs_insert_after', 'docs_insert_before', 'docs_append'):
            instructions = instructions.replace(name, 'docs_insert')
        instructions = instructions.replace('All four rich insertion tools',
                                            'Rich insertion tools')
    if variant in {'status', 'both'}:
        for name in ('docs_resolve_comment', 'docs_reopen_comment'):
            instructions = instructions.replace(name, 'docs_comment_status')
    return instructions
