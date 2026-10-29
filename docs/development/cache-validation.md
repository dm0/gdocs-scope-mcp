# Cache validation across Docs and Drive

[Implementation notes](implementation-notes.md)

## Read-only latency measurements

On 2026-10-29, a large authorized document returned about 8.23 MB of native
JSON. Direct Docs requests for only `revisionId` still took approximately
29–35 seconds. Three Drive metadata requests took 870, 380 and 379 ms.
The measured Docs response did not contain an ETag header.

These are measurements for one document and environment, not service latency
guarantees. Request execution includes HTTP transport and JSON decoding.

## Cross-service freshness experiment

The opt-in `tests/test_live_drive_freshness.py` experiment runs against the
explicit `GDOCS_SCOPE_MCP_LIVE_TEST_DOC`, using isolated STDIO MCP servers and
temporary tabs. It disables the document cache. A test-only tool reads Drive
`version` and `modifiedTime`, reads native Docs revision and marker presence,
then reads Drive again. Each native GET has start and end offsets in the
result, so a metadata/content mismatch can be distinguished from a change
that occurred between requests.

Three successive revision-guarded text insertions on 2026-10-29 produced:

| Insertion | Drive version before | Drive versions bracketing fresh Docs content | Observation completed after write acknowledgement |
| --- | --- | --- | --- |
| 1 | 813 | 815 / 815 | 2.78 s |
| 2 | 815 | 815 / 815 | 2.69 s |
| 3 | 815 | 815 / 815 | 2.82 s |

Every Docs read contained its new marker and a revision different from the
pre-write revision. After insertion 3, additional observations completed at
5.58, 8.29, 17.76, 32.65 and 63.86 seconds after acknowledgement. Drive still
reported version 815 in the final observation. The experiment establishes
stale metadata through that observation; it does not establish a maximum
propagation delay.

A separate Chrome UI check typed a synthetic marker into another temporary
tab. Across 33 observations over 122 seconds, the first observation containing
the marker also showed a changed Docs revision and Drive version 817 (baseline
815). Thus no stale version alongside new text was observed for this UI edit
at the sampling resolution of approximately 3–4 seconds. Drive later advanced
to 819 and 820 while the observed Docs revision remained unchanged. These
observations do not imply immediate propagation for all UI edits. The browser
also showed that the edit had been saved to Drive.

Both temporary tabs were deleted and all pre-existing tabs were checked for
unchanged content, structure and formatting. Image delivery URL rotation is
excluded by the shared native snapshot comparison. Both MCP processes were
closed and reaped after each scenario. Both live scenarios passed. The large
latency-benchmark document was never edited.

## Implications

Drive metadata alone is unsuitable as the validator for the current cache's
strict freshness policy: an unchanged version can accompany newer Docs
content. Reading Drive both before and after the Docs snapshot does not
eliminate this cross-service visibility problem.

The snapshot cache is disabled by default. Explicitly enabling it retains
native Docs revision checks before reuse. A future faster read policy would
need to expose its permitted staleness explicitly, such as a validation TTL
with periodic native Docs checks. Write guards must continue to use native
Docs revision IDs; a Drive version is not a substitute.

## Reproduction

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=AUTHORIZED_DOC_ID uv run --locked pytest -q tests/test_live_drive_freshness.py
```

The optional UI scenario additionally requires
`GDOCS_SCOPE_MCP_FRESHNESS_UI=1`. It writes the temporary tab title, ID and
expected marker to `/tmp/gdocs-drive-freshness-ui-ready.json`, then samples
for two minutes while an operator types that marker into the named tab.
Without that setting, the UI scenario is skipped. It must remain disabled
in unattended test runs.

Reports and subprocess logs are written by the shared fixture to
`/tmp/gdocs-scope-mcp-table-probe-drive-freshness*`. They contain native
revision IDs and synthetic markers; avoid treating them as public artifacts.

## References

- [Drive file metadata](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)
- [Docs document revision semantics](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents)
- [Firsthand Sheets metadata-lag reproduction](https://stackoverflow.com/questions/77389359/google-drive-api-not-returning-modified-time-data-properly)

The Sheets discussion motivated the experiment; the Docs findings above
come from our own separate live checks.
