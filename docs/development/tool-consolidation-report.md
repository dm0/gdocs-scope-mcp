# Study 1: implementation and validation report

Date: 2026-11-06.
Status: implementation validated; model study pending roster approval.
Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).

## Decision and scope

Keep **baseline** as the default and retain all four executable static variants.
There is no evidence yet that consolidation improves agent correctness. Issue
#59 remains open: regression checks do not satisfy its required model study.
No push, release, publication or deployment was performed.

The pre-treatment repository revision was
`6f7d48ce0f5db0b03fbdde2a099306dc7982a25f`. The implementation commit is
`ae597460e0cb161384fbdd1abc4dc94de904de2b`; the additional STDIO/live regression
tests are in `6e65a16`. The study's executable baseline is the `baseline` variant
at the same implementation revision as each treatment. This avoids confounding
the interface treatment with different application implementations.

## Implemented interfaces

See [configuration and migration](tool-consolidation.md). Only append/before/
after and resolve/reopen interfaces are consolidated. Heading-subtree
insertion, replacement, destructive comment operations and table operations
retain their existing contracts and approval hints. The selected catalog is
fixed before accepting client connections. Document-access scope is unchanged.

Consolidated adapters delegate to the existing Python tool functions. Their
descriptions include the unchanged baseline documentation. Success responses
keep operation-specific receipt models. Argument validation rejects missing
anchors, contradictory append selectors and unknown target fields before
Google access. Existing repeated-anchor matching is preserved; consolidation
does not introduce uniqueness validation. Google input/image error recovery
guidance also applies to the new insertion tool.

## Automated evidence

The complete offline run passed: **2398 passed, 1 skipped, 138 deselected**.
The deselected tests are opt-in live scenarios, not model trials. The run log
and JUnit report are `/tmp/gdocs-59-offline-final.log` and
`/tmp/gdocs-59-offline-final.xml`. An earlier run failed because the exhaustive
environment-variable test inventory omitted the new setting; that inventory
was updated before the successful complete rerun.

Focused contract checks cover all four static catalogs, unchanged tools and
annotations, literal/rich native insertion requests and receipts, formatting
overrides, expected revisions, missing/repeated anchors, target validation,
comment action/reply delegation, and structured Google input failure guidance.
The original complete baseline contract digest remains unchanged. Global Ruff
and `git diff --check` passed.

Fresh STDIO discovery passed for all four variants in both access modes. All
non-treatment tool definitions are exactly identical within each access mode;
repeated discovery in the same session is stable. Captures include full schemas,
initialization instructions, process identity and source fingerprints, under
`/tmp/gdocs-59-stdio/test_stdio_study_catalogs_full0/` and
`/tmp/gdocs-59-stdio/test_stdio_study_catalogs_sele0/`.

| Variant | Full-drive tools | Selected-files tools | Full-drive serialized bytes |
| --- | ---: | ---: | ---: |
| A: baseline | 39 | 40 | 232421 |
| B: insertion | 37 | 38 | 225233 |
| C: status | 38 | 39 | 230510 |
| D: both | 36 | 37 | 223322 |

Sizes use sorted-key Python JSON serialization of the full instructions and
catalog, including descriptions, annotations and schemas, with default ASCII
escaping. These are byte counts, not token usage or evidence of correctness.

Full-drive catalog SHA-256 values:

```text
A 544366336de25c02638d251a6fa0028402f47353d8d11f8f8e23c13f2f42077a
B 8e23e80eaf09646be6ed698b158c4f36d945d79fdbc7ff17a3710c82ac31726d
C b51af62ce6561f85c80b2a5d190292c1214e228647a2c5698a546dd9f2851d60
D 2339ad91fed9fa3a323df627d11ba8ddcbbab918f02ed12e82b2d47dab061aed
```

Four live adapter scenarios passed through isolated worktree STDIO servers
against the explicitly authorized development document. Each variant checked
append, before/after insertion, bold/literal text, emoji, a native table, strict
stale-revision rejection, native resolve/reopen action posts with ALL_SAVED,
native comment readback, unchanged surrounding tabs and cleanup. Temporary tabs
and comments were removed. Shared-document setup/final reset passed, leaving
one empty tab, no active comments, no named ranges and no pending suggestions.
All test-owned subprocesses were reaped. Logs and per-variant receipts are under
`/tmp/gdocs-59-live-run/`; JUnit is `/tmp/gdocs-59-live-run.xml`. The document
session report is `/tmp/gdocs-scope-mcp-live-session-r4slg4dc/report.json`.
The four expected `EDIT_CONFLICT` failures in stderr are negative assertions.

An additional combined run of the pre-existing insertion-style, native-comment
and heading-subtree live regressions lost its tool launcher (exit 143), while
the pytest child continued. Read-only host inspection confirmed PID 699070
owned the shared-document lock and matched this exact test command. A second
native-comment invocation correctly refused the occupied lock without touching
the document. Its diagnostic log is `/tmp/gdocs-59-native-comments.log`.
The original run completed: **7 passed in 528.64 seconds**. Its log and JUnit
are `/tmp/gdocs-59-live-regressions.log` and
`/tmp/gdocs-59-live-regressions.xml`. This covers hostile source styles for all
three original insertion tools, nested-list heading insertion, native comment
lifecycle, and heading-subtree revision races in required and target modes.
The session report `/tmp/gdocs-scope-mcp-live-session-hhhjf2h4/report.json`
confirms final reset and subprocess cleanup. The second lock-refused invocation
is retained as an infrastructure attempt, not counted as an application failure
or a passing test.

Worktree live identity: Python 3.14.4, FastMCP 3.3.1, package path
`/home/lapin/.codex/worktrees/4444/gdocs-scope-mcp/src/gdocs_scope_mcp`, source
SHA-256 `24a7be585f48b91ff41368c75bbdbb2a50bc025973a9f088b8692e8444ca9990`.
Source identity, not the editable package's cached version string, identifies
the tested implementation.

Wheel and sdist builds passed and include all 99 Python modules. An isolated
wheel installation successfully ran server identity, baseline discovery,
`both` discovery (36 tools), and authorization CLI help. Its package path was
`/tmp/gdocs-59-wheel-env/lib/python3.14/site-packages/gdocs_scope_mcp`, with the
same source fingerprint. Unconstrained installation resolved FastMCP 4.1.6;
this is packaging/discovery evidence only, not a second live regression run.
Artifacts/logs use `/tmp/gdocs-59-dist/`, `/tmp/gdocs-59-build.log` and
`/tmp/gdocs-59-wheel-*`. The environment selector must be inside FastMCP CLI's
`--command 'env ... gdocs-scope-mcp'`: the CLI filters its child's environment.

## Reproduction

Run from the assigned worktree using its `pyproject.toml` and environment:

```bash
uv sync --locked
uv run --locked pytest -m 'not live' -q
uv run --locked pytest tests/test_tool_consolidation_stdio.py -m 'not live' -q
```

For the opt-in adapter lifecycle tests, set `GDOCS_SCOPE_MCP_LIVE_TEST_DOC` to
the authorized development Doc ID and keep optional UI waits disabled, then run:

```bash
uv run --locked pytest tests/test_tool_consolidation_stdio.py -m live -q
```

This uses the existing document-session lock and isolated STDIO fixtures.
Do not run concurrent sessions against the shared test document. Local `/tmp`
artifacts are diagnostic evidence, not durable published evaluation data.

## Model-study readiness and limitations

The user requested new Codex chats as the execution route and a roster preview
before starting. Current chat turn metadata records `gpt-6.1-sol`, reasoning
`medium`. The host's thread-creation catalog lists `gpt-6-luna`, `gpt-6.1-sol`
and `gpt-6-astra`; these are proposed weaker/current/stronger choices, all with
`medium` reasoning, pending explicit approval. Host availability is not a
completed inference/access check. This proposal mixes minor versions 6 and 6.1
within GPT-6 and requires that limitation to be agreed and recorded. No tested
capability ordering or exact backend snapshot is inferred from host labels.

No model-evaluation chats have been launched, no model trajectories collected,
and no pilot/held-out dataset, run manifest, budgets, stopping rule or adoption
thresholds frozen. The mandated paired model effects, confidence intervals,
human audit, usage and error taxonomy are therefore unavailable. The protocol
starts with 480 pilot runs per level (960 across both levels), followed by
3600 held-out runs per level (7200 total); a small smoke test cannot replace it.

Before a chat-based study, verify that catalog exposure, fresh-session
independence, unrelated-tool restrictions, agent-loop settings and trace capture
can meet the [shared protocol](tool-interface-evaluation.md). Any host-imposed
limitations must be recorded before the pilot, not silently attributed to the
interface. Keep the baseline until the required evidence supports a decision.
