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

## 2026-11-11 · base-moved split, first slice: 13 three-mesh-bvh rounds (stored readiness data, $0)

Each round's `base branch hasn't moved under the change` item, as recorded in its review.json at review time
(~/.crucible/reviews/gkjohnson__three-mesh-bvh/<sha>/review.json). No re-run and no fetch.

| bucket | rounds | round ids (head sha) |
|---|---|---|
| moved + overlap (warn) | **0** | none |
| moved elsewhere (10 commits on master since 72ad37c590, tip a01c8c2c66, none in touched files) | 5 | f057e83f87 b2d7ed6a54 cb686bdfc1 a237596a79 0e27014694 |
| unchanged (master still at merge-base 402c66449f) | 4 | 29e83f4dd4 52c9dd3bff ddd6a40995 19f40902b0 |
| unreachable / na (base is a local SHA 52c9dd3bff: incremental re-review, not a remote-tracking ref) | 4 | 7a144c3e95 31301d8a3e 6773c8faf5 8269eaf240 |

So 0 of 13 rounds were judged against a base that had moved in their own files, and no finding could have changed
after a rebase. The "na" bucket is a blind spot: a re-review against the previous round's head never checks
upstream. The 11-13 week-wide split still needs the other projects' rounds.

## 2026-11-11 · base-moved split, second slice: every other project's round since 11-06 (stored readiness data, $0)

Same method as the first slice: the `base branch hasn't moved under the change` item in each
~/.crucible/reviews/<project>/<sha>/review.json with `started` >= 2026-11-06. 240 rounds; 144 are crucible
reviewing its own repo, so they're listed apart from the 96 upstream rounds.

| bucket | upstream rounds | round ids / projects | crucible self-review |
|---|---|---|---|
| moved + overlap (warn) | **3** | pyinfra 4c9f7cf0a4, 5c62b86344, 8ad9760932 (11-11 11:08-11:37; 276 commits on 3.x, 5 in touched files) | 0 |
| moved elsewhere | 1 | lutris 03ff8a7874 | 0 |
| unchanged | 11 | colyseus/schema 10, maplibre-gl-js 1 | 11 |
| na (base not a remote-tracking ref) | 4 | lutris 2, maplibre-gl-js 2 | 40 |
| not recorded (round predates the item) | 77 | supavisor 22, lutris 26, gamescope 9, MangoHud 6, Heroic 5, colyseus 5, three.js 2, phaser 1, supabase 1 | 93 |

Week total with the first slice: 3 moved+overlap (all pyinfra), 6 moved elsewhere, 15 unchanged, 8 na, 77 not recorded
(upstream only). Still open for the 11-13 note: whether any of the 3 pyinfra rounds changed a finding after a rebase
(needs a re-run on the rebased head, not $0).

## 2026-11-11 · incremental re-review prompt (DRG-63): one amended round replayed before/after

`crucible eval` only builds full reviews and `model-replay` skips incremental rounds, so neither can measure the
re-review prompt. One stored amended round was replayed by hand instead: colyseus #1000 round 2 (8a6c1d4c, previous
round 63e3b63c, base 18ccca0e), in a `--shared` clone on a branch whose recorded history is the round-1 commit, each
arm with its own CRUCIBLE_HOME holding only the round-1 review and the learned project files, `--offline --no-exec
--budget 1.5`, same models (Opus review, tiered verify). Outputs: ~/.crucible/replays/drg63-colyseus-1000-r2/.

| arm | code | $ | review tokens | summary on the pass | kept |
|---|---|---|---|---|---|
| before | 12206e8 | $0.48 | 280k | "The diff supplied for this pass doesn't match it" (then reviewed base..HEAD by hand) | 3: raw error text (carried), CHANGELOG (carried), stale comment (new) |
| after, label only | 046ebb0 | $0.35 | 156k | "This round reverts one change from the previous round" | 1: CHANGELOG; raw error text dropped by the carried-finding re-check |
| after, + re-check scope | 68e3da8 | $0.23 | – | "The inter-diff puts reserveMultipleSeatsFor back to exactly its base code" | 2: raw error text, CHANGELOG (both carried) |

- The label fixes the misreading in both new arms. The middle arm exposed the same confusion in the verifier: its
  re-check dropped the raw-error finding as "byte-identical at 63e3b63c44 and HEAD, so not caused by it", though
  round 1's commit added that line. 68e3da8 scopes both re-check prompts to base..HEAD, and the finding is kept again.
- What the new prompt gives up: the old arm's "stale comment" low sits in a hunk round 1 already had (the stored
  round raised it too, unanswered). The old arm found it only by ignoring the diff it was given and re-reviewing
  everything. The new prompt keeps to the inter-diff, so a round-1 miss in an untouched hunk waits for `--full`.
- n = 1 round, one sample per arm (the verifier isn't deterministic): a check that the symptom is gone, not a rate.
  Spend $1.06.

## 2026-11-10 · reviewer A/B, second slice: 10 paired upstream rounds (`crucible model-replay`)

Run: `crucible model-replay --clones ~/dev/oss-grind/work --rounds 6 --budget 0.8 --exclude e72b878703 7b25a717ea
63e3b63c44 2d6a660a8b 8e51962df9` at 938029a's code (raw output ~/.crucible/replays/model-2026-11-10c.txt). The
first slice's 5 rounds are excluded, and the next newest round of each project is taken: colyseus/schema 95303fd7f8,
three-mesh-bvh ce21827c59, supavisor 30e50d14b0, umu 0f4b8eeb4d, MangoHud 56f729da0b. Lutris 5f4d6fa0af was left
out twice: Opus's review came back incomplete (a chunk failed) both times. Same setup as the first slice (read-only,
--no-exec, tiers on, Opus → Sonnet verify, Sonnet → Opus verify). The first try was stopped at a 10-minute
background limit after 2 rounds. Those 4 arms were kept (a913f38's arm cache) and reused, so the restart paid only
for the rest. Labels: 4 held up, 2 refuted, all raised by Opus in the stored rounds.

| arm | slice 2 held kept | slice 2 false alarms kept | 10 pairs held kept (matcher) | by hand | false alarms kept | $ (10 pairs) | $ / held kept |
|---|---|---|---|---|---|---|---|
| Opus review | 3/4 (4/4 by hand) | 0/2 | 9/11 (Wilson 52–95%) | 10/11 (62–98%) | 1/5 | $5.66 | $0.63 |
| Sonnet review | 2/4 | 0/2 | 5/11 (21–72%) | 6/11 (28–79%) | 2/5 | $4.95 | $0.99 |

- By hand, slice 2: Opus's `cpu_win32.cpp:17` "Windows UpdateCPUData never sets max_core_load, so the option always
  shows 0%" is the labelled held-up "Option shows a constant 0% on Windows" (cited in `hud_elements.cpp`, so the
  matcher can't pair a finding across files). Sonnet's two misses (colyseus/schema's faked-emit test, MangoHud's
  duplicated LOAD_DATA block) are real misses.
- **Unlabelled kept findings, judged by evidence where any exists (6 of 15):**
  - held up, both arms (2): "only the root state is checked; nested children can still shadow accessors"
    (schema Encoder.ts:263/265). The same class was deferred with a measured answer in the later round (assert.ts:68).
  - false alarm, both arms (2 Opus, 1 Sonnet): "default changed with no CHANGELOG entry" (bvh :173 / :72) and
    "API.md not regenerated" (bvh :10, Opus). The author refuted this class twice with evidence: gkjohnson writes the
    CHANGELOG and regenerates API.md himself after merging (f0b97634, aef5a71b).
  - **not judged (9)**: no later answer covers them, and judging them needs a repro on each PR. Opus: the
    SWC/Babel wording of the schema error, the bvh index write-back when the geometry changed mid-build, the bvh
    indirect-branch test gap, MangoHud's unlabelled second percentage. Sonnet: the schema comment split from its line,
    the bvh write-back throwing inside onmessage, the normalized copy vs transfer paths in BufferUtils, supavisor's
    redundant struct guards, and the get_secrets-only test. Both arms raised the MangoHud percentage label and the
    bvh write-back (as two framings).
- **2026-11-11, 4 more judged by code read at each PR head ($0; `git show <head>:<file>` in the lane clones),
  covering 5 of the 9:**
  - held up, both arms: the bvh index write-back (Sonnet :132 "can throw inside onmessage", Opus :131 "assumes the
    geometry wasn't changed during the build"). At ce21827c59, `geometry.index.array.set( serialized.index )` runs
    inside `worker.onmessage`, which is set inside the Promise executor, so a throw there is not a rejection: the
    promise never settles and `WorkerBase.running` stays true. Reachable only if the caller resizes or replaces the
    index mid-build, which copy-by-default newly allows. Real, but an edge case (low is right).
  - held up, Sonnet: the schema comment split (Encoder.ts:266). At 95303fd7f8 `assertAccessorsNotShadowed(state)`
    sits between the "Use .cache() here ..." comment and the `TypeContext.cache(...)` line it explains.
  - held up, Sonnet: supavisor's redundant guards (secret_checker.ex:170). At 30e50d14b0 `fetch_user_secret/3` is
    specced and implemented to return only `{:ok, %SASLSecrets{}}` on success, so the `%SASLSecrets{}` match on
    `fresh` and in `scram_key/1` can't fail, and the trailing `:ok` is discarded at the only call site (:132). The
    finding's "maintainers have asked to drop such guards" is unsourced; the code claim holds. A style nit.
  - held up as stated, Opus: MangoHud's second bare percentage (hud_elements.cpp:464). At 56f729da0b the max-core
    value is drawn as `%d` + `%` with no marker, unlike the MHz/°C/W columns. Whether a marker is wanted is the
    maintainer's call; no answer exists.
  - Still not judged (4) at 02:52: the SWC/Babel error wording and the indirect-branch test gap (Opus), the
    BufferUtils normalized copy-vs-transfer paths and the get_secrets-only test (Sonnet). Judged 2026-11-11 12:xx
    below.
  - Effect on the tally: 11 of the 15 unlabelled kept findings are now judged (cpu_win32 counted as the labelled
    one it matches). Opus: 3 held (root-only check, write-back, MangoHud %), 2 false alarms (CHANGELOG, API.md),
    2 unjudged. Sonnet: 4 held (root-only check, write-back, comment split, guards), 1 false alarm (CHANGELOG),
    2 unjudged. Sonnet's extra catches are two low style nits, against Opus's lead of 4 on labelled held-up
    findings (10/11 vs 6/11), so the decision (Opus stays) doesn't change.
- **2026-11-11 12:xx, the last 4 judged by code read at each PR head ($0), so 15/15 unlabelled kept findings are judged:**
  - held up, Opus: the SWC/Babel wording (Encoder.ts:30 at 95303fd7f8). The error tells everyone to set
    `"useDefineForClassFields": false` "in your tsconfig.json"; SWC (`jsc.transform.useDefineForClassFields`) and
    Babel's class-properties plugin emit the same own data properties and are configured elsewhere, so for those users
    the fix text points at the wrong file. A low wording issue; the README also only documents the tsconfig route.
  - held up, Opus: the indirect-branch test gap (GenerateMeshBVHWorker.js:130, test/Workers.test.js:197-203). The
    copy path's `else if ( ! bvh.indirect )` skips the index write-back for indirect BVHs, and no matrix in
    Workers.test.js passes `indirect` (copyMatrix is parallel/interleaved/indexed/transferBuffers/strategy), so the
    indirect + copy combination is never run. The "non-CENTER strategies untested" half is true but weaker: the
    copy/transfer code doesn't depend on strategy.
  - held up, Sonnet: copy vs transfer disagree for normalized attributes (BufferUtils.js:44,
    GenerateMeshBVHWorker.js:163-171). `copyAttributeArray` de-normalizes to Float32, but with
    `transferBuffers: true` a non-interleaved normalized position is sent as its raw integer array and the worker
    wraps it as `BufferAttribute( position, 3, false )` (generateMeshBVH.worker.js:36), so the BVH is built at the
    integer scale. The transfer path behaves as on master (pre-existing), but the PR made the two paths disagree, and
    the normalized test matrix only runs interleaved, where transfer falls back to copy.
  - false alarm, Sonnet: "tests cover only the get_secrets call, with a SASLSecrets upstream"
    (secret_checker_test.exs:167). True as stated, but nothing untested behaves differently: the periodic
    `handle_info(:check)` path (secret_checker.ex:104) runs the same `check_secrets/2` that calls
    `drop_stale_upstream_secrets`, and a non-SASLSecrets upstream falls through the `with` (secret_checker.ex:171)
    to the no-op `:ok`.
  - Final unlabelled tally (15): Opus 5 held (root-only check, write-back, MangoHud %, SWC wording, indirect test
    gap) / 2 false alarms (CHANGELOG, API.md); Sonnet 5 held (root-only check, write-back, comment split, guards,
    normalized paths) / 2 false alarms (CHANGELOG, get_secrets-only test). Even on the unlabelled findings, where the
    labels can't favour Opus, the arms tie 5–5; with the labelled held-up findings (Opus 10/11, Sonnet 6/11) the
    10-pair totals are Opus 15 held kept / 3 false alarms kept (1 labelled + 2), Sonnet 11 / 4 (2 + 2). The decision
    (Opus stays the upstream reviewer) doesn't change. n is still small (26 held-up findings in all).
- Among the first 6 judged unlabelled findings each arm had exactly one extra held-up finding, the same one (the
  root-only check). With the 11-11 judgements Sonnet has two Sonnet-only held-up findings (the comment split and the
  supavisor guards), both low style nits, so the label bias did hide two small Sonnet catches; Opus's lead on
  labelled held-up findings (10/11 vs 6/11) is unaffected.
- Over 10 pairs, Opus keeps more held-up findings, 10/11 vs 6/11 by hand. The intervals still overlap at n=11, but
  every slice points the same way, and Opus's $ per held-up finding is lower ($0.63 vs $0.99) even though Sonnet's
  rounds cost less ($0.50 vs $0.57 per round).
- Decision: no change. Opus stays the upstream reviewer. Revisit at ≥20 pairs (the cache makes that +10 rounds, not 20).
- Spend: $3.32 for the restart (6 new arms plus the failed Lutris one) + $2.48 for the 4 kept arms of the stopped
  first try. The stopped try's Lutris arm and its unfinished supavisor arm are not metered (killed before review.json
  was read), at most $1.60 at the $0.80 cap. Total ≤ $7.40, within the ≤$8 commitment.

## 2026-11-10 · the 5 reviewer-replay pairs by change shape (ARMOR routing ask, $0)

The 5 pairs above, re-bucketed with `model-replay`'s new by-shape breakdown (`modelreplay.shape`: kind by production
files, i.e. outside tests and docs; size by production lines added + deleted, merge-base..head). Computed from the
stored per-round lines plus `git diff --numstat` on the local clones (no model calls). 4 non-empty
buckets of 6 possible (2 kinds × 3 sizes, each dimension on its own).

| bucket | rounds | Opus held kept | Opus false alarms kept | Opus $ / held kept | Sonnet held kept | Sonnet false alarms kept | Sonnet $ / held kept |
|---|---|---|---|---|---|---|---|
| multi-file | 3 (bvh 197, Lutris 29, supavisor 48 lines) | 6/7 | 0/0 | $1.87 / $0.31 | 3/7 | 0/0 | $1.99 / $0.66 |
| single-file | 2 (colyseus 6, MangoHud 9 lines) | 0/0 | 1/3 | $0.98 / n/a | 0/0 | 2/3 | $0.94 / n/a |
| ≤50 production lines | 4 | 4/5 | 1/3 | $1.96 / $0.49 | 3/5 | 2/3 | $2.06 / $0.69 |
| 51–200 production lines | 1 (bvh) | 2/2 | 0/0 | $0.89 / $0.45 | 0/2 | 0/0 | $0.87 / n/a |

- **Every cell is too few to quote** (n = 2 to 8 labelled findings; the bar is 60).
- No docs/PR-text round is in the sample, and none can be: `model-replay` only takes rounds with an answered code
  finding. The docs-only routing rule is judged by `routing-replay`, not here.
- What the shape says, with that caveat: both single-file rounds had only false alarms to find (Sonnet re-raised
  2 of 3, Opus 1 of 3), and every held-up finding was on a multi-file change, where Opus kept 6/7 to Sonnet's 3/7.
  Nothing here argues for routing small code changes to Sonnet. No routing change.
- Spend: $0.

## 2026-11-10 · reviewer A/B on our upstream PRs: Opus vs Sonnet (`crucible model-replay`, first slice)

Premise correction: the commitment said our upstream rounds ran with "the current Sonnet pick". They didn't. All
174 stored upstream rounds were reviewed by Opus: our upstream commits carry no AI trailer (RULES 6), so crucible
never knows Opus wrote them and the different-model rule picks Opus. Sonnet is what the rule *would* pick if it knew.
So the arms are Opus (today's upstream reviewer) vs Sonnet (the author-aware pick), each with the verifier `review`
pairs with it (Opus → Sonnet verify, Sonnet → Opus verify), tiers on.

Run: `crucible model-replay --clones ~/dev/oss-grind/work --rounds 5 --budget 0.8` at 5540690 (raw output
~/.crucible/replays/model-2026-11-10.txt). 5 paired rounds (three-mesh-bvh, Lutris, colyseus, supavisor, MangoHud),
the newest labelled full round of each project. Read-only verification (--no-exec) in both arms. Labels: 7 held up
(fixed/deferred), 3 refuted, all raised by Opus in the stored round, so recall favours Opus by construction.

| arm | held up kept | false alarms kept | kept code findings (unlabelled) | $ | tokens | $ / held-up kept |
|---|---|---|---|---|---|---|
| Opus review | 6/7 (Wilson 49–97%) | 1/3 | 17 (10) | $2.84 | 5.16M | $0.47 |
| Sonnet review | 3/7 (16–75%); 4/7 by hand | 2/3 | 14 (9) | $2.94 | 6.42M | $0.98 |

- By hand: Sonnet's bvh `GenerateMeshBVHWorker.js:78` "no changelog entry, regenerated API.md" covers the labelled
  "API.md not regenerated" (cited at line 8, 70 lines away, so the matcher can't pair them). Its other two misses are
  real: the SharedArrayBuffer copy path (bvh) and the prefix outside `game.directory` (Lutris, fixed upstream).
- Both arms hit the $0.80 budget on the bvh round (verification cut short, rest kept unverified); the other 4 are
  complete.
- Unlabelled kept findings look alike in kind: mostly test-gap / docs lows, plus one medium each on supavisor's
  rolling-upgrade message compatibility (both arms found it, cited at different lines).
- n is far too small to quote (7 held-up labels, 3 refuted). It points one way, though: Sonnet is not cheaper per
  round here ($0.59 vs $0.57; the Opus verifier costs more than the Sonnet one) and kept fewer held-up findings.
- Decision: no change. Opus stays the upstream reviewer (already the default, and johnr's 11-09 call). Revisit
  when ≥20 paired rounds exist; the eval arm (0d50436) also couldn't tell them apart at n=28.
- Spend: $5.78 for the 10 arms.

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
- **2026-11-10, Fable 5.2 as reviewer (BLAZE exchange: their #223 found Fable 5.2 raised more of BrianC's misses at 2.3x cost).** Same 20 cases, 2 runs pooled, `--review-model claude-fable-5-2`, default verify tiers, `--jobs 3`, not written to history.

| reviewer | recall (blocking sev) | false blocking | true dropped | $/set | $/caught bug | wall/set |
|---|---|---|---|---|---|---|
| Fable 5.2 review | 27/28 [82%, 99%] | 0/12 [0%, 24%] | 4 | $5.29 | $0.39 | 28.0 min |

  Fable 5.2 missed py-pagination once at blocking severity (r1); every bug was found at some severity in both runs (28/28). Same recall as Sonnet (27/28) and within the Opus pick's interval (26/28); cost per caught bug is 9% above Sonnet and 22% above the Opus pick, wall time ~1.5x. Unlike BLAZE's 2.3x, the cost gap here is small, likely because the eval diffs are small (fewer findings to verify). Decision: no change; Sonnet stays for Opus-written PRs. The eval cases are all small single-bug diffs, so this says nothing about bigger PRs.

## 2026-11-11 · ReviewBench test set, private offline run (johnr: "as good as OhMyBug but effective")

[ReviewBench](https://github.com/review-bench/ReviewBench) (GitHub's open benchmark for AI reviewers) scores findings
against a human-validated golden set with an LLM judge (Claude Sonnet 5, the leaderboard's judge). This run is
**private and offline**: its own README says offline results "cannot be published on the leaderboard". Nothing was
submitted.

Setup: adapter in `bench/reviewbench/` (1fc53ec). crucible at main in a container on blaze-3, normal configuration
(Opus review, tiered verification) plus the two changes the container forces: `--offline` (no GitHub API) and
`--skip-checks` (dependencies not installed). Per-PR budget $8, timeout 55 min. Test set: their 25 PRs, 352 golden TPs.
One round (the leaderboard averages 3). Judge: `npm run judge --provider anthropic --model claude-sonnet-5`.

| | crucible (normal) |
|---|---|
| grounded recall (micro) | 32.7% (115/352, 95% Wilson [28.0, 37.7]) |
| grounded precision (macro) | 85.7% |
| augmented recall / precision (macro) | 46.8% / 84.0% |
| augmented F1 (macro, computed) | 60.1 |
| findings per PR | 11.7 (292 over 25) |
| $ per PR (CLI `total_cost_usd`, list price) | mean $1.97, median $1.15, max $8.04; $49.22 for the 25 |
| wall time per PR | mean 540 s, median 285 s, max 2,297 s |

By severity (grounded recall): high 54.0%, medium 35.2%, low 27.2%. Weakest categories (grounded recall):
api-architecture 12.5% (12 golden), documentation 20.8% (21), security 21.2% (27, grounded precision 42.9%);
accessibility 27.8% (10). Best: reliability 37.6%, testing 36.4%, maintainability 35.4%, correctness 35.1%.

Published leaderboard (official, full 219-PR set, 3 rounds, review-bench.ai/api/leaderboard on 11-11; it publishes no
$ per PR):

| reviewer | grounded P / R | augmented P / R | aug F1 | s / PR | comments / PR |
|---|---|---|---|---|---|
| #1 OhMyBug | 81.7 / 60.2 | 92.4 / 85.3 | 88.7 | 322 | 37.1 |
| #2 diffox ultra | 78.3 / 53.5 | 81.6 / 75.5 | 78.4 | 87 | 20.1 |
| #3 intent-review-agent | 81.8 / 50.7 | 87.7 / 74.8 | 80.7 | 213 | 17.6 |
| #5 Laude RevEngine (Claude) | 83.6 / 46.3 | 90.8 / 64.5 | 75.4 | 182 | 11.4 |
| #6 block/review | 88.7 / 32.6 | 91.1 / 44.1 | 59.4 | 197 | 5.9 |
| #8 Copilot code review · Max | 87.8 / 28.0 | 88.3 / 40.4 | 55.5 | 973 | 7.1 |
| #14 Qodo | 85.3 / 22.1 | 86.8 / 29.9 | 44.5 | 274 | 4.7 |
| **crucible (this run, not comparable 1:1)** | 85.7 / 32.9 | 84.0 / 46.8 | 60.1 | 540 | 11.7 |

Honest read:
- crucible lands around the block/review line (#6): precision is top-tier, recall is not. OhMyBug finds about twice as
  many golden issues (grounded R 60.2 vs 32.9) by posting ~3x as many comments at similar precision.
- The cause is design, not a bug: crucible verifies and keeps findings it can defend, and its prompt aims at what a
  maintainer would block on. The golden set is 52% low-severity, and crucible's low-severity recall is 27%.
- Not comparable 1:1: 25 PRs vs 219, 1 round vs 3, our own judge run. The interval on recall is ±5 points.
- Two adapter limits cost recall: findings are capped at 60 per PR (PR 1 kept 122), and `--skip-checks` removes the
  executed project checks crucible normally uses.
- Not run: a "deep" setting (`--no-tiers`, Opus verifying everything). Our pool accounts hit monthly spend limits
  mid-run (#15, #16, #18; the reruns used #12, lent by ARMOR), so the cost/recall curve is still open.
- Verdict: not ready to submit. Next: raise the cap, try a recall-oriented pass (more low/medium findings kept when
  verified), add api-architecture and security guidance, then the deep setting, then re-run.
- Spend: $49.22 for the 25 reviews, plus about $7 on attempts cut short by account limits, plus judge calls (not
  metered by the judge CLI).

### 2026-11-11 · recall changes after the ReviewBench run (ReviewBench re-run pending)

What changed, and why (ReviewBench numbers above; each is its own commit):
- **Adapter cap removed** (9fad8f7). `to_findings.py` no longer cuts at 60 per PR (PR 1 kept 122). Findings are
  sorted by severity, so `RB_CONFIG_MAX_FINDINGS=N` drops the lowest first if a cap is wanted again.
- **`--nits`, a verified non-blocking tier** (ea91f7a). The review prompt aims at what a strict maintainer would raise,
  10 per pass, so small real problems are mostly never written down: low-severity recall was 27% on a golden set that
  is 52% low. With `--nits` (or `CRUCIBLE_NITS=1`) the same review call also lists up to 10 nits per pass (medium/low:
  edge cases, stale docs/comments, missing docs or tests for new public API, small leaks). Nits are deduped against
  the findings, verified in batches of 12 per call on the mid model (Sonnet), read-only, under their own cap inside the
  review budget (`CRUCIBLE_NITS_MAX_USD`, default $0.75), and kept only on keep + high/medium confidence; a nit with no
  verdict is left out, not kept. They live in `review.json` `nits`, never touch the findings or the verdict, and with
  the flag off every prompt, schema and cache key is unchanged. The ReviewBench adapter turns it on.
- **Per-PR budget in the adapter $8 → $5.** The run's mean was $1.97 and one PR hit the $8 cap; nits verify after the
  findings, so a tight budget cuts nits first.
- **Short checklists in the review prompt** (f1c4081) for security (with "only with a concrete path from untrusted
  input to the sink", aimed at the 42.9% security precision), API/architecture and docs. About 150 tokens per pass.

Local eval with all of it (`crucible eval --nits`, 20 cases, one round, 2026-11-11 20:26):

| | 2026-11-08 (18 cases, before) | 2026-11-11 (20 cases, --nits + checklists) |
|---|---|---|
| bug recall at blocking severity | 0.923 (12/13) | 0.857 (12/14) |
| any-severity recall | 1.0 | 1.0 |
| false blocking on clean cases | 0 | 0 (6 clean cases) |
| true findings dropped by verification | 5 | 1 |
| extra blocking findings on bug cases | 3 | 2 |
| $ per case | $0.229 | $0.213 (nits $0.027 of it) |

- Cost held: nit verification was $0.53 for 20 cases (13 kept, 10 dropped), and the total per case went down, within
  run-to-run noise. The checklists did not visibly raise review cost.
- The two blocking misses are severity calls, not detection: js-refcount (rated medium, as in every earlier run) and
  py-race (the lost-increment race was found and kept, but at medium; it was important on 11-08). One round can't say
  whether the checklists moved py-race; watch it on the next run.
- Precision on the planted set held: 0 false blocking on clean code, and the extra blocking findings on bug cases did
  not rise. 3 nits were kept on clean cases; they never block, but on ReviewBench they would count against precision
  if the judge rejects them, which is the number to watch in the re-run.
- Nits hit the labelled bug (as a separate, non-blocking comment) in 8 of 14 bug cases, mostly as a second angle on
  a finding that was already kept.

Re-run plan (pending the account): the same 25 PRs with `--nits` and the checklists, 3 rounds if the budget allows,
reporting grounded/augmented P and R, recall by severity and category, comments per PR, and $ per PR (mean, median,
max) next to the 11-11 row. Then the deep setting (`--no-tiers`) on a subset, to price the rest of the curve.
