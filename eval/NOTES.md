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

## 2026-11-10 · prompt caching off for tool-less calls (BLAZE 11-10 technique), A/B

Every model call site (code read): tool loops, which re-read their prompt on every turn and keep caching: the review
pass (review.py `run_review`), verification (both tiers, `TOOLS_RUN`), `polish`, `prep` and `reply` (`TOOLS_READ`).
**Three tool-less call sites**, one request each, nothing re-reads their prompt: `learn` rules (learn.py, Sonnet,
up to ~19k tokens), `learn` style conventions (style.py, Sonnet, up to ~4.5k tokens), and verdict salvage (review.py
`salvage_verdict`, Haiku). Before this commit all three ran with the CLI's default caching (1-hour TTL, writes at 2x input).

Probe (Haiku, one 8.6k-token prompt, `--tools ""` + `--json-schema`): cached, it wrote 8,615 tokens and read 0,
$0.00179. Uncached: 8,617 input, $0.00092 (−49%). Three back-to-back cached calls with different prompts read a
shared 3,183-token CLI system prefix and wrote the rest. So caching pays only when that prefix is warm and the
unique part is under ~2.9k tokens (cached = 0.1R + 2W vs uncached R + W).

A/B on 5 paired real inputs: the actual `salvage_verdict` on verifier actions + evidence from the newest stored upstream
reviews (702-2,674 chars), each run cached then uncached. Verdicts identical 5/5 (same keep, same schema keys). First
call (cold prefix) $0.0012 → $0.0007 (−42%); the next four (prefix warm from the call before) $0.0006-0.0009 →
$0.0007-0.0008 (+0 to +33%); total $0.0040 → $0.0038 (−5%). A burst like this is the worst case for uncached, and it
doesn't happen in practice: salvage ran in 0 of 304 stored reviews, so a real salvage call is a lone cold one (−42%).
The `learn` calls are larger and cold (one per learn run), past the break-even on both counts.

Decision: tool-less calls run with `DISABLE_PROMPT_CACHING=1` (`CRUCIBLE_NO_TOOLS_CACHE=1` restores caching for an
A/B). The review pipeline's cost doesn't move (its only tool-less call is salvage, which no stored review used). The
saving is on `learn`: by the token math, about half of the two Sonnet calls' input $. Spend for this note: $0.009.

## 2026-11-09 · cache write vs read $ per call kind ($0 baseline for the no-tools caching A/B)

From the 23 metered review.json files since 003b1a2 with no unmetered call and no cache hit (10 upstream Lutris rounds,
13 crucible self-reviews). No model calls. review.json had tokens by model, split only into review passes and
"everything else", so the call kinds below are inferred from the model: the cheap verifier tier and salvage both run
on Haiku and cannot be told apart. **The no-tools slice (salvage) is not split by call kind in these reviews**;
`tokens_by_kind` (this commit) records it from now on. $ is priced from the token counts (Opus 5.5 $4/$20, read $0.20;
Sonnet 5.5 $2/$10, read $0.20; Haiku 5.5 $0.10/$0.50, read assumed $0.01) with cache writes at 2x input (the 1-hour
rate): that lands at 1.00-1.17x each review's recorded cost_usd (median 1.05); 1.25x (5-minute) lands at 0.75-0.96x.
So shares are approximate; the per-kind $ in `tokens_by_kind` is the CLI's own figure and replaces this.

| call kind (upstream, n=10) | $ | cache write | cache read | output |
|---|---|---|---|---|
| review pass (Opus) | 4.87 | 2.53 (52%) | 0.60 (12%) | 1.74 (36%) |
| verify cheap tier + salvage (Haiku) | 0.95 | 0.32 (34%) | 0.23 (24%) | 0.40 (42%) |
| verify full tier (Sonnet) | 1.29 | 0.63 (49%) | 0.30 (24%) | 0.36 (28%) |

| call kind (own, n=13) | $ | cache write | cache read | output |
|---|---|---|---|---|
| review pass (Sonnet) | 2.05 | 1.25 (61%) | 0.40 (19%) | 0.40 (20%) |
| verify cheap tier + salvage (Haiku) | 0.46 | 0.20 (42%) | 0.11 (25%) | 0.15 (33%) |
| verify full tier (Opus) | 3.25 | 1.86 (57%) | 0.50 (15%) | 0.89 (28%) |

Read: cache writes are the largest line in every kind (34-61% of $), but every kind here is a tool loop that re-reads
its writes (the upstream review pass read 8x the tokens it wrote), so turning caching off there would price those
reads at full input. The BLAZE technique only fits one-turn calls with no tools: in a review that is salvage alone
(learn/style/polish run outside reviews). Next (commitment due 11-11 07:00): read salvage's own write/read split from
`tokens_by_kind` once metered reviews have it, and A/B `DISABLE_PROMPT_CACHING=1` on the no-tools calls only.

## 2026-11-09 · two verifier votes (`anchor-replay --votes 2`), first run

`crucible anchor-replay --clones ~/dev/oss-grind/work --votes 2 --jobs 3 --budget 10`, all answered code findings (69; 21 skipped as PR-draft findings). The $10 cap ran out ($4.75 + $5.25), so 30 findings were left out of both arms; 39 paired (15 refuted, 24 fixed/deferred).

Today's prompt (no reviewer argument), one vote vs two votes on the same 39:
- false alarms kept: 6/15 → 5/15 (one dropped)
- real findings dropped: 3/24 → 3/24 (none lost)
- votes split on 4/39; cost 2× the verifier calls

With the reviewer argument added (anchoring arm): false alarms kept 10/15 → 9/15, real dropped 4/24 → 5/24 (two votes lost one real finding). The argument arm again keeps more false alarms (9 vs 5), as on 11-07.

Verdict: not shipped to the review path. The ship rule (no fixed/deferred finding lost) holds on today's prompt, but the gain is one false alarm out of 15 for double the verifier cost, with n=39 paired, under the n≥60 bar for quoting a rate. Next: rerun with a cap that covers all 48 replayable findings (~$18) only if a cheaper verifier tier makes the second vote affordable; otherwise drop the idea.

- **2026-11-10, Sonnet as reviewer (the arm the upstream lane really runs; johnr's 11-09 "Opus vs current pick, cost per finding" ask).** Our upstream PRs are Opus-written, so the different-model rule makes Sonnet 5.5 review them, and the 11-09 table had no Sonnet-review arm. Same 20 cases, 2 runs pooled, `--review-model claude-sonnet-5-5`, default verify tiers, `--jobs 3`, not written to history.

| arm | blocking recall (pooled) | false blocking on clean | true findings dropped | $ per set | $ per caught bug | wall per set |
|---|---|---|---|---|---|---|
| Sonnet 5.5 review (upstream lane today) | 27/28 [82%, 99%] | 0/12 [0%, 24%] | 7 | $4.83 | $0.36 | 18.0 min |
| (11-09) current pick, Opus 5.5 review | 26/28 [77%, 98%] | 0/12 | 4 | $4.20 | $0.32 | 19.7 min |
| (11-09) Opus 5.5 review + verify | 27/28 [82%, 99%] | 0/12 | 6 | $8.29 | $0.61 | 13.4 min |

  Sonnet missed js-refcount once (r2), the same known medium-severity case the Opus pick missed on 11-09; every bug was found at some severity in both runs. All recall intervals overlap: at n=28 the eval can't tell Sonnet and Opus reviewers apart, and cost per caught bug is within 15%. Decision: no reviewer change from the eval. What the eval can't test is the reason for the different-model rule (Opus reviewing Opus-written code), because the cases aren't Opus-written; that part still needs the paired upstream replay (11-11 item).
