# Changelog

One line per change, newest first.

- 2026-11-04: Judge only the submitted part of `PR_DRAFT.md`. The author's notes (a preamble before `## Body`, "Explain it to me", "Issue to file first", or anything after `<!-- crucible: notes -->`) no longer drive length, heading or issue-link findings, and `polish` no longer folds them into the body. Headings from the repo's PR template (emoji prefixes included) are no longer flagged as unusual.
- 2026-11-04: Send the model prompt on stdin; `--allowedTools` swallowed it as a tool name when no budget was set.
- 2026-11-04: `crucible waive` for readiness items that don't apply, with the reason shown in the report.
- 2026-11-04: v0.2: project checks, maintainer rules and house style, readiness, executed verification, chunk coverage, carry-forward, polish/prep/reply.
- 2026-11-04: v0.1: scanners, reviewer, verification pass, SHA verdicts, answer loop, memory.
