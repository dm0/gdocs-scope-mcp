# List read round-trip measurements

This study measures synthetic list representations. It never accesses Google
documents. Run from the repository root using the root Python project:

```bash
uv run --locked --with tiktoken==0.12.0 python research/list_read_roundtrip/measure_list_tokens.py
```

The optional tokenizer uses a temporary uv environment without changing project
dependencies. See [the report](../../docs/development/list-read-roundtrip.md)
for methodology, character counts and limits of the token estimates.
