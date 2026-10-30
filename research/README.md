# Research scripts

Keep development experiments and measurement scripts here. Reports and
implementation documentation belong under `docs/`; do not place scripts there.

## List token measurements

From the repository root:

```bash
uv run --locked --with tiktoken==0.12.0 python research/measure_list_tokens.py
```

The optional tokenizer is loaded into a temporary uv environment without
changing project dependencies. Inputs are synthetic; the script does not access
Google documents. See [the report](../docs/development/list-read-roundtrip.md)
for methodology, character counts and limits of the token estimates.
