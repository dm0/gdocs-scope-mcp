# Mixed native list feasibility

Issue: [#47](https://github.com/dm0/gdocs-scope-mcp/issues/47).

The public Docs API exposes list creation through
[`CreateParagraphBulletsRequest`](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#createparagraphbulletsrequest).
Its presets have homogeneous ordered or unordered levels. It does not expose
a request to set individual list-level glyph definitions. Creating bullets
consumes leading tabs and can join the immediately preceding matching list.
Deleting bullets preserves their visual indentation; see
[Work with lists](https://developers.google.com/workspace/docs/api/how-tos/lists).

## Native experiment

`tests/test_live_mixed_lists.py` runs two isolated STDIO servers from the
assigned worktree against the explicitly authorized development document.
The probe appends synthetic paragraphs, requires the current revision on each
batch, reads native list properties and exports matching lines as plain text.
Its fixture deletes the appended region, verifies the original body exactly,
and checks that both subprocesses exit.

On 2026-10-30, the following sequence worked for both ordered parents with
unordered children and unordered parents with ordered children:

1. Create the complete list using the parent's preset and native nesting tabs.
2. Delete the children's bullets, leaving the parent's list identity intact.
3. Restore the children's leading tabs and insert a temporary level-0 root
   paragraph immediately before them.
4. Reset indentation left by bullet deletion, then create bullets for the
   temporary root and children using the child's preset.
5. Delete the temporary root paragraph in the same batch.

The children retain native `nestingLevel: 1` in a separate list; the parent
paragraphs retain their original list ID and level 0. Plain-text export confirms
that ordered parent numbering continues as `1.` and `2.` across the child block.
The temporary root is essential: without it, Google normalized the new child
list to native level 0 even though its visual indentation remained deeper.

This approach uses multiple native list IDs for mixed subtrees. It does not
change the glyph definitions of the parent's list, nor simulate nesting with
paragraph indentation alone. All temporary content must be created and removed
within one atomic native batch. Higher-level conversion must account for the
temporary indices, retain continuation paragraphs, and leave no temporary text
in receipts or the document.
