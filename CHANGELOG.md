# Changelog

One line per change, newest first.

- 2026-11-04: **v0.3.0.** `crucible eval`: 16 labelled fixture changes (12 planted bugs, 4 clean) scored for recall, false blocking findings, true findings dropped by verification, and cost; results in eval/RESULTS.md. Baseline: 92% blocking recall, 100% any-severity, 0 false blocking.
- 2026-11-04: Tiered verification: a cheap model checks each finding first, and the strong model re-checks survivors at blocking severity or low confidence. Same eval recall, 24% lower verification cost ($1.75 vs $2.30 on the eval set). `--no-tiers`, `CRUCIBLE_VERIFY_CHEAP`.
- 2026-11-04: Incremental re-review: only hunks changed since the branch's last complete review are reviewed; untouched findings are carried with remapped lines, touched ones are re-verified (so fixed bugs drop out). `--full` forces a full review.
- 2026-11-04: Stable verdicts: review/verification cache keyed on what results depend on, not volatile check output, so `--force` on the same commit reproduces the findings; `--fresh` bypasses the cache (real-use bug e).
- 2026-11-04: "issue linked" needs a linking keyword or an issue URL; a bare #N (often a PR) no longer counts, a linked PR fails "unclaimed", and template placeholders are reported (bug a). Monorepo check detection runs the touched packages' scripts in their directories (bug b). `polish` keeps required issue-link lines verbatim (bug c). `PR_DRAFT.polished.md` is never judged unless passed with `--draft` (bug d).
- 2026-11-04: Fixed `map_line` for pure insertion/deletion hunks; carried findings could land a line off.
- 2026-11-04: CI on GitHub Actions (unit tests, Python 3.10–3.13).

- 2026-11-04: Notes headings must open the heading, the review log says where the notes were cut, `prep` gets the submitted description and the notes separately, and inline ```code``` lines no longer open a fence.
- 2026-11-04: Draft splitting follows CommonMark fences, ignores a `## Body` inside the notes, keeps the preamble with the notes through `polish`, never duplicates the notes marker, and only flags headings against learned measurements (all found by crucible reviewing its own change).
- 2026-11-04: Judge only the submitted part of `PR_DRAFT.md`. The author's notes (a preamble before `## Body`, "Explain it to me", "Issue to file first", or anything after `<!-- crucible: notes -->`) no longer drive length, heading or issue-link findings, and `polish` no longer folds them into the body. Headings from the repo's PR template (emoji prefixes included) are no longer flagged as unusual.
- 2026-11-04: Send the model prompt on stdin; `--allowedTools` swallowed it as a tool name when no budget was set.
- 2026-11-04: `crucible waive` for readiness items that don't apply, with the reason shown in the report.
- 2026-11-04: v0.2: project checks, maintainer rules and house style, readiness, executed verification, chunk coverage, carry-forward, polish/prep/reply.
- 2026-11-04: v0.1: scanners, reviewer, verification pass, SHA verdicts, answer loop, memory.
