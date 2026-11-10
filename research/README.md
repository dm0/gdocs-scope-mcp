# Research

Each study lives in its own named subdirectory. Keep its scripts, synthetic
fixtures, README and research-only `tests/` together; do not put experiment
scripts or tests directly in this directory or the product test suite.

Run study commands explicitly from the repository root using the root Python
project and this checkout's environment. The default pytest run discovers only
the root `tests/` directory. Research model inference is an explicit command,
never an automatic test side effect. Keep generated logs, traces and datasets
outside tracked source. Keep study-specific reports with their study; product
implementation documentation belongs under `docs/`; study protocols and
evaluation reports belong in the study's own directory.

| Study | Scope |
| --- | --- |
| [Tool consolidation](tool_consolidation/README.md) | #59: isolated model runtime, synthetic fixtures, native calibration and paired interface evaluation. |
| [On-demand catalog](on_demand_catalog/README.md) | #60: closed without server-side reorganization; client-native deferred loading research and retained reproduction tools. |
| [List read round-trip](list_read_roundtrip/README.md) | Synthetic Markdown/HTML list token measurements. |
