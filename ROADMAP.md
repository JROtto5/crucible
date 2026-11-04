# crucible 1.0 checklist

Target: about 2027-01-04. 1.0 means a maintainer or a first-time contributor can install it, run it on a real PR and trust what it says.

## Precision, measured on real PRs
- [ ] `crucible stats`: kept vs dropped-by-verification vs later refuted (from answers), per project and overall
- [ ] A labelled set of at least 20 real merged upstream PRs replayed through `crucible review`, with precision and recall reported in the README
- [ ] Each false-positive class seen in real reports gets a regression test (started: author notes counted as the PR body; template headings flagged as unusual)
- [ ] The verifier can only run `pytest` on Python repos (no `python3 -c` probes), so Python findings are verified by reading far more often than JS ones (seen in crucible's own reviews, 2026-11-04). Decide on a safe probe runner
- [ ] Prefer `Closes/Fixes #N` over a bare `#N` for "issue linked", and reject template placeholders (BOARD bug a; the notes part is fixed)
- [ ] Baseline, 2026-11-04 (5 reports, 3 projects): 18 kept, 12 dropped by verification, 1 kept finding later refuted by the author

## Quickstart and docs
- [ ] `pip install`-able package with a `crucible` entry point (no hand-written shim)
- [ ] Five-minute quickstart from clone to first report
- [ ] Docs page for each command, including the `PR_DRAFT.md` layout
- [ ] A worked example report from a public PR

## Demo
- [ ] Recorded terminal demo (review → answer → GREEN) on a public repo

## Clean code
- [ ] Tests for `review.run_review` with a stubbed model (no network)
- [ ] Lint (ruff) clean and run in CI
- [ ] CI on GitHub Actions for the unit tests

## Safe defaults
- [x] Never posts, never pushes upstream, never approves (drafts only)
- [x] Model calls isolated from the project's `.claude/` settings and the user's MCP servers
- [x] Budget cap that leaves the review incomplete rather than GREEN
- [ ] A test asserting that no command path calls `gh` with a write verb
