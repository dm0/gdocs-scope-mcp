# Repository working agreements

Before changing project code, read [docs/architecture.md](docs/architecture.md)
and follow its dependency rules and extension recipes. Keep that document in
sync with structural changes.

Keep every research effort in its own named subdirectory under `research/`.
Place its experiment scripts, fixtures and research-only tests together there,
with tests in that study's `tests/` subdirectory. Keep research tests out of the
default product test suite; run them explicitly from the repository root using
the root Python project. Keep production behavior/contract tests in `tests/`.
Document each study's commands and scope in its own README, link it from
`research/README.md`, and keep generated logs and study artifacts untracked.

Never store real Google folder or document IDs in repository files. Supply
live IDs through environment variables or private artifacts outside the
checkout. Use clearly synthetic placeholders in documentation and fixtures.
