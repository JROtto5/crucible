# Command reference

Every command runs locally. crucible never pushes, comments, approves or posts: you submit. `crucible <command> --help` prints the same flags. Stored data lives in `~/.crucible` (or `$CRUCIBLE_HOME`).

New here? Start with [the quickstart](quickstart.md). The description layout (`PR_DRAFT.md`, what counts as your notes) is in the README under "Your PR draft and your notes".

## The loop

```
crucible learn            # once per project: maintainer rules + house style from merged PRs
crucible review           # checks → scanners → model review → per-finding verification
crucible answer ID fixed|refuted|deferred "evidence"
crucible review           # after a fix commit: reviews only what changed since the last round
```

The verdict is GREEN when every finding is answered, no important or critical finding is left open (only `fixed` or `refuted` closes one; `deferred` doesn't), every changed file was reviewed, and no project check fails that passes on the base. "Ready to submit" also needs the readiness items to pass or be waived.

## review

`crucible review [REPO] [--base REF]`

Reviews HEAD against the branch the PR targets. The default base is `upstream/<default>`, then `origin/<default>`, then a local main/master/dev. It runs the project's own lint and test commands, the scanners and readiness, then the model review in chunks. Each candidate finding goes to a separate verifier that tries to falsify it, reading the code or running a probe, and it is kept only if it survives.

- `--force`: review this commit again even if it was already reviewed with the same base and draft. Cached review passes and verdicts are reused, so the findings stay the same.
- `--fresh`: redo everything and bypass the cache.
- `--full`: review the whole change, not just what changed since the last review of this branch.
- `--draft PATH`: the PR description to judge (default `PR_DRAFT.md` in the repo).
- `--budget USD`: stop making model calls once this much is spent.
- `--skip-checks`: don't run the project's lint/test commands. The verifier may still run small probes (`node -e`, `python3 -c`, the test runner).
- `--no-exec` (or `CRUCIBLE_NO_EXEC=1`): run nothing from the checkout. Implies `--skip-checks`, and the verifier gets only read tools (Read/Grep/Glob, `git diff|log|show|grep|blame`, `ls`), so every verification is by reading. Use it in sandboxes and on code you don't trust. A later run without the flag re-reviews instead of reusing the read-only verdict. `--base-checks` re-runs failing checks on the base, to tell pre-existing failures from new ones.
- `--offline`: no GitHub calls (readiness skips the issue, claim and open-PR checks).
- `--author MODEL`: the model that wrote the change, if any (else read from `Co-Authored-By`). The reviewer is chosen to be a different model.
- `--no-tiers`: verify every finding with the strong model only (default: cheap model first, escalate when unsure or blocking).
- `--route`: a round that changes only docs or PR text gets one cheaper pass. Off by default; `crucible routing-replay` shows why.

Exit code 0 means GREEN. The report is printed and saved next to `review.json` in `~/.crucible/reviews/<owner>__<name>/<sha>/`. Its header gives the cost and the tokens used.

Readiness checks whether the linked issue is still unclaimed and whether another open PR changes the same lines. Your own assignment and your own PRs don't count against you. "You" is `CRUCIBLE_GH_USER` if set, else the account `gh` is logged in as. If neither is available, nobody is skipped, and both checks say so when they flag something.

## status

`crucible status [REPO]`: prints the stored report for HEAD without calling a model. Exit 0 when GREEN.

## answer

`crucible answer ID fixed|refuted|deferred "note" [--repo R]`

Answers a finding on HEAD's review. The note is the evidence: the fixing commit, or why the claim is wrong. Answers carry to later rounds by finding id, and `stats` counts them. A new commit needs a new review before you can answer its findings.

## waive

`crucible waive ITEM "reason" [--repo R]`: marks a readiness item as not applicable on this branch. The reason must be at least 20 characters, and the report prints it.

## learn

`crucible learn [REPO] [--prs N] [--no-style]`

Reads the project's last N merged PRs (default 25) and its contributing docs. It writes the maintainer rules the review checks against, and the house style: body length, headings, comment density. Bot PRs and commits that aren't on the upstream branch are skipped.

## polish, prep, reply

- `crucible polish [REPO]`: rewrites the body of `PR_DRAFT.md` in the house style into `PR_DRAFT.polished.md`. It keeps every fact and the template's issue lines. Copy the result over `PR_DRAFT.md` to accept it.
- `crucible prep [REPO]`: the questions a maintainer is likely to ask about this change, written to `PREP.md`.
- `crucible reply PR_URL [--repo R]`: draft answers to a PR's review comments, written to `REPLIES.md`. Nothing is posted.

These working files are added to `.git/info/exclude`, so they never end up in a commit.

## Feedback and memory

- `crucible vote ID up|down "reason"`: thumbs on a finding. A down-vote becomes a memory proposal, not a rule.
- `crucible proposals OWNER/NAME [--accept N]`: list proposals, or accept one into the project's memory.
- `crucible remember OWNER/NAME "lesson"`: add a lesson directly. Every later review reads the memory.

## Measuring

- `crucible stats [--project P] [--since T] [--json]`: the real-PR precision log, offline. It shows how many kept findings were fixed, deferred or refuted, "held up" with its 95% interval, the cost per held-up finding, and tokens per held-up finding for reviews that recorded token counts, with calls, $ and cache write / read tokens per call kind (review, verify_cheap, verify, salvage) for reviews stored since per-kind metering.
- `crucible eval [--cases ...] [--split build|holdout]`: runs the review on the labelled fixture changes in `eval/` and scores recall and false blocking. This costs money (about $4 for the full set).
- `crucible routing-replay`: replays stored reviews offline to show what each cost-routing rule would have lost.
- `crucible anchor-replay --clones DIR [--votes N]`: re-verifies answered findings with and without the reviewer's argument, to measure anchoring. With `--votes N` a finding is kept only if all N verdicts keep it, and the report adds the first vote alone and how often the votes split. This makes model calls (N per finding per arm).
- `crucible model-replay --clones DIR [--models opus sonnet] [--rounds N] [--budget USD] [--exclude SHA...] [--fresh]`: re-reviews stored full rounds once per reviewer model, at the commit and base they were reviewed at, and scores each arm against the author's answers (fixed/deferred = held up, refuted = false alarm). A replayed finding matches a labelled one by file, nearby line and shared wording; kept findings that match no label are listed for you to judge. Labels exist only for findings the stored arm (the first model) raised, so this favours it on recall. Each arm runs with `--no-exec --offline --full --fresh` in a throwaway home, so stored reviews and `stats` are untouched. This makes model calls (a full review per round per arm; `--budget` caps each). The report breaks each arm down by change shape: kind (single-file or multi-file by production files, i.e. outside tests and docs; tests only; docs/PR text) and production lines changed (≤50, 51–200, >200), with buckets under 60 labelled findings marked too few to quote. Each finished arm is kept in `~/.crucible/replays/model-arms` (keyed by round, base, model and `--budget`) and scored again from there by later runs, so answers given since re-label it and a larger `--rounds` pays only for the rounds it adds: rounds already replayed with every arm stay in the sample first. The report says how many arms were reused and what this run spent. `--fresh` re-runs every arm; `--exclude` leaves out rounds by commit prefix (7+ hex characters).
