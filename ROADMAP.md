# crucible 1.0 checklist

Target: about 2027-01-04. 1.0 means a maintainer or a first-time contributor can install it, run it on a real PR and trust what it says.

## Precision, measured on real PRs
- [x] `crucible stats`: kept vs dropped-by-verification vs later fixed/deferred/refuted (from answers), per project and overall, deduped across rounds (2026-11-05: 59 upstream reviews, 195 unique model findings, 96 kept, 16 of 21 answered held up, 75 kept still unanswered). Next: count findings a maintainer later raised that crucible missed (recall on real PRs)
- [x] A labelled fixture eval (`crucible eval`, 16 cases) with recall / false-blocking / cost in the README (v0.3)
- [ ] A labelled set of at least 20 real merged upstream PRs replayed through `crucible review`, with precision and recall reported in the README
- [ ] Grow the fixture eval to 30+ cases, including multi-file changes and severity calibration (the refcount case is found but rated medium)
- [x] A rerun on a reviewed commit re-judges an edited draft or a moved base instead of reusing the verdict (real-use bug i, 2026-11-04)
- [x] (2026-11-05: absence findings carry an anchor and are re-verified when it changes, with the bug-l falsifier test; incremental summaries no longer repeat the earlier round) A carried finding is re-checked when the later changes touch the same file, not only its cited lines (2026-11-04: a "no test for X" finding carried with stale evidence after the test landed lower in the same file). Seen again 2026-11-04 21:xx: 3 fixed findings (one in README.md:34, edited twice) were carried through 3 rounds and had to be answered by hand. Seen a third time 2026-11-05 (bug l self-review): a "no test for the re-check guard" finding carried for 2 rounds after its test landed. Seen a fourth time 2026-11-05 (bug j self-review): an incremental round's summary repeated the previous round's "no CHANGELOG entry" and "strict decoding" text after both were fixed (findings were re-checked correctly; only the summary was stale) · BLAZE lesson 2026-11-05 (exchange): key the re-check on "has the code it points at changed since the round that raised it", not on round count; and judge a check by its latest run on the head only (a cancelled run with nothing newer is "not finished", not "failed"). · BLAZE 2026-11-05 note: an answered finding keeps its answer only while its anchor holds (FIXED: the whole enclosing block unchanged; REFUTED/ACCEPTED/DEFERRED: the flagged line unchanged and no new copy in the block). An absence finding ("no test for X") has no line to hash, so give it an explicit anchor: the file where the missing thing should live plus the code it is about, and re-check when either changes. Ship it with a falsifier test: the 11-05 bug-l case (test landed, finding must not carry).
- [ ] Every new gate or heuristic ships with its falsifiers next to it: the inputs it must still refuse (stays NOT_GREEN) and the old inputs it must still accept, plus the first three real inputs it would reject, checked by hand (BLAZE exchange 2026-11-05; same lesson as the 11-05 `\b` regression).
- [x] A verifier that answers in prose (rejected StructuredOutput) is transcribed, not left unverified; a transcription never drops a finding (real-use bug l, 2026-11-05)
- [ ] Each false-positive class seen in real reports gets a regression test (started: author notes counted as the PR body; template headings flagged as unusual; a check failing on an untracked scratch file, bug h; template comment/checklist/title counted as body length, bug g; a backticked build command not accepted as testing evidence, bug m; an owner-run repo's one-line self-merged PRs used as the length baseline for a contributor's body, 2026-11-06)
- [x] (2026-11-06: `python3 -m unittest|pytest` and `python3 -c` probes allowed for the verifier, no bytecode written; it was 5/149 Python findings executed vs 14/64 JS. Next: measure the executed share on the next week of real reviews) The verifier could only run `pytest` on Python repos (no `python3 -c` probes), so Python findings are verified by reading far more often than JS ones (seen in crucible's own reviews, 2026-11-04). Decide on a safe probe runner. Seen again 2026-11-05: in crucible's self-review of bug l, 4 verifiers tried `python3 -m unittest` (or a mutant copy) and were blocked by the approval gate, so every Python finding came back `by read`. Next: allow the project's own test runner (`python3 -m unittest`) and throwaway scripts in a temp dir
- [x] Prefer `Closes/Fixes #N` over a bare `#N` for "issue linked", and reject template placeholders (v0.3)
- [x] Surface an open PR that changes the same lines even when it links a different issue (real-use bug k, Heroic #5776; 2026-11-05). Next: measure how often it warns on real PRs (busy files in Heroic: 12 line-overlapping PRs, #5776 ranked first)
- [ ] Baseline, 2026-11-04 (5 reports, 3 projects): 18 kept, 12 dropped by verification, 1 kept finding later refuted by the author
- [x] Cost routing by change type behind `--route`, gated by an offline replay of stored reviews (`crucible routing-replay`; 2026-11-05). Docs-only rounds get one cheaper pass. Lows-on-the-cheap-tier failed the bar (4 real lows lost on 57 upstream reviews, one fixed by the author), so it wasn't built
- [x] (2026-11-06: done; the old commit must still exist and share a changed file with HEAD; stubbed amend two-round test; on the real clones 16 of 40 past amend re-reviews were eligible, with deltas of 254 changed lines vs 1,045 in full. Next: measure the saving on the next week of real reviews with `routing-replay`) Incremental re-review across amended commits: 38 of 57 upstream reviews (67% of spend) were full re-reviews because the previous reviewed commit isn't an ancestor after `git commit --amend`. With the same merge-base, `git diff prev..HEAD` is still the change between rounds; require the old commit to exist, and prove it on a stubbed two-round amend test plus a replayed real pair

## Quickstart and docs
- [x] `pip install`-able package with a `crucible` entry point (no hand-written shim): `pipx install git+https://github.com/JROtto5/crucible` (2026-11-05). Next: tag a release so the quickstart can pin `@v0.4.0`
- [ ] Five-minute quickstart from clone to first report
- [x] CONTRIBUTING.md (setup, what a change needs, safe defaults) and issue templates for a wrong finding, a missed issue and a bug (2026-11-05)
- [ ] Docs page for each command, including the `PR_DRAFT.md` layout
- [ ] A worked example report from a public PR

## Demo
- [ ] Recorded terminal demo (review → answer → GREEN) on a public repo

## Clean code
- [x] Tests for `review.run_review` with a stubbed model (no network): two-round incremental test (v0.3)
- [ ] Stubbed tests for `evalrun.write_results` (NOTES.md splice, history columns)
- [x] Lint (ruff) clean and run in CI: pyflakes + syntax rules, config in pyproject.toml (2026-11-05)
- [x] CI on GitHub Actions for the unit tests (v0.3)

## Safe defaults
- [x] Never posts, never pushes upstream, never approves (drafts only)
- [x] Model calls isolated from the project's `.claude/` settings and the user's MCP servers
- [x] Budget cap that leaves the review incomplete rather than GREEN
- [ ] A test asserting that no command path calls `gh` with a write verb
