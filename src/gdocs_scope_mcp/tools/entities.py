"""Thin MCP adapters for entities."""

# Preserve the exact public descriptions after nesting registration functions.
# ruff: noqa: E501

from gdocs_scope_mcp import entity_edit
from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.tabs import TabId
from gdocs_scope_mcp.entities import (
    DropdownOptions,
    EntityDetails,
    EntityEditResponse,
)
from gdocs_scope_mcp.tool_inputs import (
    NonemptyText,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema


def register(mcp):
    """Register entities tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(EntityDetails),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': True},
    )
    def docs_get_entity(
        doc_id: str, entity_id: NonemptyText, tab_id: TabId | None = None,
    ) -> EntityDetails | EditFailedResponse:
        """Inspect a native smart chip identified by docs_read's data-mcp-id.

        Returns kind, native ID, tab, revision, original UTF-16 source range,
        complete API metadata and the shared dropdown definition/options when
        applicable. Defaults to the first tab. Source indices are diagnostic;
        labels are not editable text runs. Reads do not modify the document.
        """
        return entity_edit.get_entity(doc_id, entity_id, tab_id)


    @mcp.tool(
        output_schema=tool_response_schema(EntityEditResponse),
        annotations={'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_create_dropdown_definition(
        doc_id: str, title: NonemptyText, options: DropdownOptions,
        tab_id: TabId | None = None,
    ) -> EntityEditResponse | EditFailedResponse:
        """Create a reusable native dropdown definition with 2-50 typed options.

        Options have display_value and optional #RRGGBB foreground_color and
        background_color. Returns dropdown_definition with definition/option IDs.
        Does not insert an instance or change existing definitions. Defaults to
        the first tab. Use the returned IDs in smart-chip HTML for the insertion
        tools. Writes are revision-guarded; inspect state after unknown outcomes
        before retrying, since creating another definition is not idempotent.
        """
        return entity_edit.create_dropdown_definition(
            doc_id, title, options, tab_id,
        )


    @mcp.tool(
        output_schema=tool_response_schema(EntityEditResponse),
        annotations={'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_select_dropdown(
        doc_id: str, entity_id: NonemptyText, option_id: NonemptyText,
        tab_id: TabId | None = None, expected_option_id: str | None = None,
    ) -> EntityEditResponse | EditFailedResponse:
        """Select an existing option on one native dropdown instance by ID.

        Does not change the shared definition or other instances. Obtain IDs
        from docs_read and docs_get_entity. expected_option_id optionally refuses
        an intervening selection change. Defaults to the first tab. Writes use
        the freshly read revision; concurrent changes fail without blind retries.
        Inspect state after ambiguous transport failures before retrying a write.
        """
        return entity_edit.select_dropdown(
            doc_id, entity_id, option_id, tab_id, expected_option_id,
        )

