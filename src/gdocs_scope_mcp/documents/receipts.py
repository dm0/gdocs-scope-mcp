"""Models owned by documents.receipts."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from gdocs_scope_mcp.contracts import (
    APPEND_PREVIEW_LIMIT,
    RECEIPT_ITEM_LIMIT,
    DocumentEditReceipt,
    TruncatedStr80,
    TruncatedStr200,
)


class InsertSucceedResponse(DocumentEditReceipt):
    """Result of successful text insertion request"""

    ok: Literal[True] = True
    inserted_entity_count: int = Field(
        default=0, ge=0, description='Number of native smart chips inserted',
    )
    anchor: Annotated[
        TruncatedStr80,
        Field(
            description=(
                'A paragraph used as the anchor; the first 80 characters max'
            )
        ),
    ]
    insert_position: Annotated[
        Literal['before', 'after'],
        Field(description='Insert position relative to the anchor paragraph'),
    ]
    at_index: Annotated[
        int,
        Field(
            description='Google Docs API insertion index; diagnostic only'
        ),
    ]
    rich: bool
    temporary_image_cleanup_pending: Annotated[
        list[str], Field(description='Temporary Drive file IDs that could not '
                         'be deleted; insertion succeeded, do not repeat it. '
                         'Remove these files manually.')
    ] = Field(default_factory=list)
    inserted_image_count: Annotated[
        int, Field(ge=0, description='Number of native inline images inserted')
    ] = 0
    inserted_text: Annotated[
        TruncatedStr200,
        Field(description='Inserted text preview; U+FFFC represents each '
              'native image or smart chip; the first 200 characters max'),
    ]
    inserted_char_count: Annotated[
        int, Field(ge=0, description='Full inserted Unicode code-point count, '
                   'including paragraph breaks and one U+FFFC placeholder '
                   'per native image or smart chip')
    ]
    preview_truncated: bool
    anchor_char_count: Annotated[
        int, Field(ge=0, description='Full rendered anchor paragraph length '
                   'in Unicode code points')
    ]
    anchor_preview_truncated: bool


class AppendSucceedResponse(DocumentEditReceipt):
    """Describe appended content without exposing Google API requests."""

    ok: Literal[True] = True
    inserted_entity_count: int = Field(
        default=0, ge=0, description='Number of native smart chips inserted',
    )
    temporary_image_cleanup_pending: Annotated[
        list[str], Field(description='Temporary Drive file IDs that could not '
                         'be deleted; insertion succeeded, do not repeat it. '
                         'Remove these files manually.')
    ] = Field(default_factory=list)
    inserted_image_count: Annotated[
        int, Field(ge=0, description='Number of native inline images inserted')
    ] = 0
    scope: Literal['document_end'] = 'document_end'
    rich: Annotated[
        bool, Field(description='Whether the input was parsed as Markdown')
    ]
    at_index: Annotated[
        int,
        Field(
            ge=1,
            description='Google Docs API insertion index; diagnostic only',
        ),
    ]
    appended: Annotated[
        str,
        Field(
            max_length=APPEND_PREVIEW_LIMIT,
            description='Inserted plain-text preview, including paragraph '
            'breaks and U+FFFC for each native image or smart chip; '
            'at most 200 code points',
        ),
    ]
    inserted_char_count: Annotated[
        int,
        Field(
            ge=0,
            description='Full inserted length in Unicode code points, '
            'including paragraph breaks and one U+FFFC per image or '
            'smart chip',
        ),
    ]
    preview_truncated: Annotated[
        bool,
        Field(description='Whether appended omits text after the preview'),
    ]


class ReplaceSucceedResponse(DocumentEditReceipt):
    """Result of successful text replacement request"""

    ok: Literal[True] = True
    replaced: Annotated[
        TruncatedStr80,
        Field(description='Replaced text; the first 80 characters max'),
    ]
    at_index: Annotated[
        int | None,
        Field(
            description='Google Docs API replacement index; diagnostic only'
        ),
    ] = None
    occurrences_found: Annotated[
        int | None,
        Field(description='Complete pre-edit match count in the effective '
              'scope for targeted replacement, including occurrence=1. '
              'Targeted search is case-insensitive; null for native '
              'replace-all.'),
    ] = None
    occurrences_changed: Annotated[
        int | None,
        Field(description='Native literal replace-all changed count; '
              'case-sensitive, not a pre-edit match count'),
    ] = None
    occurrences_found_complete: bool = Field(
        default=False,
        description='True for every targeted replacement, whose match count '
        'covers the entire effective scope; false for native replace-all, '
        'which returns a changed count rather than a pre-edit match count.',
    )
    applied: Annotated[
        int, Field(ge=0, description='Number of replacements applied; '
                   'distinct from the pre-edit match count')
    ]
    replaced_char_count: Annotated[
        int, Field(ge=0, description='Full Unicode code-point length of '
                   'replaced, or the search string for native replace-all')
    ]
    preview_truncated: bool


class DeleteParagraphResponse(DocumentEditReceipt):
    """Report deleted paragraphs using bounded text previews."""

    ok: Literal[True] = True
    deleted_count: Annotated[
        int,
        Field(
            description='Number of paragraphs removed or cleared, excluding '
            'an already-empty final Body paragraph',
        ),
    ]
    deleted: Annotated[
        list[TruncatedStr80],
        Field(
            max_length=RECEIPT_ITEM_LIMIT,
            description='Deleted paragraph previews, up to 80 '
            'characters each, in reverse document order'
        ),
    ]
    deleted_char_counts: Annotated[
        list[int], Field(max_length=RECEIPT_ITEM_LIMIT,
                         description='Full paragraph Unicode code-point '
                         'lengths, aligned with the returned deleted previews')
    ]
    deleted_preview_truncated: Annotated[
        list[bool], Field(max_length=RECEIPT_ITEM_LIMIT)
    ]
    deleted_truncated: Annotated[
        bool, Field(description='Whether deleted omits paragraphs after '
                    'the first 100 previews; deleted_count remains the total')
    ]


class BatchReplaceChange(BaseModel):
    """Describe one replacement while preserving the existing with field."""

    model_config = ConfigDict(serialize_by_alias=True)

    replaced: TruncatedStr80
    replacement: Annotated[TruncatedStr200, Field(alias='with')]
    at_index: Annotated[int, Field(description='Google Docs API index; '
                                 'diagnostic only')]
    replaced_char_count: Annotated[
        int, Field(ge=0, description='Full replaced Unicode code-point count')
    ]
    replacement_char_count: Annotated[
        int, Field(ge=0,
                   description='Full replacement Unicode code-point count')
    ]
    preview_truncated: bool
    replacement_preview_truncated: bool


class BatchReplaceResponse(DocumentEditReceipt):
    """Report the changes applied by one replacement batch."""

    ok: Literal[True] = True
    applied: int
    changes: Annotated[
        list[BatchReplaceChange],
        Field(max_length=RECEIPT_ITEM_LIMIT,
              description='First 100 applied changes in document order'),
    ]
    changes_truncated: Annotated[
        bool, Field(description='Whether changes omits entries after the '
                    'first 100 previews; applied remains the total')
    ]
