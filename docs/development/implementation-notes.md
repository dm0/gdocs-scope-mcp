# Implementation notes

[README](../../README.md) · [Development](../development.md) · [Result contracts](../protocol.md)

This index collects internal design documents and API research. For tool
arguments, examples and supported behavior, start with the [document tools](../tools/documents.md),
[table tools](../tools/tables.md) and [comment tools](../tools/comments.md).

## Current implementation

| Document | Contents | Verification |
| --- | --- | --- |
| [Concurrent edits](../concurrent-edits.md) | Revision policies, dependencies, retries, atomicity and unknown write outcomes | [Tests and reproduction](../concurrent-edits.md#verification) |
| [Table references](../table-references.md) | Checked positions, structural inventories, selective expectations and structural operations | [Tests and reproduction](../table-references.md#verification) |
| [Table discovery](../table-discovery.md) | First-tab traversal, physical/logical geometry, pagination and bounds | [Tests and reproduction](../table-discovery.md#validation) |

## API research

[Table identity and concurrent writes](../table-identity.md) records historical
API probes and their results, including named-range behavior across structural
changes. Its candidate native-identity strategy is research only; production
tools use the checked positional-reference contract linked above. The research
log does not replace current tool contracts.
