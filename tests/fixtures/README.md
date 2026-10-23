`google_document.json` is an unchanged copy of the Google Docs API response
provided in the workspace's `data/doc.json`. It covers headings, lists, inline
styles, paragraph alignment, images, and a table. Keeping the snapshot here
makes the offline tests independent of the parent workspace and Google access.

Tests currently assert supported hierarchy and text-formatting behavior, not
complete round-trip fidelity for every element in this response. The smaller
synthetic fixture in `conftest.py` supplies ASCII text and repeated anchors for
precise edit assertions.
