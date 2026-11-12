# crucible on ReviewBench

Adapter for [ReviewBench](https://github.com/review-bench/ReviewBench) (its `AGENT_CONTRACT.md`): one PR in, one
findings file out.

- `Dockerfile`: python:3.13-slim + crucible from this repo + the Claude Code CLI binary (copy it into the build
  context as `./claude`; it is not committed).
- `agent.sh`: runs `crucible review` in its normal configuration (Opus review, tiered verification), plus the two
  changes the benchmark forces: `--offline` (there is no GitHub API in the container) and `--skip-checks` (the
  project's dependencies are not installed, so its lint/test commands cannot run). The PR title and body become
  `PR_DRAFT.md`. It also passes `--nits`: the verified non-blocking tier (batched mid-model verification, capped
  at `CRUCIBLE_NITS_MAX_USD`, default $0.75 per PR).
- `to_findings.py`: maps the kept, verified findings and nits in `review.json` to the contract, most severe first, uncapped
  (`RB_CONFIG_MAX_FINDINGS=N` caps it; the first run capped at 60). PR-text findings and findings
  without a line are left out.

`RB_CONFIG_KEEP_REVIEW=1` also leaves crucible's `review.json` next to `findings.json` (private runs: it is how
nits are told apart from findings when reading the judge's output).

Credential at run time: `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`). Configuration: `RB_CONFIG_BUDGET` (USD
per PR, default 5; was 8, which one PR hit), `RB_CONFIG_TIMEOUT` (seconds, default 3300).

```sh
cp "$(command -v claude)" bench/reviewbench/claude
docker build -t crucible-rb:dev bench/reviewbench
# then ReviewBench's scripts/try-agent.sh crucible-rb:dev -e CLAUDE_CODE_OAUTH_TOKEN
```

Results: eval/NOTES.md ("ReviewBench").
