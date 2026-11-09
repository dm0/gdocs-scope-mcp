# Completion and adoption decision

Date: 2026-11-09. Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).

The user accepted validation and requested completion without more model trials,
including removal of temporary debugging changes. This is an explicit product
acceptance decision, not a revision of the statistical result or a claim that
the original noninferiority gate passed.

Adopt the fully consolidated catalog as the startup default (`both`):
`docs_insert` replaces append/before/after and `docs_comment_status` replaces
resolve/reopen. The full-drive catalog falls from 39 to 36 tools; selected-files
falls from 40 to 37. Existing application operations, revision and approval
semantics, content formats, access scope and receipts are preserved. Explicit
`baseline` remains a supported migration fallback. The two intermediate static
variants remain executable as required by the issue's reproducibility scope.

Model inference is finished at 2833 cumulative reservations. No 1500- or
3000-session Luna continuation was authorized or started. The final separate
[infrastructure follow-up](INFRA_FOLLOWUP.md) yielded 250 complete A/D pairs per
model after the recorded bold-oracle correction:

| Model | Baseline success | Consolidated success | Paired effect, pp | Descriptive 95% CI, pp |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-luna | 240/250 | 242/250 | +0.80 | [-2.40, +3.20] |
| gpt-6.1-sol | 250/250 | 250/250 | 0.00 | [0.00, 0.00] |
| gpt-6-astra | 250/250 | 250/250 | 0.00 | [0.00, 0.00] |

Luna does not establish noninferiority within 2 pp. Ceiling intervals for the
other models do not establish equivalence. Follow-up replacement, the fixed
25-template mixture, hybrid native/synthetic execution and unblinded assistant
review remain limitations. Historical protocols, reports, grades and private raw
traces are retained without pooling earlier campaigns or relabeling failures.

Research-only controllers, simulator, fixtures and their tests stay together
under this study directory, outside production imports and default pytest
collection. They are reproducibility artifacts, not production diagnostics.
The shipped package must contain no study actor, callback simulator, extra
debug logging, permanent-document fallback or embedded live document/folder ID.

Engineering completion checks and the final local commit are recorded below
after cleanup. Publication, release and deployment are separate actions.
