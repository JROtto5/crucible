# Changelog

One line per change, newest first.

- 2026-11-04: Notes headings must open the heading, the review log says where the notes were cut, `prep` gets the submitted description and the notes separately, and inline ```code``` lines no longer open a fence.
- 2026-11-04: Draft splitting follows CommonMark fences, ignores a `## Body` inside the notes, keeps the preamble with the notes through `polish`, never duplicates the notes marker, and only flags headings against learned measurements (all found by crucible reviewing its own change).
- 2026-11-04: Judge only the submitted part of `PR_DRAFT.md`. The author's notes (a preamble before `## Body`, "Explain it to me", "Issue to file first", or anything after `<!-- crucible: notes -->`) no longer drive length, heading or issue-link findings, and `polish` no longer folds them into the body. Headings from the repo's PR template (emoji prefixes included) are no longer flagged as unusual.
- 2026-11-04: Send the model prompt on stdin; `--allowedTools` swallowed it as a tool name when no budget was set.
- 2026-11-04: `crucible waive` for readiness items that don't apply, with the reason shown in the report.
- 2026-11-04: v0.2: project checks, maintainer rules and house style, readiness, executed verification, chunk coverage, carry-forward, polish/prep/reply.
- 2026-11-04: v0.1: scanners, reviewer, verification pass, SHA verdicts, answer loop, memory.
