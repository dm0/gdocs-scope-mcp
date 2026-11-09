# Static tool consolidation

Status: adopted by user decision on 2026-11-09. The default is `both`.
See the [completion decision](../../research/tool_consolidation/DECISION.md)
for the accepted validation and unchanged statistical limitations.

Select `tool_interface_variant` in JSON configuration or set
`GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT` before starting a server:

| Variant | Insertion | Comment status |
| --- | --- | --- |
| `baseline` (A) | `docs_append`, `docs_insert_before`, `docs_insert_after` | `docs_resolve_comment`, `docs_reopen_comment` |
| `insertion` (B) | `docs_insert` | Separate baseline tools |
| `status` (C) | Separate baseline tools | `docs_comment_status` |
| `both` (D, default) | `docs_insert` | `docs_comment_status` |

All catalogs are complete and static for the server lifetime. Restart and
reconnect after changing the variant. This setting is independent of document
access mode. No dynamic discovery is introduced.

## Typed calls and migration

Insertion keeps all existing content, revision, tab, formatting and upload
options. Only the tool name and target arguments change:

```json
{"doc_id":"example","text":"Added paragraph","target":{"position":"append"}}
```

```json
{"doc_id":"example","text":"Added paragraph","target":{"position":"before","anchor":"Distinct paragraph","heading_id":"heading"},"rich":false}
```

Use `position: "after"` for after-paragraph insertion. `before` and `after`
require a nonempty anchor. Append forbids anchor and heading fields; unknown
target fields are rejected. Matching, including repeated-anchor behavior, is
the existing application's behavior. Heading-subtree insertion stays separate
as `docs_insert_at_heading` and is unchanged.

```json
{"doc_id":"example","comment_id":"native-thread","action":"resolve","reply":"Reviewed"}
```

Use `action: "reopen"` for reopening. Reply is optional and belongs to the
same native action post. This is an action interface, not a promise to skip
already-resolved/reopened threads: persistence and retries are unchanged.
Deletion, replies and comment editing remain separate tools with their existing
approval annotations.

Receipts retain their exact operation-specific shapes: append returns
`AppendSucceedResponse`, anchored insertion returns `InsertSucceedResponse`,
and comment actions retain their existing response models. Failures keep the
same transport conversion and recovery guidance. Tool descriptions carry the
baseline documentation without improving only one arm's factual guidance.

Configurations without an explicit variant now select `both`. Reconnect clients
to discover the new names and migrate calls as above. Legacy names are not
aliases in the default catalog. Set `tool_interface_variant` to `baseline` to
keep existing callers working unchanged; an explicit variant is preserved.
The two intermediate variants remain available for study reproduction.
No application operation, access policy, revision guard or receipt changed.
