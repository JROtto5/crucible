# crucible on ReviewBench

Adapter for [ReviewBench](https://github.com/review-bench/ReviewBench) (its `AGENT_CONTRACT.md`): one PR in, one
findings file out.

- `Dockerfile`: python:3.13-slim + crucible from this repo + the Claude Code CLI binary (copy it into the build
  context as `./claude`; it is not committed).
- `agent.sh`: runs `crucible review` in its normal configuration (Opus review, tiered verification), plus the two
  changes the benchmark forces: `--offline` (there is no GitHub API in the container) and `--skip-checks` (the
  project's dependencies are not installed, so its lint/test commands cannot run). The PR title and body become
  `PR_DRAFT.md`. It also passes `--nits`: the verified non-blocking tier (batched mid-model verification, capped
  at `CRUCIBLE_NITS_MAX_USD`, default $0.75 per PR). With the budget set, a PR whose review spent at most half of it
  also gets the nit sweep, a nit-only second look at each pass (`CRUCIBLE_NITS_SWEEP_USD`, default $0.75;
  `CRUCIBLE_NITS_SWEEP=0` turns it off for an A/B), and the bug sweep before verification, a second look for blocking
  bugs the passes missed (`CRUCIBLE_BUG_SWEEP_USD`, default $0.60; `CRUCIBLE_BUG_SWEEP=0` turns it off).
- `CRUCIBLE_SEATS=2` (off by default; `agent.sh` passes the container's environment through, so set it with
  `-e CRUCIBLE_SEATS=2` on `try-agent.sh`, or with `ENV CRUCIBLE_SEATS=2` in a seat image's Dockerfile so the tag says
  what it runs) adds a second, independent review seat, with or without `--nits`:
  `CRUCIBLE_SEAT2_MODEL` (default `sonnet`), `CRUCIBLE_SEAT2_ORDER` (default `reversed`), `CRUCIBLE_SEAT2_SHARE`
  (default 0.30 of the budget). Its findings are unioned with the first seat's before verification, and it turns the
  bug sweep off unless `CRUCIBLE_BUG_SWEEP=1` (CHANGELOG 2026-11-25).
- `to_findings.py`: maps the kept, verified findings and nits in `review.json` to the contract, most severe first, uncapped
  (`RB_CONFIG_MAX_FINDINGS=N` caps it; the first run capped at 60). PR-text findings and findings
  without a line are left out.

`RB_CONFIG_KEEP_REVIEW=1` also leaves crucible's `review.json` next to `findings.json` (private runs: it is how
nits are told apart from findings when reading the judge's output).

A PR whose review hit an account spend or usage limit exits 3 (rerun it): findings are still written, but any
failure reason in review.json, or a line in the review log, that names a limit marks the run failed. A Fable 5.2 call
refused for a limit moves to Opus for that call alone (`model_fallbacks` in review.json) and doesn't fail the PR.
A review that failed, or reviewed no pass at all (a missing credential), exits 3 the same way.

Credential at run time: `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`). Configuration: `RB_CONFIG_BUDGET` (USD
per PR, default 5; was 8, which one PR hit), `RB_CONFIG_TIMEOUT` (seconds, default 3300).

```sh
cp "$(command -v claude)" bench/reviewbench/claude
docker build -t crucible-rb:dev bench/reviewbench
# then ReviewBench's scripts/try-agent.sh crucible-rb:dev -e CLAUDE_CODE_OAUTH_TOKEN
```

Results: eval/NOTES.md ("ReviewBench").
