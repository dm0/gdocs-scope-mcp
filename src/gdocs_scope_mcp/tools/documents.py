"""Thin MCP adapters for documents."""

# Preserve the exact public descriptions after nesting registration functions.
# ruff: noqa: E501

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents import (
    editing as docs_edit,
    reading,
)
from gdocs_scope_mcp.documents.models import DocumentOutline, DocumentSubset
from gdocs_scope_mcp.documents.receipts import (
    AppendSucceedResponse,
    BatchReplaceResponse,
    DeleteParagraphResponse,
    InsertSucceedResponse,
    ReplaceSucceedResponse,
)
from gdocs_scope_mcp.documents.tabs import TabId, TabsResponse
from gdocs_scope_mcp.settings import code_formatting
from gdocs_scope_mcp.tool_inputs import (
    CodeBlockStyle,
    CodeBlockThemeBackground,
    ExpectedRevision,
    NonemptyText,
    ReplacementOccurrence,
    Replacements,
    TableBorders,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema


def register_discovery(mcp):
    """Register documents tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(DocumentOutline),
        annotations={
            'readOnlyHint': True,
            'destructiveHint': False,
            'idempotentHint': True,
            'openWorldHint': True,
        },
    )
    def docs_get_tree(doc_id: str, *,
                      tab_id: TabId | None = None) -> DocumentOutline:
        """
        Fetch a Google Doc's structural outline as a JSON object.

        Headings describe accepted content without pending suggestions applied.
        suggestions metadata reports pending changes in the document/selected
        tab, with null for unavailable detection. Read details separately with
        docs_suggestions_read; this tool accepts or rejects no changes.

        The object contains document_id, title, revision_id, and a flat sections
        collection. Each section has id, title, level, and ancestor_ids. Hierarchy
        is represented by ancestor_ids, not nested section objects. Body
        paragraphs are omitted.

        tab_id selects a root or nested tab; omitted selects the first tab.
        Discover IDs with docs_tabs_list. Heading IDs are local to that tab.
        The tabs array lists ALL root and nested tabs with tab_id, title,
        parent_tab_id, depth and sibling index, including the selected tab.
        A single entry means this is the document's only tab. The inventory and
        selected outline come from the same read; sections belong only to tab_id.

        Use this tool FIRST when encountering a document to locate target sections
        via their heading IDs, avoiding the need to read a massive document all at
        once.
        With one tab, continue without tab_id or another discovery call. With
        several tabs, reuse these headings for the first tab, or call this tool
        with another tab_id to obtain that tab's headings before editing it.

        Args:
            doc_id: Google Doc ID (from the URL: /document/d/{DOC_ID}/edit)
        """
        return reading.get_tree(doc_id, tab_id=tab_id)


    @mcp.tool(
        output_schema=tool_response_schema(TabsResponse),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': True},
    )
    def docs_tabs_list(doc_id: str) -> TabsResponse:
        """List root and nested tabs with IDs, titles, parents and order.

        Pass tab_id to document read/edit, table and entity tools. Omitted tab_id
        means the first document tab. Explicit missing IDs never fall back.
        Tab discovery is read-only; revision IDs remain document-wide.
        """
        return reading.tabs_list(doc_id)

def register_reading(mcp):
    """Register documents tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(DocumentSubset),
        annotations={
            'readOnlyHint': True,
            'destructiveHint': False,
            'idempotentHint': True,
            'openWorldHint': True,
        },
    )
    def docs_read(
        doc_id: str, heading_ids: list[str] | None = None, *,
        tab_id: TabId | None = None,
    ) -> DocumentSubset | EditFailedResponse:
        """
        Read the selected Google document tab's content converted to Markdown.

        Return accepted content: hide proposed insertions, retain proposed
        deletions, and omit suggested formatting. suggestions identifies the
        view, pending changes in the document and returned scope, relevant IDs
        and detection warnings. A null pending flag means unknown, not absent.
        Use docs_suggestions_read for proposals rather than interpreting this
        Markdown as a diff. No suggestions are accepted or rejected by reading.

        Native people, resource, date and dropdown chips remain identifiable HTML
        spans with data-mcp-entity and data-mcp-id, rather than ordinary labels or
        links. Pass a span to a rich insertion tool to create a native instance.
        Use docs_get_entity for complete properties, source ranges and dropdown
        options. tab_id selects a root or nested tab; omit for the first tab.
        Discover IDs with docs_tabs_list; returned tab_id identifies this view.

        Contiguous native lists use nested HTML ol/ul/li elements to preserve
        marker kind, nesting and adjacent independent groups in rich reinsertion.
        Unmarked paragraphs end list groups; continuation membership, custom
        numbering and original native list IDs are not reconstructed losslessly.

        Table HTML includes data-mcp-table-ref when its native position can be
        validated, including nested tables. Unsafe refs are omitted with an
        explicit suggestions.warnings entry. Pass a
        reference to docs_table_read for bounded structured cells and A1 addresses.
        Refs describe checked section positions, not persistent object identity:
        heading ID hierarchy + table ordinal + section table structure inventory.
        Text/style changes preserve refs; structural changes require fresh refs.
        Swapping structurally identical tables preserves position meaning.
        Snapshot checks compare selected cells/fields, allowing independent edits.
        Reads/snapshots create no bindings or files and write no metadata.

        You can read the entire selected tab, or isolate sections by passing
        a list of target heading_ids, including their nested subsections.
        Isolating sections reduces token usage on large files.

        Args:
            doc_id: Google Doc ID from the URL.
            heading_ids: Optional list of heading IDs to fetch.
                Pass null or omit this field to read the whole selected tab.
                An empty list returns no sections. Duplicate IDs and selected
                descendants of selected ancestors are collapsed in document order.

        Returns
        -------
            Document metadata and sections [{heading_id, markdown}], effective
            selected_headings, unknown_heading_ids, partial and tab_count. The
            tab_count includes root and nested tabs; one means the only tab.
            partial=false means the whole selected tab, not all document tabs.
            Call docs_get_tree to choose among other tabs. Whole-tab reads
            include the preamble with heading_id=null. Mixed selections return
            valid content and diagnostics; all-unknown selections fail with
            HEADING_NOT_FOUND. Refresh IDs with docs_get_tree after that error.
            Code reads use configured inline font/color matching, validated block
            markers, and a configurable block-formatting heuristic enabled by
            default. Recognized code omits visual style wrappers and preserves
            literal block whitespace. Only marked blocks retain a language;
            formatting heuristics never guess it. Reading does not create markers.
        """
        if isinstance(heading_ids, str):
            heading_ids = [heading_ids]
        return reading.read(doc_id, heading_ids, tab_id=tab_id)

def register_editing(mcp):
    """Register documents tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(ReplaceSucceedResponse),
        annotations={
            'readOnlyHint': False,
            'destructiveHint': True,
            'idempotentHint': False,
            'openWorldHint': True,
        },
    )
    # Preserve the public positional calling convention.
    def docs_search_replace(  # noqa: PLR0917
        doc_id: str,
        find: NonemptyText,
        replace: str,
        occurrence: ReplacementOccurrence = 1,
        heading_id: str | None = None,
        regex: bool = False,
        *, tab_id: TabId | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> ReplaceSucceedResponse | EditFailedResponse:
        """
        Find text and replace.

        Uses configured write_revision_mode: required validates targets with up to
        three attempts; target delegates concurrent/overlapping edits to Google.
        expected_revision_id forces a strict required revision without retries.
        Unknown writes and rejected target revisions are not replayed.

        Preserves history using batchUpdate.
        Replace-all (occurrence=0) is only supported if regex=False and heading_id
        is None.

        Args:
            doc_id:     Google Doc ID
            find:       Text to search for (or regex pattern if regex=True)
            replace:    Text to replace it with
            occurrence: Occurrence number to replace, 1-based (default 1 = first).
                        Use 2 for the second, etc. Use 0 to replace ALL
                        occurrences. Replace all is only supported in non regular
                        expression mode (regex=False) and heading_id is None.
            heading_id: Restrict search and replacement to this heading and its
                        subheadings. Use docs_get_tree to find heading IDs.
            regex:      If True, treat `find` as a Python regular expression

        Returns
        -------
            A structured object with ok, replaced (up to 80 characters), at_index,
            occurrences_found, and occurrences_changed. Targeted replacements
            populate at_index and occurrences_found; replace-all populates
            occurrences_changed. Unused index/count fields are null.
            Includes document_id, scope, heading_id, applied (changes),
            replaced_char_count (Unicode code points), and preview_truncated.
            occurrences_found_complete is True for every targeted replacement;
            occurrences_found counts all pre-edit matches in the effective scope,
            while applied=1, including when replace is empty (deletion).
            Native replace-all has occurrences_found=null and completeness=False;
            replaced previews the search string.
            Targeted matching is case-insensitive; native literal replace-all
            is case-sensitive. at_index is diagnostic only.
        """
        return docs_edit.search_replace(
            doc_id, find, replace, occurrence, heading_id, regex,
            expected_revision_id=expected_revision_id, tab_id=tab_id,
        )


    @mcp.tool(
        output_schema=tool_response_schema(InsertSucceedResponse),
        annotations={
            'readOnlyHint': False,
            'destructiveHint': False,
            'idempotentHint': False,
            'openWorldHint': True,
        },
    )
    def docs_insert_after(
        doc_id: str,
        anchor: NonemptyText,
        text: str,
        heading_id: str | None = None,
        rich: bool = True,
        *, tab_id: TabId | None = None,
        upload_local_images: bool = False, table_borders: TableBorders = True,
        code_block_style: CodeBlockStyle | None = None,
        code_block_theme_background: CodeBlockThemeBackground | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> InsertSucceedResponse | EditFailedResponse:
        """
        Insert a new paragraph immediately after the paragraph containing `anchor`.

        Configured required mode validates an unchanged, unique anchor with up to
        three attempts; target lets Google merge overlapping changes without local
        conflict checks or retries. expected_revision_id forces strict required.
        Table stages always use required; completed stages/unknown writes are not
        replayed. Inspect partial results.

        The anchor is matched case-insensitively as a substring of the paragraph.

        The search can be scoped to the specified heading and nested subheadings.

        Rich formatting is ON by default. Set rich=False to insert literal text.

        Converts Markdown paragraphs and # / ## / ### / ... headings, with
        **bold**, *italic*, and ***bold italic*** inline styles. Heading mapping:
        # is TITLE, ## is SUBTITLE, ### is HEADING_1, and so on. Native lists with
        homogeneous or mixed nesting, rectangular Markdown/HTML tables and images
        are supported. Tables preserve inline formatting, br line breaks and
        column alignment;
        merged/nested tables and block content in cells are unsupported. Tables
        use multiple revision-guarded batches; failures may leave partial content.
        Read before retrying. Images require public HTTP(S) PNG/JPEG/GIF URLs;
        alt/title metadata is not preserved. HTML width/height accept pixel
        numbers. Without dimensions, images fit paragraph content width in
        single-column paged body paragraphs/lists. Explicit sizes take precedence;
        cells and unsupported/unresolved layouts retain Google's default sizing.
        Inline code and blocks default to Roboto Mono, with inline color #188038;
        font/color are configurable on the server. Blocks preserve literal
        whitespace. Declared languages use Pygments (theme default); highlighting
        is configurable on the server. Unknown/absent languages stay plain.
        HTML code/pre are supported; blocks inside list items are unsupported.

        Args:
            doc_id: Google Doc ID
            anchor: A unique, distinctive string of text within the target
                paragraph. Choose a longer phrase to avoid accidental matches.
            text:   Text to insert as the new paragraph
            heading_id: Narrow down search to this heading and subheadings
            rich:   If True (default), convert Markdown using the shared converter
            upload_local_images: Allow absolute local image paths/file URLs.
                Uploads to My Drive root, temporarily grants anyone-with-link
                read access, inserts, then deletes sources. Defaults to False.
                Ignored with rich=False. See temporary_image_cleanup_pending.
            table_borders: Show borders on new tables (default True).
                False hides outer and internal borders. Ignored with rich=False.
            code_block_style: Pygments theme, e.g. default or monokai.
                Omitted/null inherits config/environment. Ignored with rich=False.
            code_block_theme_background: Apply paragraph theme background.
                Omitted/null inherits server config/environment; False disables it.
                Ignored with rich=False.

        Returns
        -------
            A receipt with document_id, scope, heading_id, ok, anchor,
            insert_position, diagnostic at_index, rich, and inserted_text.
            inserted_text is a preview of up to 200 Unicode code points;
            inserted_image_count counts native images; previews use U+FFFC per
            image. inserted_char_count includes placeholders and paragraph breaks;
            preview_truncated signals omitted text. The anchor preview is at most
            80 code points, with anchor_char_count and anchor_preview_truncated.
        """
        with code_formatting(style=code_block_style,
                             theme_background=code_block_theme_background):
            return docs_edit.insert_after(
                doc_id, anchor, text, heading_id=heading_id, rich=rich,
                upload_local_images=upload_local_images,
                table_borders=table_borders,
                expected_revision_id=expected_revision_id, tab_id=tab_id,
            )


    @mcp.tool(
        output_schema=tool_response_schema(InsertSucceedResponse),
        annotations={
            'readOnlyHint': False,
            'destructiveHint': False,
            'idempotentHint': False,
            'openWorldHint': True,
        },
    )
    def docs_insert_before(
        doc_id: str,
        anchor: NonemptyText,
        text: str,
        heading_id: str | None = None,
        rich: bool = True,
        *, tab_id: TabId | None = None,
        upload_local_images: bool = False, table_borders: TableBorders = True,
        code_block_style: CodeBlockStyle | None = None,
        code_block_theme_background: CodeBlockThemeBackground | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> InsertSucceedResponse | EditFailedResponse:
        """
        Insert a new paragraph immediately before the paragraph containing

        `anchor`.

        Configured required mode validates an unchanged, unique anchor with up to
        three attempts; target lets Google merge overlapping changes without local
        conflict checks or retries. expected_revision_id forces strict required.
        Table stages always use required; completed stages/unknown writes are not
        replayed. Inspect partial results.

        The anchor is matched case-insensitively as a substring of the paragraph.

        The search can be scoped to the specified heading and nested subheadings.

        Rich formatting is ON by default. Set rich=False to insert literal text.

        Converts Markdown paragraphs and # / ## / ### / ... headings, with
        **bold**, *italic*, and ***bold italic*** inline styles. Heading mapping:
        # is TITLE, ## is SUBTITLE, ### is HEADING_1, and so on. Native lists with
        homogeneous or mixed nesting, rectangular Markdown/HTML tables and images
        are supported. Tables preserve inline formatting, br line breaks and
        column alignment;
        merged/nested tables and block content in cells are unsupported. Tables
        use multiple revision-guarded batches; failures may leave partial content.
        Read before retrying. Images require public HTTP(S) PNG/JPEG/GIF URLs;
        alt/title metadata is not preserved. HTML width/height accept pixel
        numbers. Without dimensions, images fit paragraph content width in
        single-column paged body paragraphs/lists. Explicit sizes take precedence;
        cells and unsupported/unresolved layouts retain Google's default sizing.
        Inline code and blocks default to Roboto Mono, with inline color #188038;
        font/color are configurable on the server. Blocks preserve literal
        whitespace. Declared languages use Pygments (theme default); highlighting
        is configurable on the server. Unknown/absent languages stay plain.
        HTML code/pre are supported; blocks inside list items are unsupported.

        Args:
            doc_id: Google Doc ID
            anchor: Text to search for to find the target paragraph
            text:   Text to insert as the new paragraph
            heading_id: Narrow down search to this heading and subheadings
            rich:   If True (default), convert Markdown using the shared converter
            upload_local_images: Allow absolute local image paths/file URLs.
                Uploads to My Drive root, temporarily grants anyone-with-link
                read access, inserts, then deletes sources. Defaults to False.
                Ignored with rich=False. See temporary_image_cleanup_pending.
            table_borders: Show borders on new tables (default True).
                False hides outer and internal borders. Ignored with rich=False.
            code_block_style: Pygments theme, e.g. default or monokai.
                Omitted/null inherits config/environment. Ignored with rich=False.
            code_block_theme_background: Apply paragraph theme background.
                Omitted/null inherits server config/environment; False disables it.
                Ignored with rich=False.

        Returns
        -------
            A receipt with document_id, scope, heading_id, ok, anchor,
            insert_position, diagnostic at_index, rich, and inserted_text.
            inserted_text is a preview of up to 200 Unicode code points;
            inserted_image_count counts native images; previews use U+FFFC per
            image. inserted_char_count includes placeholders and paragraph breaks;
            preview_truncated signals omitted text. The anchor preview is at most
            80 code points, with anchor_char_count and anchor_preview_truncated.
        """
        with code_formatting(style=code_block_style,
                             theme_background=code_block_theme_background):
            return docs_edit.insert_before(
                doc_id, anchor, text, heading_id=heading_id, rich=rich,
                upload_local_images=upload_local_images,
                table_borders=table_borders,
                expected_revision_id=expected_revision_id, tab_id=tab_id,
            )


    @mcp.tool(
        output_schema=tool_response_schema(DeleteParagraphResponse),
        annotations={
            'readOnlyHint': False,
            'destructiveHint': True,
            'idempotentHint': True,
            'openWorldHint': True,
        },
    )
    def docs_delete_paragraph(
        doc_id: str, anchor: NonemptyText,
        *, tab_id: TabId | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> DeleteParagraphResponse:
        """
        Delete the paragraph(s) containing `anchor` text.

        Configured required mode validates original targets/styles with up to three
        attempts. Target lets Google merge overlapping changes without local
        conflict checks or retries. expected_revision_id forces strict required.
        Unknown writes and rejected target revisions are not replayed.

        Deletes ALL paragraphs that contain the anchor string (case-insensitive).
        If the anchor matches only one paragraph, only that paragraph is deleted.
        The required final Body newline remains as an empty paragraph. Clearing
        final paragraph content counts as one deletion; an already-empty final
        paragraph is skipped and is not counted.

        Args:
            doc_id: Google Doc ID
            anchor: Text to search for in paragraphs to delete

        Returns
        -------
            A structured object with ok, deleted_count, and deleted (paragraph
            previews up to 80 characters each, in reverse document order).
            Includes document_id, scope, and heading_id. At most 100 previews are
            returned, with aligned deleted_char_counts (full display-text Unicode
            code-point lengths excluding trailing newlines) and
            deleted_preview_truncated flags. deleted_truncated signals omitted
            previews; deleted_count includes all removed/cleared paragraphs.
        """
        return DeleteParagraphResponse.model_validate(
            docs_edit.delete_paragraph(
                doc_id, anchor, expected_revision_id=expected_revision_id,
                tab_id=tab_id,
            ),
        )


    @mcp.tool(
        output_schema=tool_response_schema(AppendSucceedResponse),
        annotations={
            'readOnlyHint': False,
            'destructiveHint': False,
            'idempotentHint': False,
            'openWorldHint': True,
        },
    )
    def docs_append(
        doc_id: str, text: str, rich: bool = True, *,
        tab_id: TabId | None = None,
        upload_local_images: bool = False,
        table_borders: TableBorders = True,
        code_block_style: CodeBlockStyle | None = None,
        code_block_theme_background: CodeBlockThemeBackground | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> AppendSucceedResponse:
        """
        Append Markdown paragraphs or literal text at the end of a Google Doc.

        Configured required mode replans at the current end (up to three attempts).
        Target lets Google merge concurrent appends and choose their order, without
        local retries. expected_revision_id forces strict required without retries.
        Table stages always use required; completed stages and unknown writes are
        not replayed. Inspect partial failures.

        A paragraph break is added before the appended content automatically.
        With rich=True, separate Markdown paragraphs with blank lines. Headings
        map as follows: # is TITLE, ## is SUBTITLE, ### is HEADING_1, and so on.
        Bold, italic, combined emphasis and native lists with homogeneous or mixed
        nesting are supported.
        Markdown images and HTML img[src] create native images from public HTTP(S)
        PNG/JPEG/GIF URLs. HTML width/height accept pixel numbers; alt/title
        metadata is not preserved. CSS/responsive images are unsupported.
        Without dimensions, images fit paragraph content width in single-column
        paged body paragraphs/lists. Explicit sizes take precedence; cells and
        unsupported/unresolved layouts retain Google's default sizing.
        Rectangular Markdown/HTML tables preserve inline formatting, br breaks,
        empty cells and column alignment. Merged/nested tables and block content
        are unsupported. Tables use multiple revision-guarded batches; failures may
        leave partial content. Read the document before retrying.

        Inline code and blocks default to Roboto Mono, with inline color #188038;
        font/color are configurable on the server. Blocks preserve literal
        whitespace. Declared languages use Pygments (theme default); highlighting
        is configurable on the server. Unknown/absent languages stay plain.
        HTML code/pre are supported; blocks inside list items are unsupported.

        With rich=False, preserve Markdown delimiters and line breaks literally.

        Args:
            doc_id: Google Doc ID
            text: Markdown or literal content to append, according to rich.
            rich: Parse Markdown if True (default); insert literal text if False.
            upload_local_images: Allow absolute local image paths/file URLs.
                Uploads to My Drive root, temporarily grants anyone-with-link
                read access, inserts, then deletes sources. Defaults to False.
                Ignored with rich=False. See temporary_image_cleanup_pending.
            table_borders: Show borders on new tables (default True).
                False hides outer and internal borders. Ignored with rich=False.
            code_block_style: Pygments theme, e.g. default or monokai.
                Omitted/null inherits config/environment. Ignored with rich=False.
            code_block_theme_background: Apply paragraph theme background.
                Omitted/null inherits server config/environment; False disables it.
                Ignored with rich=False.

        Returns
        -------
            A structured receipt with document_id, rich, diagnostic at_index,
            appended (plain-text preview up to 200 Unicode code points),
            inserted_image_count, inserted_char_count (including paragraph breaks
            and U+FFFC per native image), preview_truncated,
            and ok=True. Read the document to verify formatting.
            scope is document_end and heading_id is null.
        """
        with code_formatting(style=code_block_style,
                             theme_background=code_block_theme_background):
            return docs_edit.append(
                doc_id, text, rich=rich, upload_local_images=upload_local_images,
                table_borders=table_borders,
                expected_revision_id=expected_revision_id, tab_id=tab_id,
            )


    @mcp.tool(
        output_schema=tool_response_schema(BatchReplaceResponse),
        annotations={
            'readOnlyHint': False,
            'destructiveHint': True,
            'idempotentHint': False,
            'openWorldHint': True,
        },
    )
    def docs_batch_replace(
        doc_id: str, replacements: Replacements,
        *, tab_id: TabId | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> BatchReplaceResponse:
        """
        Apply multiple find→replace operations atomically in a single batchUpdate.

        Configured required mode validates original targets/styles with up to three
        attempts. Target delegates merging, including overlaps, to Google without
        local conflict checks or retries. expected_revision_id forces strict
        required. Unknown writes and rejected target revisions are not replayed.

        All replacements are applied in one API call (end-of-document first to
        preserve index validity). Either ALL changes succeed, or none do.

        Args:
            doc_id:           Google Doc ID
            replacements: Nonempty array of typed replacement objects, e.g.:
                              [{"find": "Q1", "replace": "Q2"},
                                {"find": "draft", "replace": "final", "occurrence":
                                0}]

                              Each item: {"find": str, "replace": str,
                                          "occurrence": int (default 1, 0=all),
                                          "regex": bool (default false)}
                              find must be nonempty; replace="" deletes text.
                              Types are strict; unknown fields, negative
                              occurrences and invalid regex patterns are rejected
                              before API access. occurrence=0 supports literal
                              and regex replace-all within this batch tool.

        Returns
        -------
            A structured object with ok, applied (count), and changes in document
            order. Each change has replaced, with (replacement text), and at_index.
            Includes document_id, scope, heading_id, and changes_truncated. Only
            the first 100 change previews are returned; applied counts all edits.
            Each change bounds replaced to 80 and with to 200 Unicode code points,
            with full replaced_char_count/replacement_char_count and
            preview_truncated/replacement_preview_truncated flags. Indices are
            diagnostic only.
        """
        return BatchReplaceResponse.model_validate(
            docs_edit.batch_replace(
                doc_id, [replacement.model_dump() for replacement in replacements],
                expected_revision_id=expected_revision_id, tab_id=tab_id,
            ),
        )
