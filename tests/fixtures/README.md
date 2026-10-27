`google_document.json` is an unchanged copy of the Google Docs API response
provided in the workspace's `data/doc.json`. It covers headings, lists, inline
styles, paragraph alignment, images, and a table. Keeping the snapshot here
makes the offline tests independent of the parent workspace and Google access.

Tests currently assert supported hierarchy and text-formatting behavior, not
complete round-trip fidelity for every element in this response. The smaller
synthetic fixture in `conftest.py` supplies ASCII text and repeated anchors for
precise edit assertions.

# Native code fixture

`native_code.json` retains the API structure of a code block created through
Insert > Building blocks > Code block in the authorized development document
on 2026-10-27. Python was selected in the UI. Document identity and indices were
normalized; redundant font/color fields were reduced. The text is synthetic.
The API exposes separate U+E907 delimiter runs, Roboto Mono text runs, and normal
paragraphs without explicit line spacing, shading, or a language field. This
is observed behavior, not a documented API guarantee. The same delimiter
structure was present with the UI language set to None before choosing Python.
