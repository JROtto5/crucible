# crucible

**An independent, evidence-first reviewer for the pull requests you send to other people's projects.**

Before you send a PR to three.js, Colyseus or supabase-js, crucible checks it the way that project's maintainers would. It runs their checks, learns what they actually ask for in review, hunts for real bugs, makes every finding prove itself, and holds the PR description to the project's house style. It never posts anything. You submit.

```text
crucible learn   ~/src/three.js                 # maintainer rules + house style from merged PRs
crucible review  ~/src/three.js --budget 3      # checks → scanners → review → verification → verdict
crucible answer  CR-80b53167 fixed "restore for…of; re-added [1,2,3] test"
crucible status                                  # GREEN / NOT_GREEN + readiness, for this exact commit
crucible polish                                  # PR_DRAFT.md → PR_DRAFT.polished.md in the project's voice
crucible prep                                    # likely maintainer questions + evidence-backed answers
crucible reply   https://github.com/o/r/pull/12  # draft answers to real review comments (never posted)
```

## How a review works

1. **Clean tree, exact commit.** Uncommitted changes to tracked files are refused, so the verdict really describes `HEAD`. The base defaults to `upstream/<default>`, then `origin/<default>`, and the merge-base is printed.
2. **The project's own checks run first.** Lint, typecheck and test commands are detected from `package.json` scripts (CI workflow `run:` lines are shown as hints). You can override them in `~/.crucible/projects/<owner>__<repo>/config.json`. Failures are fed to the reviewer as facts. With `--base-checks`, a failing check is re-run on the base in a throwaway worktree, so a pre-existing failure doesn't block you.
3. **Deterministic scanners.** Secrets, merge markers and debug statements. Secrets in test or fixture paths drop to medium.
4. **House-style checks**, measured against the project's `STYLE.md`:
   - comments denser than the file's own style, or narrating the obvious;
   - big uncommented logic in files that normally explain themselves;
   - generated-sounding descriptions: emoji, "This PR introduces…", filler, bullet bloat, a body far longer than the project median, headings the project never uses;
   - a description with no testing evidence.

   These are medium/low and answerable, not blocking.
5. **Chunked review by a different model than the author.** The author model is read from `Co-Authored-By` trailers, and the reviewer is chosen to differ. Files are grouped into chunks, and big files are split by hunk. **Coverage is recorded, and anything less than 100% can't be GREEN.** The reviewer reads whole functions, callers, the matching tests and public types. It gets concrete severity definitions, at most 10 ranked findings per chunk, and the project's learned rules and repeat-mistakes memory. Every finding must name file:line and a `wrong_if`, the observation that would prove it false.
6. **Verification, one finding per call, in parallel.** The verifier gets only the claim, its `wrong_if` and the cited code, never the reviewer's argument, so it can't anchor on it. Its job is to *disprove* the finding. It may run `node`, the project's test runner or `pytest` to show a concrete result, and it must report exactly what it read or ran. Findings proven by execution rank first. If the verifier fails to return, the finding is kept and marked **unverified** (fail closed).
7. **Honesty caps.** A finding the reviewer itself marks as not caused by this change, or not reachable in real use, is capped to non-blocking `low`.
8. **Dedupe.** Findings with the same root cause (same file, overlapping lines, similar claim) are merged, keeping the higher severity.
9. **Readiness**, deterministic, each item pass/fail/warn with evidence:
   - the PR description matches the template's sections;
   - an issue is linked;
   - tests are touched when source changes;
   - docs/types are touched when exported API changes;
   - a changeset/changelog is added where the repo uses one;
   - conventional commits, if commitlint is configured;
   - DCO sign-off, if required;
   - no whitespace-only churn;
   - size is compared with the project's median merged PR;
   - the issue is still open, unassigned and has no competing open PR (`gh`).

**GREEN** means coverage is complete, no non-pre-existing check failures remain, no critical or important finding is left unless it's fixed or refuted, and every finding has an answer. **Ready to submit** means GREEN plus no failed readiness item.

## Answers, re-reviews, memory

- **Stable IDs.** IDs come from a hash of the file and the normalized claim. Answers to findings that no longer exist are dropped automatically.
- **Re-review on every new commit.** Answers carry forward when the same finding comes back and its cited lines weren't touched since the last reviewed commit, even if the reviewer reworded it. Checks always re-run. Chunk results are cached by content, so unchanged files are free.
- **Feedback.** `crucible vote ID down "reason"` writes a **proposal**, not a rule. `crucible proposals PROJECT --accept N` promotes it into the dated repeat-mistakes memory, and only the newest ~40 entries go into each review.
- **Budget.** `--budget USD` caps spend. Hitting the cap leaves the review incomplete, so it can't be GREEN. The total cost is printed in every report.

## `crucible learn`

Learning reads the project's most recent merged PRs through `gh` and writes three files:
- `rules.md`: recurring requests from maintainer review comments, each with links to its source, and from CONTRIBUTING, AGENTS.md and the PR template.
- `meta.json`: median and p75 merged-PR size.
- `STYLE.md` / `style.json`, measured from PRs by repeat contributors:
  - title format and length;
  - body length (median and p75 words);
  - how often PRs use headings, tables, screenshots and emoji;
  - how issues are referenced;
  - commit format;
  - comment density across the codebase;
  - the voice, comment conventions, how reviewers are called out, and what regulars never do;
  - three real example bodies with links.

## Your PR draft and your notes

crucible reads the description from `PR_DRAFT.md` (or `PR_DRAFT.polished.md`) in the repo. Only the part you would paste into GitHub is judged. Your own notes in the same file are excluded from the style checks, the readiness checks (template sections, the linked issue) and the reviewer's description findings:

- a preamble before a `## Body` heading is skipped, and a `## Title` section gives the title (otherwise a leading `# Title` line does);
- the body ends at the first notes heading (`Explain it to me`, `Issue to file first`, `Author notes`, `Do not submit`, …) or at a `<!-- crucible: notes -->` line.

Headings from the repo's own PR template never count as "headings this project rarely uses", even with emoji prefixes.

## Assistants (drafts only)

- `polish` rewrites the body of `PR_DRAFT.md` in the house style and carries your notes over below a `<!-- crucible: notes -->` line. It keeps every fact, number and test result, adds no unprovable claims, lists anything it removed in `PR_DRAFT.polish-notes.md`, and re-scans the result for generated-text tells.
- `prep` predicts reviewer questions and answers them with file:line and test evidence. It also writes "explain it like you wrote it" notes.
- `reply` fetches the comments on an open PR and drafts replies that follow [docs/answering-maintainers.md](docs/answering-maintainers.md).

crucible's working files (`PR_DRAFT*.md`, `PREP.md`, `REPLIES.md`, `PR.diff`) are added to `.git/info/exclude`, so they never end up in your commit.

## Isolation

Model calls run with `--setting-sources ""` and an empty MCP config. A checked-out project's `.claude/` settings and hooks are never loaded, and your own MCP servers stay out of the loop. The reviewer is read-only (git/read tools). The verifier can additionally run tests and `node`, but has no file-write tools.

## Install

Requires Python 3.10+, git, `gh`, and the [Claude Code](https://claude.com/claude-code) CLI.

```bash
git clone … ~/dev/crucible
printf '#!/usr/bin/env bash\nPYTHONPATH=~/dev/crucible exec python3 -m crucible "$@"\n' > ~/.local/bin/crucible && chmod +x ~/.local/bin/crucible
python3 -m unittest discover -s ~/dev/crucible/tests
```

Environment variables:
- `CRUCIBLE_REVIEW_MODEL`, `CRUCIBLE_VERIFY_MODEL`: override the reviewer and verifier models.
- `CRUCIBLE_ASSIST_MODEL`: the model for `polish`, `prep` and `reply`.
- `CRUCIBLE_CLAUDE_DIR`: which Claude account to bill.
- `CRUCIBLE_HOME`: where state is kept (default `~/.crucible`).

MIT licensed.
