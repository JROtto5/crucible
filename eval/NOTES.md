## Notes on the runs below

- **2026-11-04, fixtures.** After the first two runs, crucible's self-review found two fixture mistakes: py-pagination's label pointed one line past the file, and py-test-deleted's deleted test didn't tell round from floor. Both were fixed, and the two cases were re-run with tiered verification. Both were caught, so the rows stand.
- **2026-11-04, scoring.** The first two runs were scored with a looser rule (±3 lines or a keyword). Re-scoring the tiered run's kept findings with the current rule (labelled file AND a root-cause keyword or the labelled line ±1) gives the same 11/12. Each credited finding names the planted bug:

| case | credited blocking finding |
|---|---|
| js-missing-await | writeFile is no longer awaited; save() resolves before… |
| js-null-edge | displayName crashes for guests (user.profile undefined) |
| js-off-by-one | Off-by-one loop bound makes mean() always return NaN |
| js-shell-injection | Shell command injection through the upload name in makeThumb |
| js-timeout-units | The new seconds value goes to setTimeout without conversion… |
| py-pagination | Off-by-one: each page has size-1 items… |
| py-race | Lock removal makes incr() lose updates under concurrency |
| py-secret | Possible secret in added line (scanner) |
| py-sql-injection | SQL injection: user input is pasted into the query with an f-string |
| py-test-deleted | Floor division changes nearest-cent rounding to truncation |
| ts-api-break | Swapping the parameters of the public formatDate breaks callers |
| js-refcount | (missed at blocking severity: found, rated medium) |

- **2026-11-07, held-out split.** Cases now carry `split: build|holdout` (default build). All 16 earlier cases are build cases: prompts and the verifier were tuned while watching them. Held-out cases come from real catches and are frozen: a prompt change is never justified by one, and a held-out miss is fixed by adding a build case of the same shape. First two: `py-fix-reintroduces-hang` (gamescope #2516 round 2, rewritten in Python: the shutdown fix calls `JobSet.clear()`, whose `Job.close()` joins without a bound, before its new bounded wait; the change's own tests pass, a stuck job still hangs `shutdown(timeout=0.2)`) and its clean twin `clean-py-bounded-shutdown` (bounded wait first, then forget only finished jobs). First run (`--split holdout`, not written): caught at blocking severity, 0 false blocking on the twin, $1.07. Second run, recorded in history.jsonl as the baseline: caught again, 0 false blocking, 1 true finding dropped by verification (another finding on the same bug was kept), $0.65. Two cases are too few to read a percentage from.

- **2026-11-09, held-out pair 2: a test that cleans its input before asserting.** `py-test-sanitizes-input` (Lutris #7006 round 1 shape, written from scratch in Python): the change fixes one French string, adds a link to another with an unclosed `href` quote, and adds a test that strips `<a>` tags with a regex before parsing, so its 9 tests pass while `to_label()` renders the linked string empty. The clean twin `clean-py-markup-test` closes the quote and parses each string as shipped. First run (`--cases`, not written): caught, 0 false blocking on the twin, 0 true dropped, $0.38 for the pair. Four held-out cases are still too few for a rate.

- **2026-11-09, three-arm model comparison (asked by BLAZE 2 for Fable 5.2's release; not written to history).** All 20 cases (14 bug, 6 clean), 2 runs per arm pooled, `--jobs 3`, Claude Code 2.1.321 (needed for `claude-fable-5-2`). $ is the CLI's `total_cost_usd`.

| arm | blocking recall (pooled) | false blocking on clean | true findings dropped | $ per set | $ per caught bug | wall per set |
|---|---|---|---|---|---|---|
| current pick (Opus 5.5 review, Haiku→Sonnet verify) | 26/28 [77%, 98%] | 0/12 [0%, 24%] | 4 | $4.20 | $0.32 | 19.7 min |
| Opus 5.5 review + verify | 27/28 [82%, 99%] | 0/12 | 6 | $8.29 | $0.61 | 13.4 min |
| Fable 5.2 review + verify | 28/28 [88%, 100%] | 0/12 | 7 | $23.21 | $1.66 | 28.6 min |

  Misses: current missed py-race (r1) and js-refcount (r2, the known medium-severity case); Opus missed py-race once (r2). Every arm found every bug at some severity. The recall intervals all overlap, so n=28 can't separate the arms. Cost can: Fable 5.2 costs 2.8× Opus and 5.5× the current pick per set, and it's slowest. Every bug case cost $0.94–$3.67 on Fable 5.2 vs $0.28–$0.94 on Opus, so this isn't one outlier. Decision: no reviewer change on this evidence. Fable 5.2 would only be worth it if a larger set showed a recall gain big enough to pay ~$1.05 more per caught bug than Opus.
