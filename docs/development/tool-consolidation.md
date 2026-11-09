# Static tool consolidation

Status: adopted by user decision on 2026-11-09. The default toolset is `v2`.
See the [completion decision](../../research/tool_consolidation/DECISION.md)
for the accepted validation and unchanged statistical limitations.

Select `toolset_version` in JSON configuration or set
`GDOCS_SCOPE_MCP_TOOLSET_VERSION` before starting a server:

| Toolset version | Insertion | Comment status |
| --- | --- | --- |
| `v1` | `docs_append`, `docs_insert_before`, `docs_insert_after` | `docs_resolve_comment`, `docs_reopen_comment` |
| `v2` (default) | `docs_insert` | `docs_comment_status` |

All catalogs are complete and static for the server lifetime. Restart and
reconnect after changing the version. This setting is independent of document
access mode. No dynamic discovery is introduced.

```json
{"toolset_version": "v2"}
```

The environment variable overrides JSON. Toolset versions describe the public
tool names and argument contracts, independently of package releases. A future
incompatible catalog change requires a new toolset version; bug fixes do not.
The former experimental `tool_interface_variant` field and environment selector
are removed. Replace them with v1 for the old baseline or v2 for the combined
catalog. Old selectors fail rather than silently changing the selected catalog.
Partial study variants are research-only, not public product versions.

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

Configurations without an explicit version now select `v2`. Reconnect clients
to discover the new names and migrate calls as above. Legacy names are not
aliases in the default catalog. Set `toolset_version` to `v1` to
keep existing callers working unchanged; an explicit version is preserved.
All four historical arms remain available through the research-only launcher.
No application operation, access policy, revision guard or receipt changed.

## Evaluation records

Study material is kept with [the research effort](../../research/tool_consolidation/README.md):

- [Completion decision](../../research/tool_consolidation/DECISION.md).
- [Implementation and validation](../../research/tool_consolidation/IMPLEMENTATION_REPORT.md).
- [Preflight](../../research/tool_consolidation/PREFLIGHT.md) and
  [evaluation protocol](../../research/tool_consolidation/EVALUATION_PROTOCOL.md).
- [Model study](../../research/tool_consolidation/REPORT.md),
  [trace audit](../../research/tool_consolidation/AUDIT.md),
  [A/D stage](../../research/tool_consolidation/NI_STAGE1_REPORT.md), and
  [infrastructure follow-up](../../research/tool_consolidation/INFRA_FOLLOWUP.md).
