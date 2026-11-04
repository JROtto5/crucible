# crucible

An independent, evidence-first AI code reviewer for your own branches. It's built for one job: making sure a change is *worth a maintainer's time* before you submit it upstream.

```
crucible review ~/src/three.js --base origin/dev   # scanners → reviewer → verification
crucible answer CR-82463d-02 fixed "use i < xs.length; added test"
crucible status                                     # GREEN / NOT_GREEN for this exact commit
crucible vote CR-82463d-03 down "logging is fine in examples/"
```

**How it works**
1. **Deterministic scanners first.** Secrets, merge markers and leftover debug statements are caught cheaply and with certainty.
2. **A reviewer on a different model than the author**, acting as a strict maintainer of *that* project. It reads the project's CONTRIBUTING rules and the full files around each hunk, not just the diff.
3. **Every finding is falsifiable**: severity, file:line, and a `wrong_if` test that would prove it false.
4. **A verification pass** tries to disprove every finding and drops the ones that fail. The dropped findings are listed, so you can see what got cut and why.
5. **Verdicts belong to one commit SHA.** A new commit needs a new review, so a stale GREEN is never reused.
6. **You answer every finding** (fixed / refuted / deferred). GREEN = nothing critical or important left open, and everything answered.
7. **It learns per project.** Down-votes and `crucible remember` lessons feed every future review of that repo.
8. **A human submits.** crucible never pushes, comments or approves.

Requires Python 3.10+, git, and the [Claude Code](https://claude.com/claude-code) CLI. `CRUCIBLE_REVIEW_MODEL` and `CRUCIBLE_VERIFY_MODEL` choose the models; `CRUCIBLE_CLAUDE_DIR` chooses which account pays for the calls.

MIT licensed.
