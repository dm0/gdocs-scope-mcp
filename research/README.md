# Research scripts

Keep development experiments and measurement scripts here. Reports and
implementation documentation belong under `docs/`; do not place scripts there.

## Isolated Codex study runtime

`codex_study_runtime.py` uses the installed Codex app-server protocol and the
user's existing Codex authentication to create fresh ephemeral chats on the
approved #59 model roster. It requires Python 3.11+ and Codex CLI
`0.166.0-alpha.6` with experimental dynamic tools. It disables configured MCP
servers and unrelated capabilities only for its own process, never by editing
the user's configuration. Unknown server-name syntax fails closed.

The bounded infrastructure probe uses only a synthetic echo tool:

```bash
uv run --locked python research/codex_study_runtime.py \
  --model gpt-6-luna --output /tmp/gdocs-59-isolated-probe/luna
```

This checks model dispatch, `medium` reasoning, dynamic-tool callbacks and
process cleanup. It is not a pilot or evidence of improved tool correctness.
The ordinary Codex state directory must be writable during app-server startup;
the restricted parent sandbox may therefore require native tool approval.

## List token measurements

From the repository root:

```bash
uv run --locked --with tiktoken==0.12.0 python research/measure_list_tokens.py
```

The optional tokenizer is loaded into a temporary uv environment without
changing project dependencies. Inputs are synthetic; the script does not access
Google documents. See [the report](../docs/development/list-read-roundtrip.md)
for methodology, character counts and limits of the token estimates.
