# Repository working agreements

Before changing project code, read [docs/architecture.md](docs/architecture.md)
and follow its dependency rules and extension recipes. Keep that document in
sync with structural changes.

Read the applicable workspace instructions completely as well. In the main
checkout they are in `../AGENTS.md`. In a linked worktree, use
`git worktree list --porcelain` and
`git rev-parse --path-format=absolute --git-common-dir` to locate the main
checkout and read its root and immediate parent's `AGENTS.md`, in addition to
instructions at this worktree and its immediate parent. The current workspace
file is `/home/lapin/projects/sandboxes/gdocs-scope-mcp/AGENTS.md`.

Run project commands and environment setup in the assigned worktree with its
own environment. Preserve unrelated changes. Workspace instructions govern
validation, live-document authorization, logical-stage commits and delivery
scope; this file intentionally does not reproduce historical handoff notes.
