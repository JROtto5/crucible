# crucible

[![tests](https://github.com/JROtto5/crucible/actions/workflows/tests.yml/badge.svg)](https://github.com/JROtto5/crucible/actions/workflows/tests.yml)

**An independent, evidence-first reviewer for the pull requests you send to other people's projects.**

Before you send a PR to three.js, Colyseus or supabase-js, crucible checks it the way that project's maintainers would. It runs their checks, learns what they actually ask for in review, hunts for real bugs, makes every finding prove itself, and holds the PR description to the project's house style. It never posts anything. You submit.

```text
crucible learn   ~/src/three.js                 # maintainer rules + house style from merged PRs
crucible review  ~/src/three.js --budget 3      # checks → scanners → review → verification → verdict
crucible answer  CR-80b53167 fixed "restore for…of; re-added [1,2,3] test"
crucible status                                  # GREEN / NOT_GREEN + readiness, for this exact commit
crucible polish                                  # PR_DRAFT.md → PR_DRAFT.polished.md in the project's voice
crucible prep                                    # likely maintainer questions + evidence-backed answers
crucible eval                                    # score the reviewer on 16 labelled fixture changes
crucible reply   https://github.com/o/r/pull/12  # draft answers to real review comments (never posted)
```

## Measured, not guessed

`crucible eval` runs the full review on 16 labelled fixture changes in JS, TS and Python. The 12 bug cases cover off-by-one, a null edge, a missing `await`, refcount/ownership, an API break, shell and SQL injection, a units mix-up, a race, pagination, a deleted test hiding a regression and a committed secret. The 4 clean cases are a refactor, a docs change, a fix with tests and an opt-in option with tests. Latest results ([eval/RESULTS.md](eval/RESULTS.md)):

| | recall (blocking) | recall (any severity) | false blocking findings on clean changes | cost, 16 cases |
|---|---|---|---|---|
| v0.2 verification (strong model only) | 92% | 100% | 0 | $4.02 |
| v0.3 tiered verification | 92% | 100% | 0 | verification $1.75 vs $2.30 |

The one blocking miss is the refcount case: the bug is found, but rated medium. Every crucible change has to keep or improve these numbers.

## How a review works

1. **Clean tree, exact commit.** Uncommitted changes to tracked files are refused, so the verdict really describes `HEAD`. The base defaults to `upstream/<default>`, then `origin/<default>`, and the merge-base is printed.
2. **The project's own checks run first.** Lint, typecheck and test commands are detected from `package.json` scripts (CI workflow `run:` lines are shown as hints). In monorepos (nx, pnpm workspaces, lerna, turbo, `workspaces`) the scripts of the packages the change touches run in those package directories. You can override them in `~/.crucible/projects/<owner>__<repo>/config.json`. Failures are fed to the reviewer as facts. With `--base-checks`, a failing check is re-run on the base in a throwaway worktree, so a pre-existing failure doesn't block you. Checks run in your working tree; if one fails and its output names an untracked file (a scratch script, a capture), it is re-run on a clean checkout of HEAD and that result counts, so a scratch file that isn't in the commit can't fail it. The clean checkout has tracked files and `node_modules` only, so a check that needs a gitignored file (`.env`, generated code) can still fail there; the report says which run it shows, and the reviewer sees both outputs.
3. **Deterministic scanners.** Secrets, merge markers and debug statements. Secrets in test or fixture paths drop to medium.
4. **House-style checks**, measured against the project's `STYLE.md`:
   - comments denser than the file's own style, or narrating the obvious;
   - big uncommented logic in files that normally explain themselves;
   - generated-sounding descriptions: emoji, "This PR introduces…", filler, bullet bloat, a body far longer than what outside contributors' merged PRs usually have, headings the project never uses;
   - a description with no testing evidence.

   These are medium/low and answerable, not blocking.
5. **Chunked review by a different model than the author.** The author model is read from `Co-Authored-By` trailers, and the reviewer is chosen to differ. Files are grouped into chunks, and big files are split by hunk. **Coverage is recorded, and anything less than 100% can't be GREEN.** The reviewer reads whole functions, callers, the matching tests and public types. It gets concrete severity definitions, at most 10 ranked findings per chunk, and the project's learned rules and repeat-mistakes memory. Every finding must name file:line and a `wrong_if`, the observation that would prove it false.
6. **Verification, one finding per call, in parallel, in tiers.** A cheap model (`claude-haiku-5-5` by default) checks each finding first. The strong verifier re-checks it only when the claim survived at a blocking severity or the cheap verifier wasn't confident, so verification costs about a quarter less with the same eval recall. The verifier gets only the claim, its `wrong_if` and the cited code, never the reviewer's argument, so it can't anchor on it. Its job is to *disprove* the finding. It may run `node`, the project's test runner or `pytest` to show a concrete result, and it must report exactly what it read or ran. Findings proven by execution rank first. If the verifier fails to return, the finding is kept and marked **unverified** (fail closed).
7. **Honesty caps.** A finding the reviewer itself marks as not caused by this change, or not reachable in real use, is capped to non-blocking `low`.
8. **Dedupe.** Findings with the same root cause (same file, overlapping lines, similar claim) are merged, keeping the higher severity.
9. **Readiness**, deterministic, each item pass/fail/warn with evidence:
   - the PR description matches the template's sections;
   - an issue is linked with a linking keyword or an issue URL (a bare `#123` is often a PR reference and doesn't count; template placeholders like `Closes #(issue_number)` are reported);
   - tests are touched when source changes;
   - when CI runs the tests against several versions of a declared dependency (a `strategy.matrix` axis such as `three-version: [0.159.0, 0.168.0, latest]` or `django-version`, matched to package.json or the Python requirements), the versions the local install doesn't match are named with the command to try the oldest (warn only; `latest`-style values count as covered; waive it once you've run them);
   - docs/types are touched when exported API changes;
   - a changeset/changelog is added where the repo uses one;
   - conventional commits, if commitlint is configured;
   - DCO sign-off, if required;
   - no whitespace-only churn;
   - size is compared with the project's median merged PR;
   - the issue is still open, unassigned and has no competing open PR (`gh`).
   - no other open PR changes the same lines, whatever issue it links (`gh`, warn only). Up to the 300 most recently updated open PRs are read; the 20 most focused that share a file are compared line by line (a line you change inside one of their hunks), listed most focused first. PRs that share only a file are counted, and any PR that couldn't be compared is named, never passed. Bots, your own PRs, lockfiles, changelogs and package.json are ignored.

**GREEN** means coverage is complete, no non-pre-existing check failures remain, no critical or important finding is left unless it's fixed or refuted, and every finding has an answer. **Ready to submit** means GREEN plus no failed readiness item.

## Answers, re-reviews, memory

- **Stable IDs.** IDs come from a hash of the file and the normalized claim. Answers to findings that no longer exist are dropped automatically.
- **Incremental re-review on every new commit.** When the branch has a complete review of an earlier commit with the same base, only the hunks changed since then are reviewed. That includes a commit you amended or squashed: the old commit just has to still exist locally, and share a changed file with the new one. Other findings whose cited lines weren't touched are carried forward with their lines remapped, and findings in touched code are verified again, so a fixed bug drops out. A finding about something missing ("no test for X", "no CHANGELOG entry") is verified again when the file where the missing piece would go changes (the reviewer names it; if it names a file that doesn't exist, any change in that directory counts, and with no name, any change does), with that file's diff in front of the verifier, so it drops out once the test lands. Checks, scanners, house style and readiness always run on the whole change. `--full` forces a full review.
- **Stable verdicts.** Review and verification results are cached by what they depend on (diff, rules, memory, check outcomes), not by volatile check output, so `crucible review --force` on the same commit gives the same findings. `--fresh` redoes the review and bypasses the cache. A plain rerun on a reviewed commit reuses its verdict only if the base and the PR draft are unchanged; edit `PR_DRAFT.md` and the next run judges it again.
- **Answers carry forward** when the same finding comes back and its cited lines weren't touched since the last reviewed commit, even if the reviewer reworded it.
- **Feedback.** `crucible vote ID down "reason"` writes a **proposal**, not a rule. `crucible proposals PROJECT --accept N` promotes it into the dated repeat-mistakes memory, and only the newest ~40 entries go into each review.
- **Budget.** `--budget USD` caps spend. Hitting the cap leaves the review incomplete, so it can't be GREEN. The total cost is printed in every report.
- **Precision log.** `crucible stats` reads your stored reviews offline (no model calls) and prints, per project and overall: reviews, $/review, unique model findings, how many verification kept or dropped, and how the kept ones were answered (fixed / deferred / refuted / unanswered). "Held up" is the share of answered kept findings that weren't refuted. A finding shown in several rounds counts once (same id, or the same title in one project), so carried findings and full re-reviews of an amended commit don't inflate it. `--project owner/name`, `--include-self`, `--json`.
- **Cost routing (opt-in).** `--route` (or `CRUCIBLE_ROUTE=1`) gives a round whose changed files are all docs or PR text (Markdown/reST/AsciiDoc and README/LICENSE-style files; agent instructions and prompt files count as code) one cheaper pass: `claude-sonnet-5-5` reviews (`CRUCIBLE_ROUTE_DOCS_MODEL`), and verification stops at the cheap tier. Code changes keep the full pipeline. It's off by default because no stored review has been docs-only yet, so the replay can't clear it. `crucible routing-replay` replays your stored reviews offline, at no cost, and shows what each candidate rule would have lost: findings by severity (and whether the author later fixed them), extra findings kept, and the refuted share before and after. A rule that loses an important/critical finding, or any medium, stays off. Settling low findings on the cheap tier is such a rule: on 57 upstream reviews it lost 4 real lows, one of which the author fixed.

## `crucible learn`

Learning reads the project's most recent merged PRs through `gh` and writes three files:
- `rules.md`: recurring requests from maintainer review comments, each with links to its source, and from CONTRIBUTING, AGENTS.md and the PR template.
- `meta.json`: median and p75 merged-PR size.
- `STYLE.md` / `style.json`, measured from PRs by repeat contributors:
  - title format and length;
  - body length (median and p75 words), and separately for merged PRs from outside contributors (not owner, member or collaborator). The length check compares a draft with the outside contributors' median when at least 5 such PRs exist, because owners often merge their own PRs with a one-line body;
  - how often PRs use headings, tables, screenshots and emoji;
  - how issues are referenced;
  - commit format;
  - comment density across the codebase;
  - the voice, comment conventions, how reviewers are called out, and what regulars never do;
  - three real example bodies with links.

## Your PR draft and your notes

crucible reads the description from `PR_DRAFT.md` in the repo (or `--draft PATH`). `PR_DRAFT.polished.md` is only a proposal from `polish`: copy it over `PR_DRAFT.md` to accept it. Only the part you would paste into GitHub is judged. Your own notes in the same file are excluded from the style checks, the readiness checks (template sections, the linked issue) and the reviewer's description findings:

- your notes start at the first notes heading (`Explain it to me`, `Issue to file first`, `Author notes`, `Do not submit`, …) or at a `<!-- crucible: notes -->` line, and run to the end of the file;
- before that point, a `## Body` heading starts the body, and anything above it (a metadata preamble, a `## Title` section) counts as notes;
- a `## Title` section gives the title; without `## Body`, a leading `# Title` line does.

Markers inside code fences are ignored.

Headings from the repo's own PR template never count as "headings this project rarely uses", even with emoji prefixes.

## Assistants (drafts only)

- `polish` rewrites the body of `PR_DRAFT.md` in the house style and carries your notes over below a `<!-- crucible: notes -->` line. Issue-link lines the template requires (`Closes #12`, `Related issue: #34697`) always survive the rewrite verbatim. It keeps every fact, number and test result, adds no unprovable claims, lists anything it removed in `PR_DRAFT.polish-notes.md`, and re-scans the result for generated-text tells.
- `prep` predicts reviewer questions and answers them with file:line and test evidence. It also writes "explain it like you wrote it" notes.
- `reply` fetches the comments on an open PR and drafts replies that follow [crucible/guides/answering-maintainers.md](crucible/guides/answering-maintainers.md).

crucible's working files (`PR_DRAFT*.md`, `PREP.md`, `REPLIES.md`, `PR.diff`) are added to `.git/info/exclude`, so they never end up in your commit.

## Isolation

Model calls run with `--setting-sources ""` and an empty MCP config. A checked-out project's `.claude/` settings and hooks are never loaded, and your own MCP servers stay out of the loop. The reviewer is read-only (git/read tools). The verifier can additionally run tests and `node`, but has no file-write tools.

## Install

Requires Python 3.10+, git, `gh`, and the [Claude Code](https://claude.com/claude-code) CLI.

```bash
pipx install git+https://github.com/JROtto5/crucible   # or: pip install --user git+https://github.com/JROtto5/crucible
crucible --version
```

Nothing else is installed: crucible uses only the Python standard library. To work on crucible itself, or to run `crucible eval` (its fixture cases live in the repository, not the package):

```bash
git clone https://github.com/JROtto5/crucible && cd crucible
pipx install --editable .
python3 -m unittest discover -s tests
```

Environment variables:
- `CRUCIBLE_REVIEW_MODEL`, `CRUCIBLE_VERIFY_MODEL`: override the reviewer and verifier models.
- `CRUCIBLE_ASSIST_MODEL`: the model for `polish`, `prep` and `reply`.
- `CRUCIBLE_CLAUDE_DIR`: which Claude account to bill.
- `CRUCIBLE_VERIFY_CHEAP`: the cheap verification tier (default `claude-haiku-5-5`; `none` turns tiering off, as does `--no-tiers`).
- `CRUCIBLE_HOME`: where state is kept (default `~/.crucible`). `CRUCIBLE_CACHE` can point at a shared cache.

Run `crucible eval` (about $2–4 for all 16 cases) after changing prompts or models.

Found a wrong finding, a missed bug or a crash? See [CONTRIBUTING.md](CONTRIBUTING.md): issue templates ask for exactly what's needed to turn it into a regression test.

MIT licensed.
