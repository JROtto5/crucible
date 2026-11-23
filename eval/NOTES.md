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

**Resolved 2026-11-12 12:06 ET, $0, no re-run needed.** All three pyinfra "moved + overlap" rounds are demo replays
of commits that were already merged upstream, not open PRs: 4c9f7cf0a4 and 8ad9760932 are #1587 (on 3.x as 09116428),
5c62b86344 is #2030 (on 3.x as 1cad0d6e). If you rebase them onto current 3.x they conflict with their own merged
copy, so the rebased diff is empty and there is no finding to compare. They are replays of historical rounds, so the
right bucket is "na" and not "moved + overlap". **Corrected week total: 0 upstream moved+overlap rounds.** Side
evidence: 4c9f7cf0a4's kept finding (`requires_command()` gets the `table=` kwarg → TypeError) was fixed upstream by
#1730 (11b62d24) and #2059 (c4636eb0). That counts as one held-up finding (n=1, too few to quote). Lesson: the
base-moved item should mark a round whose head is already an ancestor of, or patch-equal to, the base as "replay"
and not as "moved + overlap".

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

### 2026-11-12 · py-race severity, the nit floor, and ReviewBench run 2 (grounded R 41.1, aug F1 67.6, $1.77/PR)

**py-race: the checklists did not move it.** Tonight's first two runs (HEAD, `--nits`) split: one rated the lost
update important, one medium. A/B on the same case, 4 runs per arm, `--nits` on in both: ea91f7a (before the
checklists) rated the race itself blocking in 2/4 runs, HEAD in 2/4 (scored "caught" 3/4 vs 2/4, because a blocking
"no concurrency test" finding also matches the case). The 11-09 three-arm run also missed it at blocking before any
checklist existed. It is a coin-flip severity call in both arms, so there is no prompt change: tuning the prompt on
one build case would be fitting noise. $1.87 for the A/B.

**Nit floor: high confidence only** (594332a; reverted by 0ac25d7 after the judge, see below). eval now records each kept nit (b0f473e). All 6 clean cases × 2 runs:
6 nits kept, both medium-confidence keeps were taste ("no test for a job that finishes mid-wait", "a doc comment
mentions the previous behaviour"), plus one high-confidence one ("docstring says stopped"). The other 3 were real (dead
`JobSet.clear()`, `timeout=None` raises TypeError, an all-separator slug is now empty and untested). With the floor
at high, the same 12 runs kept 5, all real, at the same cost ($0.14 per clean case). `CRUCIBLE_NITS_MIN_CONFIDENCE=medium`
restores the old floor.

**ReviewBench run 2 (stopped at the account's limit before judging).** Same 25 test PRs, image at 54785aa (`--nits`,
checklists, no cap, $5 budget per PR; built **before** the high-only floor, so it keeps medium-confidence nits too),
`RB_CONFIG_KEEP_REVIEW=1` so each PR's review.json is kept. The run used #12, with a stop at 85% weekly, and that stop
fired during PR 24 (66% → 85% over 24 PRs). PR 24 and the judge did not run. Measured so far, review side only:

| | run 1 (11-11, 25 PRs) | run 2 (11-12, 24 PRs) |
|---|---|---|
| comments per PR | 11.7 | 15.3 (234 findings + 133 nits) |
| $ per PR mean / median / max | $1.97 / $1.15 / $8.04 | $1.83 / $1.17 / $5.09 |
| PRs at the $ cap | 1 (at $8) | 2 (PR 1, PR 13, at $5) |
| wall per PR mean / median / max | 540 / 285 / 2,297 s | 455 / 286 / 1,466 s |
| nit verification | – | $2.72 total; 133 kept (73 high, 60 medium confidence), 49 dropped, 28 unverified (cap) |

The two capped PRs ran out of budget before nit verification, so PR 1 has no nits. ARMOR then allowed #12 up to 92%
for PR 24 and one judge pass (results below; the account ended at 86%).

**ReviewBench run 2, judged** (25 PRs, `npm run judge --provider anthropic --model claude-sonnet-5`, 1 round, same
golden set and judge prompts as run 1). Nits are told apart from findings with each PR's review.json; the two
alternative columns are re-scored from the same judge verdicts (no re-judging): each candidate keeps its verdict, and
golden coverage is the union of what the remaining candidates cover. That re-scoring reproduces run 1's official
numbers exactly.

| | run 1 (11-11) | **run 2 (11-12, as run)** | run 2, high-confidence nits only | run 2, no nits |
|---|---|---|---|---|
| grounded recall, macro | 32.9 | **41.1** | 37.4 | 27.8 |
| grounded recall, micro (95% Wilson) | 32.7 (115/352, [28.0, 37.7]) | **38.6 (136/352, [33.7, 43.8])** | 35.5 | 27.0 |
| grounded precision, macro / micro | 85.7 / 86.4 | **89.7 / 90.8** | 90.8 / 90.6 | 89.9 / 92.1 |
| augmented precision / recall, macro | 84.0 / 46.8 | **86.3 / 55.6** | 84.9 / 50.1 | 82.9 / 38.9 |
| augmented F1, macro | 60.1 | **67.6** | 63.0 | 52.9 |
| comments per PR | 11.7 | 14.8 (239 findings + 130 nits) | 12.4 | 9.6 |
| $ per PR mean / median / max | $1.97 / $1.15 / $8.04 | $1.77 / $1.11 / $5.09 | – | – |
| wall per PR mean / median / max | 540 / 285 / 2,297 s | 441 / 246 / 1,466 s | – | – |

Grounded recall (macro) by severity: high 54.0 → 61.0, medium 35.2 → 44.9, low 27.2 → 36.2 (n = 36 / 134 / 182). By
category, run 1 → run 2: correctness 35.1 → 40.6 (133), reliability 37.6 → 45.3 (58), maintainability 35.4 → 39.2
(44), testing 36.4 → 35.3 (35), security 21.2 → 20.4 (27; grounded precision 61.5 → 57.1 micro), documentation
20.8 → 29.2 (21), api-architecture 12.5 → 25.0 (12), performance 31.2 → 56.2 (12), accessibility 27.8 → 38.9 (10).
Checks executed: no (`--skip-checks`, as in run 1).

Nits, by the judge (true = matched TP or novel TP):

| | candidates | judged true | 95% Wilson |
|---|---|---|---|
| findings | 239 | 153 (64.0%) | [57.8, 69.8] |
| nits, high confidence | 72 | 68 (94.4%) | [86.6, 97.8] |
| nits, medium confidence | 58 | 56 (96.6%) | [88.3, 99.0] |

The verifier dropped 77 nits (49 on its verdict, 28 unverified because the cap or budget ran out). 5 kept nits were not
sent: the adapter leaves out nits with no line and nits on the PR text.

Honest read:
- The nit tier is the whole gain, and it is precise. Nits are 95% true by the judge, above the findings' 64% (the
  findings' misses are mostly novel FPs in maintainability, where augmented precision is 37%). The nits add 13 points
  of macro grounded recall and 15 of augmented F1, and grounded precision went up, not down.
- **The high-only nit floor from earlier tonight (594332a) was wrong, and is reverted** (0ac25d7). Medium-confidence
  nits are as precise as high ones (56/58), and dropping them costs 3.7 points of recall. 2 taste nits on 12 clean eval
  runs was too small a sample to set the default.
- Watch: findings alone did worse than in run 1 (macro grounded recall 27.8 vs 32.9). Two causes fit and one round
  can't separate them: run-to-run noise, or the review call now filing borderline issues as nits rather than findings
  (the dedupe only removes nits that repeat a finding). Either way the total went up.
- Security did not improve (recall 20.4, precision 57.1), so the checklist's untrusted-input line didn't fix it.
  api-architecture and documentation rose, on 12 and 21 golden issues.
- Cost went down: mean $1.77 (the $5 cap held; PR 1 and PR 13 hit it before their nits were verified).

Implied placement (caveat: 25 PRs vs 219, 1 round vs 3, our own judge run; the micro recall interval is ±5 points). The
published rows are in grounded-recall order (#1 60.2, #2 53.5, #3 50.7, #5 46.3, #6 32.6, #8 28.0, #14 22.1), and so
does augmented F1 for the rows below #3. Run 2 (grounded R 41.1 macro, augmented F1 67.6) lands between #5 Laude
RevEngine (46.3 / 75.4) and #6 block/review (32.6 / 59.4): **about #6** (#4 is not in our notes, but sits at or above #5), up from just under block/review in run 1. To
pass #5 it needs about 5 more points of grounded recall and 8 of augmented F1 at this precision. The top of the
interval (43.8) still doesn't reach 46.3, so a top-5 claim isn't supported yet. Nothing was submitted.

Spend: $44.22 for the 25 reviews (nit verification $2.76 of it) on #12 (66% → 86% weekly with the judge, which the
judge CLI doesn't meter in $). Local, tonight: about $6.20 (py-race A/B, clean-case nit runs).

### 2026-11-12 · a nit reserve for budget-capped reviews (ReviewBench focus item 1)

ReviewBench run 2's two capped PRs (1 and 13, at $5) spent everything on the findings, and every nit then went
unverified and was dropped (the nit tier fails closed). Change (11c0059 + the self-review round): the verification of
medium/low findings now runs against the budget less a reserve for the nits, `min(nit cap $0.75, 15% of the budget,
$0.20 per batch of 12 deduped nit candidates)` (`nits_reserve_usd`, recorded as `review.json` `nits_reserve_usd`).
Blocking-severity findings are verified first, against the whole budget. A finding the hold leaves unverified is kept
(fail closed) with its own reason, and the attempt doesn't count toward the retry limit. At the adapter's $5 the
reserve is the full $0.75 nit cap, about 4.7× run 2's mean nit spend per PR ($0.11). No limit set: nothing changes.

Local check, `crucible eval --nits --budget 0.28`, 8 cases (6 bug, 2 clean), one round per arm, d10bc6f vs the change:

| | before (d10bc6f) | after |
|---|---|---|
| bug recall (blocking) | 6/6 | 6/6 |
| false blocking on clean | 0 | 0 |
| true findings dropped | 1 | 0 |
| nits kept / dropped | 1 / 2 | 2 / 1 |
| nit verification $ | $0.157 | $0.073 |
| total $ | $1.378 | $1.377 |

One round on 8 cases is noise-sized. It shows that the hold costs no recall or cost here, not that it recovers nits
at scale. A first try at `--budget 0.12` (not in the table) verified nothing in either arm: the review pass alone
(~$0.17) used the whole budget, which no reserve can fix. The real test is PRs 1 and 13 on the next ReviewBench run (a borrowed account, not this lane): count
their kept nits (run 2: 0 on PR 1) and their unverified findings. Spend this shift: $2.00 over 4 self-review rounds + $4.72 local eval (both budgets, both arms).

### 2026-11-12 · R3 changes (2708fc1, c3c9a5f, 6ed8d12, 4e069a8) and their local eval

What changed, from run 2's judge verdicts and review.json sidecars (general patterns only, nothing keyed on the 25 PRs):
- **Nit reserve over the passes too** (2708fc1). Run 2's PR 1 spent $4.91 of $5 on 24 review passes before any
  verification, so the 11c0059 reserve (medium/low verification only) could not help it. PR 13 was not affected (22
  nits kept). Passes after the first now stop at budget less `min(nit cap, 15%)`, and blocking findings verify within the
  hold too (run 2's unverified findings were judged true 30 of 31 times, and they stay kept).
- **20 nits per pass** (c3c9a5f). The cap of 10 never bound in run 2 (at most 7 from a one-pass PR). Estimate: about
  $0.02 per extra candidate, +$0.08–0.16 per PR at 11–15 candidates, bounded by the $0.75 nit cap.
- **Maintainability false positives** (6ed8d12). 70 of the 72 false maintainability findings were the unverified
  house-style comment checks (0 of 70 judged true, 43 on one PR); the reviewer's own were 6 true and 2 false. With
  `--nits` those checks are now verified nit candidates, at most 3 per review. The secret scanner also skips elided
  example keys: run 2's only 2 critical scanner findings were doc-comment placeholders.
- **Security** (4e069a8). 9 of 27 golden security issues were caught. The 18 misses were mostly hardening gaps with no
  full exploit path (partial or skippable guards, unbounded state, leaky error text, permissions set only at creation,
  secrets left behind on delete, running as root), plus sibling sites of a flaw that was found once. The nit note now
  asks for both, one nit per site. The findings' bar and the base prompt are unchanged.

Local eval (`crucible eval --nits`, 20 cases, one round, 2026-11-12 07:35, account #17), next to the 11-11 `--nits` run:

| | 11-11 (f1c4081+) | R3 changes |
|---|---|---|
| bug recall at blocking severity | 0.857 (12/14) | 0.929 (13/14) |
| false blocking on clean cases | 0 (6) | 0 (6) |
| true findings dropped | 1 | 3 |
| extra blocking on bug cases | 2 | 2 |
| nits kept (on clean) / dropped | 13 (3) / 10 | 18 (5) / 19 |
| $ per case (nit verification) | $0.213 ($0.027) | $0.252 ($0.033) |
| total | $4.27 | $5.03 |

No regression in precision on the planted set (0 false blocks, same extra blocking). Recall is up one case (py-race,
a coin-flip severity call, so it isn't evidence). Cost is up $0.04 per case, mostly review-side (more nits written).
"True dropped" rose 1 → 3 at one round, which is in the noise range of earlier runs (5 on 11-08). The ReviewBench
result of these changes is the run-3 section below.

### 2026-11-12 · ReviewBench run 3 (R3 code, 10df5ca): better on the 23 clean PRs, 2 PRs lost to a Fable spend limit

Same 25 test PRs, same adapter (`--nits`, `RB_CONFIG_BUDGET=5`, `RB_CONFIG_KEEP_REVIEW=1`), image `crucible-rb:r3`
built at 10df5ca (nit reserve held over the passes, 20 nits per pass, house-style and security nits). Account #18
(ARMOR loan), 52% → 60% weekly. Sonnet 5 judge, 1 round. 2.41 h of reviews, $38.88 total.

**Two PRs are damaged, not measured.** crucible routes the biggest diffs to `claude-fable-5-2`, and on #18 that model
answered "You've hit your monthly spend limit" (Opus and Sonnet worked). PR 13 (nebula) failed every pass: 0 comments,
$0. PR 1 (emdash) lost some passes: 32 comments vs 77 in run 2. Those two scored 0.00 grounded recall (run 2: 0.78,
0.33). The 23 other PRs ran normally, so they are the fair comparison. Lesson for the adapter: treat a spend-limit
message in a pass as a failed PR (non-zero exit, rerun), not as a finished review.

| | run 2 (25) | run 3 as run (25) | run 2, 23 clean PRs | run 3, 23 clean PRs |
|---|---|---|---|---|
| grounded R macro | 41.1 | 38.0 | 39.8 | **41.3** |
| grounded R micro [Wilson] | 38.6 [33.7, 43.8] | 37.5 [32.6, 42.7] | | |
| grounded P macro | 89.7 | 85.2 | 88.8 | 88.9 |
| aug P / R macro | 86.3 / 55.6 | 93.7 / 55.3 | 89.1 / 52.5 | **94.1 / 56.6** |
| aug F1 (macro P, R) | 67.6 | 69.6 | 66.1 | **70.7** |
| comments / PR | 14.8 | 12.8 (169 findings + 190 nits kept) | | |
| $ / PR mean / median / max | 1.77 / 1.11 / 5.09 | 1.56 / 0.99 / 4.91 | | |

As run, by severity (macro GR): high 42.5, medium 44.5, low 30.8. By category: security 45.5 (micro GR 59.3, GP 66.7;
run 2 was R 20.4 / P 57.1), correctness 44.0, maintainability 30.1, documentation 25.0, api-architecture 25.0.
Judged true: findings 94.2%, high nits 93.9%, medium nits 91.2%. No nits: GR 22.5, so nits carry about 15 points of
recall at ~92% true.

Reading: the R3 changes help where they were aimed (security recall up from 20 to 46, aug P up 5, aug R up 4 on the
clean PRs) at lower cost. The as-run headline is pulled down by the two account-damaged PRs; rerunning PR 1 and PR 13
on an account whose Fable 5.2 works is the next step before quoting a single R3 number. Still short of #5 (Laude:
grounded R 46.3, aug F1 75.4); at aug F1 ~70 and grounded R ~41 it sits at #6 (block/review 32.6 / 59.4 is below).

### 2026-11-13 · maintainability nits (ReviewBench focus item 1): local A/B, no gain visible

Change: a maintainability paragraph in the `--nits` prompt, built like the security one that took run 3's security
recall from 20 to 45.5. It covers a copied block (naming both sites), dead code (after a search for uses), debug output
or commented-out code, a re-implemented existing helper (naming its file and line), one thing named two ways, and a
repeated magic value. The nit verifier must search for uses or read both sites. It is limited to checkable kinds because
run 2's false maintainability findings were taste (70 of 72 from the house-style comment checks). The run 3 golden
misses themselves were not read: the judge output was not on this desktop or on blaze-3.

New eval kind `nit`: `issues` lists planted non-blocking problems, scored by how many a kept nit or finding (any
severity) hits; a blocking finding there counts as false blocking. These cases run only with `--nits` and stay out of
bug recall.

`crucible eval --nits --no-write`, before (4804564) vs after, 2 rounds per arm:

| | before | after |
|---|---|---|
| nit-py-maintainability (4 planted: missed reuse, dead code, duplication, debug print) | 4/4, 4/4 | 4/4, 4/4 |
| nit-py-maintainability-cross (3 planted, evidence in untouched files) | 3/3, 3/3 | 3/3, 3/3 (1 false blocking in r1*) |
| clean-py-docs + clean-js-refactor: false blocking / nits kept | 0 / 0 | 0 / 0 |
| $ for the first case + 2 clean, per round | $0.89, $0.86 | $0.82, $0.80 |

\* The cross case's first fixture changed `line_items()` from a list to a JSON string, a real contract change, and the
blocking finding was most likely that. The fixture now keeps the return type. Re-run after the fix (after arm, 1 round): 3/3, 0 false blocking, $0.25.

Reading: both cases are at the ceiling in both arms. The reviewer already finds blatant copy/dead/reuse problems in a
small diff, so these cases can catch a regression but can't show a gain. There is no local evidence of a recall gain;
the claim waits for ReviewBench run 4's maintainability category (run 3: 30.1 on 44 golden). Spend this shift: $5.08
local eval + about $0.9 over two self-review rounds.

### 2026-11-13 · ReviewBench run 3: how much of what the verifier keeps holds up (BLAZE verifier-comparison ask), $0 from stored artifacts

Rule (code-read): a kept item holds up if the Sonnet 5 judge (ReviewBench @ f223ce3) matched it to a golden issue as
true or read the code at the PR head and judged it true. Same 25 PRs, R3, 1 round as run (PR 1 and 13 partly lost to
the Fable spend limit). Verify: Sonnet 5.5 on 19 heads, Opus 5.5 on 6, cheap tier Haiku 5.5; nits batch-verified 12/call.

| | n | held up | Wilson 95% |
|---|---|---|---|
| verifier kept / proposed | 521 | 359 (68.9%) | [64.8, 72.7] |
| kept findings, judged | 138 | 130 (94.2%) | [89.0, 97.0] |
| kept nits, judged | 182 | 169 (92.9%) | [88.2, 95.8] |
| all kept, judged | 320 | 299 (93.4%) | [90.2, 95.7] |

39 kept items had no judge verdict (mostly the adapter's per-PR cap): excluded, not counted true. Verify $/PR $0.73
($18.28 / 25); whole review $1.55/PR ($38.86); verify $ per proposed item $0.035. Not measured: how often the verifier
wrongly disproves (the judge never saw the 162 disproved items; judging them is ~$3–5 Sonnet).

### 2026-11-13 · docs nits (ReviewBench focus item 2): out-of-diff doc lines in the prompt, local A/B

Change: with `--nits`, each pass gets a $0 list of docs and comment lines outside the diff that name what the pass
changed (crucible/docrefs.py), a docs paragraph in the nit note, and a stale-doc rule for the nit verifier. Run 3's
documentation category was 25.0; the golden misses themselves were not read (judge output not on this desktop).

New nit case `nit-py-docs-stale`: `deliver_message` retries 5 times (was 3) with exponential backoff, and `MAILER_HOST`
now names the server (the old variable still works). Planted: README "(default 3)" (outside the diff), README and
docs/config.md naming only `MAILER_SMTP_HOST` (outside), mailer/queue.py's docstring "retries 3 times ... 4n"
(outside), and the changed function's own docstring "Waits one second between tries" (context line).

`crucible eval --nits --no-write --cases docs`, before (2a5b3f1) vs after, 2 rounds per arm, run side by side:

| | before | after |
|---|---|---|
| nit-py-docs-stale (4 planted) | 4/4, **2/4** (both README issues missed) | 4/4, 4/4 |
| clean-py-docs: false blocking / nits kept | 0 / 0, 0 / 0 | 0 / 0, 0 / 0 |
| $ for both cases, per round | $0.57, $0.34 | $0.59, $0.29 |

Reading: the one miss in the before arm is exactly what the list targets (doc lines in files the diff doesn't show),
but it is 1 round of 2 on one case, so this is direction, not a measured gain. The after arm's round 1 overlapped a
change to the parameter comparison (only against the same re-added definition); on this fixture both versions list the
same names. $0 sweep, last 8 commits of 7 local clones (56 commits): 20 get a list, median 0 lines, max 6. Spend this
shift: $1.79 local eval.


### 2026-11-14 · API call sites (ReviewBench focus item 3): stale callers outside the diff in the prompt, local A/B, no gain visible

Change: with `--nits`, each pass gets a $0 list of call and import lines outside the diff that use a definition whose
contract the pass's files changed (crucible/callsites.py). The signature of each touched definition is compared base
-> HEAD: a parameter removed or renamed, a positional reorder, a parameter made keyword-only, a new required
parameter, a changed default, a changed return annotation, a key a destructured options object stops reading, a
definition removed or moved. Appending an optional parameter, giving one a default, or adding an annotation is not
listed. Other languages (Go, Rust, C...) have no parameter model: any change to the argument list counts. The nit note
gains an API/architecture paragraph (a second way of doing what the repo already does one way, a crossed layer, a
public name off its peers' pattern). Run 3's api-architecture category was 25.0 on 12 golden issues; the misses were
not read (judge output not on this desktop).

$0 sweep, last 12 non-merge commits of lutris, colyseus, mangohud, heroic and crucible (60 commits): 5 have a changed
contract, 4 get a list, median 0 lines, max 5. Read by hand: lutris cb04e81d (`read_version_from_config` drops its
`default` parameter, 4 callers) and colyseus ccc3ba38 (`guard(root, serverEntry, hostSuffix)` -> `guard(o)`) are real
contract changes. Re-run after self-review round 4 (the rebase moved crucible's window to include this branch): 6 with
a changed contract, 5 get a list, max 6; the new one is crucible 21db940 (`sites()` drops its unused `def_files`
parameter), also real. The first sweep had heroic 94836a3e at 13 lines from React props objects compared as one blob and
generic names (`install`, `remove`); after comparing destructured keys and skipping common names, max 5.

New bug case `py-api-stale-caller`: `charge(customer_id, amount)` now takes the Customer; the PR updates invoices.py
and its test, and `jobs/retry.py` (not in the diff) still passes the id. `crucible eval --nits --no-write --cases
py-api-stale-caller ts-api-break clean-py-docs clean-js-refactor`, before (0eb9546) vs after, 2 rounds per arm:

| | before | after |
|---|---|---|
| py-api-stale-caller | caught, caught | caught, caught |
| ts-api-break | caught, caught | caught, caught |
| clean-py-docs + clean-js-refactor: false blocking / nits kept | 0 / 0 | 0 / 0 |
| $ for the 4 cases, per round | $1.15, $0.67 | $1.27, $0.72 |

Reading: ceiling in both arms again. In a 7-file fixture the reviewer greps for the caller on its own; the note is
for a large repo split over passes, where it doesn't, and no local case shows that. Cost +10% on these 4 cases ($1.99 vs $1.82 over both rounds)
(+$0.04-0.06 on the stale-caller case, where the note appears). The claim waits for ReviewBench run 4's
api-architecture category. Spend this shift: $3.81 local eval.

### 2026-11-15 · nit sweep (ReviewBench focus item 4, low severity): a second nit-only look when budget remains, local A/B

Change: with `--nits` and a `--budget`, a review that spent at most half its budget makes one more nit-only call per
reviewed pass after the findings are verified. The call uses the review model at medium effort. It is shown the same
diff and notes, plus the findings and nits already raised in those files, and asked for what isn't on the list. The
sweep's nits go through the normal nit verifier. Cap: $0.75 (`CRUCIBLE_NITS_SWEEP_USD`); off with
`CRUCIBLE_NITS_SWEEP=0`. Run 3's low-severity grounded recall was 30.8, and nits carried ~15 points of recall at ~92%
true; run 3 spent a mean of $1.56/PR of $5 (median $0.99).

`crucible eval --nits --no-write --budget 5`, 3 nit cases + 3 clean cases, 1 round per arm, run side by side at
0ea52ea's code:

| | sweep off | sweep on |
|---|---|---|
| planted issues (nit-py-maintainability 4, nit-py-docs-stale 4, nit-py-maintainability-cross 3) | 11/11 | 11/11 |
| nits kept / dropped | 14 / 8 | 18 / 2 |
| nits on the 3 clean cases | 1 | 1 |
| false blocking | 0 | 1 (cross case, a first-pass finding) |
| $ for the 6 cases | $1.63 | $2.52 |

Reading: the planted issues were found in both arms (ceiling again), so the +4 kept nits are the only sign of more
recall, and with `--no-write` the eval kept no per-nit titles, so nobody has checked whether those 4 are true or
golden-shaped. The sweep cannot add findings: the cross case's false blocking came from the first pass, and the same
fixture produced one on 11-13. Cost per case went up $0.15 (about +54% on small cases). Projected effect on
ReviewBench: PRs that spent under $2.50 of $5 get about $0.75 of sweep at most (each call is cut at what the cap
leaves, give or take what the CLI spends past it) plus about one verification batch (~$0.20). The worst case pushes
run 3's $1.56 mean to about $2.5, under the $3 ceiling; the typical case adds about $0.2-0.4.
The recall claim waits for ReviewBench run 4. Count `sweep: true` nits in the kept set and in the judge's matches.

Re-run of the cross case after self-review round 2 asked about the false blocking (2 rounds per arm, side by side):
off 3/3 issues, 0 false blocking, 4 and 4 nits kept, $0.37 / $0.32; on 3/3, false blocking 0 then 1, 6 and 7 nits
kept, $0.48 / $0.46. Over all 3 rounds that is 2 of 3 on vs 0 of 3 off. By the code the sweep can't cause it: it
runs after the findings are final and appends only to the nit candidates (`test_nit_sweep_runs_when_budget_remains_and_its_nits_are_verified`
checks the findings are unchanged). But 2/3 vs 0/3 is not evidence of that either way (Fisher p = 0.4), and
`--no-write` kept no finding titles to compare. Unresolved: in run 4, compare false blocking on PRs with and without
a sweep, and keep review.json from the next local run of this case to read the blocking finding. On this case the
sweep added 2-3 kept nits per round.
Spend this shift: $4.15 + $1.63 local eval, $1.13 + $0.55 self-review rounds 1-2 ($2.34 over all 4 rounds).

### 2026-11-15 · ReviewBench run 4 (R4 code, 6dce5d4 before rebase): past the #5 bar on both measures

Same 25 test PRs, same adapter (`--nits`, `RB_CONFIG_BUDGET=5`, `RB_CONFIG_KEEP_REVIEW=1`), same Sonnet 5 judge
(ReviewBench @ f223ce3), 1 round. Image `crucible-rb:r4` installed from a `git archive` of the unpushed stack: docs
and comments outside the diff (focus 2), callers outside the diff (focus 3), the nit sweep (focus 4), the Fable → Opus
fallback on a limit, and the adapter failing a PR that hit a limit or reviewed no pass. Account #17, 6% → 19% weekly.
3.28 h of reviews, $53.08 total. A first launch with an empty credential reviewed nothing and still reported 25 PRs
"passed" at $0, which is why the adapter now also fails a review that ran no pass; that launch was discarded.

| | run 3, 23 clean PRs | **run 4, same 23** | run 3 as run (25) | **run 4 (25)** |
|---|---|---|---|---|
| grounded R macro | 41.3 | **48.9** | 38.0 | **48.1** |
| grounded R micro [Wilson] | | | 37.5 [32.6, 42.7] | 47.7 [42.6, 52.9] |
| grounded P macro | 88.9 | 87.8 | 85.2 | 88.3 |
| aug P / R macro | 94.1 / 56.6 | 93.7 / 66.3 | 93.7 / 55.3 | 94.0 / 68.3 |
| aug F1 (macro P, R) | 70.7 | **77.6** | 69.6 | **79.1** |
| $ / PR mean | 1.48 | 1.87 | 1.55 | 2.12 (median 1.49, max 5.00) |

ReviewBench's #5 (Laude RevEngine) is grounded R 46.3 / aug F1 75.4: run 4 is above both, privately and on one
round. PRs 1 and 13 ran in full this time (53 and 39 comments, both at the $5 cap). No fallback fired: #17's Fable
5.2 worked (2 PRs reviewed on Fable, 19 on Opus, 4 on Sonnet), so the fallback is still untested on a real limit.

By category (macro GR, run 3 as run → run 4): maintainability 30.1 → 54.9, documentation 25.0 → 54.2, correctness
44.0 → 51.7, api-architecture 25.0 → 29.2, security 45.5 → 33.0 (micro 59.3 → 55.6, n=27: the macro drop is a few
small PRs; watch it), reliability 42.3, testing 45.1, performance 43.8, accessibility 33.3. By severity: high 42.5 →
54.5, medium 44.5 → 48.4, low 30.8 → 46.2. Judged true: findings 94.6%, high nits 96.7%, medium nits 94.9%.
Without nits: GR 27.1, so nits now carry about 21 points of recall.

Judged true in run 4, with n (2026-11-15, from the stored `runs/r4` judge output sha256 784ab0cf9d42… joined to each
PR's review.json by file + title; all 486 sent candidates matched exactly one kept item, $0, no re-run):

| | candidates | judged true | 95% Wilson |
|---|---|---|---|
| findings | 167 | 158 (94.6%) | [90.1, 97.1] |
| nits, high confidence | 183 | 177 (96.7%) | [93.0, 98.5] |
| nits, medium confidence | 136 | 129 (94.9%) | [89.8, 97.5] |
| all sent | 486 | 464 (95.5%) | [93.2, 97.0] |

The three intervals overlap, so this run cannot tell nit and finding precision apart; "nits are more precise" is not supported. Kept but not
sent: 32 findings and 6 nits (no line, or on the PR text).

**The nit sweep** ran on 19 PRs (skipped on 6 that spent over half their budget), cost $5.32 over the run ($0.21/PR),
and kept 54 nits (32 dropped by the verifier). The judge called 50 of the 54 true (17 matched, 33 novel) and they are
the only cover for 15 golden issues: macro GR without the sweep's nits would be 43.1 instead of 48.1.

**The cross-file false-blocking question** (sweep, 2026-11-15 above): blocking findings judged false were 1 of 8 on
the 19 PRs with a sweep and 1 of 33 on the 6 without (run 3: 1 of 28). No sign the sweep adds false blocking; too few
to prove it doesn't. The local case's review.json is still the place to read the one blocking finding.

What it doesn't say: one round, private, n=25 PRs (the official run is 219 PRs × 3 rounds). Cost rose $0.57/PR, about
two thirds of it the sweep and the extra nit verification, and stays under the $3 ceiling. Next weakest: api-
architecture (29.2, n=12), security (33.0 macro), accessibility (33.3, n=10), reliability (42.3, n=58, the largest
category below 45).

### 2026-11-15 · security golden issues R3 found and R4 missed (no re-run, $0)

From the stored judge output on blaze-3: ReviewBench @ f223ce3, `runs/r3` (crucible 10df5ca) and `runs/r4` (6dce5d4),
`scoring/results.details.json` sha256 e58bf907a3e1… (r3) and 784ab0cf9d42… (r4); a golden issue counts as found when
any candidate lists it in `covered_golden_indices`. Same 25 PRs in both runs, 27 golden security TPs.

Found: R3 16, R4 15 (micro 59.3 → 55.6, as above). R3 found and R4 missed 4; R4 found and R3 missed 3.

| PR key | golden # | sev | file:line | what | R4 in that file |
|---|---|---|---|---|---|
| DisciplinedSoftware_Codebase-Conversion_1-4b46d68c | 27 | low | .devcontainer/Dockerfile:33 | last USER is root (a semgrep rule) | 0 candidates (75 elsewhere) |
| mheuss_chronicle_14-04ac4c02 | 14 | low | chronicle-daemon/crates/storage/src/media.rs:238 | `DirBuilder::mode` leaves an existing, looser directory unchanged | 5, none on it |
| scottlz0310_Mcp-Docker_29-e7705d26 | 24 | medium | services/copilot-review-mcp/internal/auth/handler.go:90 | PKCE advertised (S256) but optional at /authorize and /token | 8, none on it |
| scottlz0310_Mcp-Docker_29-e7705d26 | 29 | medium | same line | the same PKCE gap, second golden entry | (same) |

So 3 distinct issues, not 4: the two Mcp-Docker entries are one bug filed twice. R4's gains: statswales-frontend_626
#3 (publisher-api.ts:924), Mcp-Docker_29 #0 (session.go:111) and #30 (handler.go:74). All are one-round differences on
PRs both runs reviewed in full; with n=27 and 1 round each, a net −1 is noise, not a regression. The one worth a
look is the PKCE miss: R4 raised 8 findings in handler.go and none on the discovery-vs-handler mismatch, which is a
cross-function spec check (what the server advertises vs what it enforces) that the security checklist doesn't name.

## 2026-11-15: "no testing evidence" before DRG-105 (read-only, $0)

Baseline for b06cb2a..9451ca3 (prose results count as testing evidence). Population: the 240 stored reviews
`crucible stats` reads (`stats._load`, self-reviews excluded); 187 of them reviewed a PR_DRAFT.

- `PR description: no testing evidence` fired in **20 of 240** (20 of the 187 with a draft), kept every time
  (deterministic style check, never sent to verification).
- By project: three-mesh-bvh 16, MangoHud 2, three.js 2. The bvh share is gkjohnson's 5-line cap: short drafts
  that state results in one prose sentence and carry no "Tested:" line.
- The draft text at review time isn't stored, so the new rule can't be replayed on exactly what was reviewed. On
  the 8 drafts as they are on disk now: 2 fail the old rule and pass the new one (bvh-981, bvh-961: both say
  "fails on master ... passes here" in prose); the other 6 pass both, having gained a testing line in later rounds.
- So the check's pre-DRG-105 false-positive floor is at least 2 of the 20 fires (bvh-981 02584fc1 is the DRG-105 case);
  the next 20 drafted reviews show whether the fire rate drops from 20/187 (10.7%).
- Replay on recovered drafts (2026-11-15, $0, crucible 9451ca3 vs b06cb2a^): 6 of the 20 fires can be matched to a
  draft. The 2 on-disk drafts above, plus 4 three-mesh-bvh #969 reviews (57f240cb, d86b2ce3, ddea945b, 330a5daa)
  matched by review.json mtime to the PR body version in effect then, taken from GitHub's `userContentEdits`
  (13:45Z 315 words, 15:23Z 88 words, 16:15Z 98 words). The old rule fails all three versions, which matches the
  fires; the new rule passes all three ("The new packing test fails on master."). **k = 0 of 6 still fire.**
  The other 14 (10 bvh #961b/#981 rounds before any PR opened, 2 MangoHud, 2 three.js) have no recoverable text.
  Caveat: a body version is the nearest posted text, not the byte-exact draft; review.json carries no timestamp,
  so file mtime stands in for review time.
- Recovery attempt for the rest (2026-11-16, $0): **none recoverable byte-exact.** Searched
  work/next/bvh-961b.review{1..8}.log, bvh-981.review{1,2}.log (they hold the finding text, never the draft; the
  check fired in 961b review1-4 and 6 and 981 review2), bvh-961b.answers-review{1,2,6}.md (describe each edit,
  not the text), and the drafts on disk: bvh-961b/PR_DRAFT.polished.md (11-11 07:03, after review4, before
  review6), bvh-961b/PR_DRAFT.md (11-12 10:48, = review8, which did not fire), bvh-981/PR_DRAFT.md (11-11 22:07,
  unchanged since, so it is review2's text: already one of the 6 above). All three pass the new rule; none is the
  text a fired review saw. answers-review1/2 say the review1-2 fires were on drafts with no test line at all, so
  those were true positives under both rules. MangoHud/three.js drafts weren't searched (bvh only, per the
  commitment). DRG-134 stores the judged PR text from here on, so this gap doesn't recur.
  Count note (fixed 2026-11-16): "11 bvh" above should read 10. All 6 matched fires are bvh (bvh-981, bvh-961, 4 ×
  #969), so bvh's 16 − 6 = 10, and 10 + 2 MangoHud + 2 three.js = 14 = 20 − 6.
- MangoHud/three.js follow-up (2026-11-16, $0): **none recoverable either, so recovered 0 of 4.** The 4 fires are
  work/mangohud.review1.log (11-05 16:12:00), next/mangohud-padding.review.log (11-05 04:11:46) and
  next/three.js-profiling.review{,2}.log (11-04 18:06:26, 18:07:46). Every matching draft on disk was edited
  after its fired review: mangohud/PR_DRAFT.md 16:12:19, mangohud-padding/PR_DRAFT.md 04:13:47,
  three.js-profiling/PR_DRAFT.md 18:15:32. The `.polished.md` copies are polish output written later still. Later
  reviews of the same drafts (mangohud review4, padding review2-4, profiling review1/3) did not fire. So all 14
  unmatched fires stay unreplayable, and the floor stays "at least 2 of 20".

### 2026-11-16 · api-architecture (focus item 1): new optional parameters no real call passes, local A/B

Read first ($0, stored judge output on blaze-3, the same r3/r4 `results.details.json` hashes as above): the 12 golden
api-architecture TPs on the 25 PRs, found in r3 / r4 when any candidate lists the index in `covered_golden_indices`.
R4 found 4 (AY2526S2 #7, PROTRIDER #20, fastimage #6, wirechat #5) and missed 8:

| kind | golden | R4 candidates in that file |
|---|---|---|
| plumbing gap: added at one layer, not wired through | gimmes #1 (`volume_floor` not passed by cli.py, not in ScannerConfig; **R3 found it**), Mcp-Docker #28 (`AllowedRedirectHosts` has no env var in `loadConfig`), AY2526S2 #1 (`AddressBook.removeNote` has no `Model` method) | 0, 3, 0 |
| return type / shape | PROTRIDER #28 (annotation says always `GridSearchResult`, may be None), fastimage #23 (class vs instance methods return different shapes) | 4, 4 |
| public API left producing incompatible data | nebula #2 (exported `encrypt()` writes `key_id = ""`) | 6 |
| out-of-scope feature removal | PROTRIDER #22 (cross-validation dropped) | 4 |
| validation contract | TechDebtMCP #4 (flags regex accepts duplicates) | 4 |

The plumbing gap is the largest kind. On gimmes the existing call-site note already listed `cli.py:312` (the PR also
removed `volume_spike_ratio`), and R4 still raised nothing there: the note told the reviewer the call still works,
which it does. It never named the new parameter nobody passes.

Change: `callsites.changed_contracts(..., knobs)` also collects the optional parameters a touched Python/JS/TS
definition gained; `callsites.unpassed` finds every call of it in the checkout (the PR's own calls count, tests don't),
reads each call's arguments, and lists the definition when no real call passes the parameter by keyword, by position
or through a spread. The note asks for a nit at the call or the config only when the value is meant to be set (the PR
or docs call it tunable, or the call's other arguments come from config/settings/CLI), else nothing.
Go/Java/other languages are not covered (Mcp-Docker's is a struct field, AY2526S2's a missing interface method).

$0 sweeps (new code): last 30 non-merge commits of lutris, colyseus, heroic, schema, supabase-js, umu and crucible
(210): 7 add an optional parameter, every one passed by a real caller, **fires 0 of 210**. The 25 R4 PRs, at merge-base
-> head: 3 add optional parameters (gimmes 1, PROTRIDER 7, emdash 7), **fires on gimmes only**, naming `volume_floor
(default 10)` and `cli.py:312`. All other eval cases: silent (clean-py-bounded-shutdown and clean-ts-option-with-tests
add one; their callers pass it). So the review prompt is byte-identical before and after on the other 24 eval cases, and the full `crucible eval` CONTRIBUTING asks for on prompt changes was not run: it would re-measure model variance only (self-review CR-3c50ba15, answered with this).

New nit case `nit-py-unwired-knob` (built on the gimmes shape, not copied): `filter_stale` gains `min_volume=10`, the
tests pass it, `feeds/cli.py`'s call (outside the diff) takes `threshold=cfg.stale_cycles` and doesn't, and
`ScanConfig` has no field. `crucible eval --nits --no-write --budget 5 --cases nit-py-unwired-knob`, before (4fdc54e +
the case) vs after, 3 rounds per arm, side by side:

| | before | after |
|---|---|---|
| planted gap found | 1, **0**, 1 (2/3) | 1, 1, 1 (3/3) |
| nits kept / dropped | 9 / 6 | 11 / 6 |
| false blocking | 0 | 0 |
| $ per round | 0.56, 0.46, 0.38 ($1.40) | 0.70, 0.40, 0.33 ($1.43) |

Reading: direction only (2/3 vs 3/3, Fisher p = 1.0). The note fires on 1 PR in 25, so its cost on ReviewBench is a
few hundred prompt tokens on that PR and nothing elsewhere. At most it recovers 1 golden issue of 12 in this
category (gimmes #1); the claim waits for run 5. Caveat: the shape came from reading a test-set golden issue, so a
gimmes hit in run 5 is weaker evidence than a hit on a PR outside the 25.

Self-review (3 rounds): round 1, `_call_args` re-split the file on every grep hit (20000 hits: 4.97 s, quadratic);
each file is now split once (0.10 s). Round 2: a docstring usage example counted as a call (now skipped, as `sites()`
does), and a call passing a renamed optional parameter's old name was counted as taking the new default (such calls
are now left out: they fail, and `breaks()` lists them). Dropping the knob whenever a parameter went was tried first
and silenced gimmes, which removed `volume_spike_ratio` (default 2.0) while adding `volume_floor` (10). Round 3: a new
optional parameter with the same default as a removed one is a rename, not a knob. Sweeps re-run after each round:
0 of 210, R4 gimmes only, eval cases nit-py-unwired-knob only.
Spend this shift: $2.83 local eval + $3.12 self-review rounds 1-3.

### 2026-11-16 · one flaw at several sites (`also_at`), from the api-architecture and reliability misses, local A/B + full eval

Read first ($0, the stored judge output on blaze-3, `runs/r4/scoring/results.details.json` sha256 784ab0cf9d42…, joined
to `golden/<pr>.json` by index): the api-architecture misses left after the plumbing-gap change (above) are one-offs
(return shape, validation contract, a removed feature); none is "a second pattern beside the repo's", which the nits
paragraph already names. So this shift went to the reliability misses (36 of 58), where one shape repeats:
PaulStSmith_figlet-comment-generator_32 has six golden issues, one per publish workflow, for one flaw ("paths: narrowed
to source files, so a version bump no longer triggers the release"). R3 and R4 both found it and kept **one** finding
at one workflow whose text said "all six publish workflows", and each run matched 1 of the 6.

Across all categories R4 missed 184 golden TPs. For each one, I checked whether a kept candidate in another file named
that file in its message: **8 golden issues on 4 PRs** (figlet 5, statswales_626 #6 consumer-api.ts, fastimage_165 #24
exif.rb, node-postgres_3650 #2 pg-pool diagnostics.js). Two more on agents-config are siblings of a hit, but nothing
named them. The reviewer knew the sites and wrote one comment, and ReviewBench, like a reader of inline comments,
matches by file and line.

Change (only with `--nits`; the no-nits prompt and schemas are byte-identical): findings and nits may carry `also_at`,
the other sites of the same flaw as "path:line". The nits paragraph now says to write a repeated flaw once and list the
other sites (it used to say "give each site its own nit", in the security list only). The $0 filter keeps a site only if
its file is in the change and the line exists at HEAD. The verifier gets "the same flaw is also claimed at …" and returns
`sites_hold`. Only confirmed sites are kept. A finding with no verdict, a transcribed verdict or a dropped verdict keeps
no sites (fail closed). A verifier prompt for a claim without sites is unchanged, so cached verdicts still match. The
ReviewBench adapter writes one row per confirmed site ("… (same flaw as a:8): …"), skipping a site another kept item
already covers. The eval scorer counts the sites the same way.

New build case `nit-py-sibling-tmp`: three sibling exporters each gain the same temp-file-then-rename write. Each leaves
a partial `.tmp` behind when the write raises. This is the sibling-site shape in a different form (not a copy of a
test-set PR). The first fixture version wrote `path + ".tmp"`, which breaks the `pathlib.Path` callers the base
accepted: an unplanted real bug that "after" rated important in 2 of 3 rounds. The finding was true, but the eval
scores any blocking finding on a nit case as false blocking. The fixture now uses `f"{path}.tmp"`, and both arms were
re-run. `crucible eval --nits --no-write --budget 5 --cases
nit-py-sibling-tmp`, 3 rounds per arm, side by side:

| | before (ef1bbe9 + case + scorer) | after |
|---|---|---|
| planted issues found | 3/3, 3/3, 3/3 | 3/3, 3/3, 3/3 |
| false blocking | 0 | 0 |
| nits kept / dropped | 10 / 13 | 13 / 4 |
| $ (3 rounds) | 1.71 | 1.37 |

Reading: no recall difference on this case, because the reviewer already split the three sites "before". It shows the
mechanism working (in kept reviews, every csv_out.py item carried `json_out.py`/`ndjson_out.py` sites, all confirmed by
the verifier) and no loss. Whether it recovers figlet's five waits for ReviewBench run 5. The cost difference is
direction only: 3 rounds per arm, with no review/verification split recorded. Fewer separate nits to verify is a
plausible cause, not a shown one.

Full `crucible eval --nits --budget 1.5` (26 cases, after only; last nits baseline is 11-12's R3 run, 20 cases): recall
**0.933** (14/15; build 12/13, holdout 2/2), any severity 1.0, false blocking 0 (clean and nit cases), nit cases 14/15
planted, $8.73. The blocking miss is js-refcount, rated medium as in every run since 11-04. The nit miss was
nit-py-maintainability's missed-reuse (4/4 in every earlier run). Rerun 3× after: 4/4, 4/4, 4/4, 0 false blocking
($1.17), so it was one-round variance. Not a same-set comparison: R3's run had 20 cases (14 bug, no nit cases), this one
26. No before arm of the full eval was run (another ~$8.7), so for the changed nits prompt the same-case evidence is
the new case's A/B and the maintainability re-runs. On bug cases, 2 extra blocking findings (py-fix-reintroduces-hang:
a "no test for the core behaviour" finding; py-test-deleted: the deleted test, which is the planted bug's other half),
the same count as R3's run (2). On clean and nit cases, 0.

Risk on ReviewBench: a confirmed site is one more candidate, so a wrong confirmation costs precision once per site. The
verifier's site check is what holds that; nit precision in run 4 was 95.5%. Count `same flaw as` rows in run 5's judged
candidates. Not covered: a re-run of a held (budget-refused) finding loses its sites, since they were never confirmed.
Self-review: round 1 (4 lows: no NOTES entry yet, the finding-tier `also_at` path and the report lines untested, one
assertion pinned a line wrap), all fixed in 280968c. Round 2 (4 lows: this paragraph's wording on the R3 comparison and
on cost, a dangling reference, and the nit-sweep branch untested), fixed in the next commit.
Spend this shift: $19.74 ($8.73 full eval, $8.63 case A/B incl. the discarded fixture, $1.17 maintainability re-runs,
$1.21 self-review 1) + $0.67 self-review 2.

## 2026-11-16: how often the debug-statement check (diff.py `DEBUG_RX`) is wrong (read-only, $0)

Counted every stored "Debug statement left in" finding:
- `~/.crucible/reviews` (525 reviews, 19 repos): 4 fires, all one line, the planted `print("DEBUG ...")` in
  eval case nit-py-maintainability (shop/report.py:21, which expected.json lists). 0 wrong. 0 fires on any real
  upstream review.
- ReviewBench runs on blaze-3 (r3, r4, nits1, normal, r4-noauth-void; 25 PRs each): 15 fires, all on one PR
  (simnaut_emdash_2), the same 3 lines every run: `console.log("No tracked files found.")` in i18n/build.ts and two
  `console.log("[...] Setup complete: created admin user ...")` lines in OAuth callbacks. The judge scored all 12 judged
  fires (r4-noauth-void has no scoring) `novel_fp`. They are intended logging (a build script's message, server log
  lines), not leftovers.

So: 4 of 19 fires right (the fixture), 15 of 19 wrong; 3 distinct real-code lines, 3 wrong. n = 19 is too few to quote
a rate. What it does show: on real code, every fire so far was `console.log` used as a script message or server log,
and no real debug leftover has been caught. Each costs one low novel_fp per ReviewBench round. Follow-up DRG-146.

DRG-146 (2026-11-17, lane 0200): narrowed as above, see CHANGELOG. All 3 wrong real-code lines go quiet (test); the planted
fixture DEBUG print still fires. On the 1420-hit corpus (work/next/drg146, paths with the clone prefix stripped) 732 go quiet,
688 still fire. Hand-checked: a random 20 (seed 17) of the 573 the path rule quiets (bench/, scripts/, benchmark/, build/,
example/ output and commented-out lines) and all 11 the tag rule quiets outside script paths: every one deliberate output,
no leftover. Whether ReviewBench's novel_fp drops waits for the next run.

### 2026-11-17 · reliability (focus item: largest category under 45), a nits paragraph, local A/B

Read first ($0, the stored judge output on blaze-3, `runs/r4/scoring/results.details.json` sha256 784ab0cf9d42…,
joined to `golden/<pr>.json` by index; found = any candidate lists the index in `covered_golden_indices`): R4 found 22
of 58 golden reliability TPs; 36 missed. By hand, by shape:

| shape | misses | examples (PR key, golden #) |
|---|---|---|
| a failure the code hides (logged, then success; count includes failures; health stays green) | 6 | chronicle_14 #1 #4 #6, LANdalf_88 #3, apilix_12 #14, TechDebtMCP_135 #2 |
| a resource with no end (no timeout, no stop, cleanup only on success, context replaced) | 7 | Codebase-Conversion_1 #53, jadx_3 #12 #13, CrabTrap_15 #0, agents-config_1 #7, Mcp-Docker_29 #4, wirechat_183 #0 |
| a need the setup doesn't meet (manifest, minimum runtime, one-OS command, container) | 7 | apilix_12 #0 #18, fastimage_165 #24, agents-config_1 #6 #24, LANdalf_88 #4, Codebase-Conversion_1 #33 |
| a step unsafe to run twice | 2 | emdash_2 #2, disaster-ninja_1230 #3 |
| one flaw at sibling sites (already `also_at`, 11-16) | 5 | figlet_32 #2 #5 #6 #8 #9 |
| one-offs | 9 | |

Most are low or medium, the same seen-but-unsaid pattern as the security misses before 4e069a8. Change (only with
`--nits`; the no-nits prompt is byte-identical): `NITS_NOTE` gains a "Reliability gaps, the same way" paragraph naming
the four shapes; the sweep uses the same note. Test: `test_reliability_goes_to_nits`.

New build case `nit-py-reliability` (shapes, not a copy of a test-set PR): a mirror tool gains `fetch()` with no
timeout beside a `head()` that has one, `prune()` that logs a failed delete and still counts it as removed, and a
background refresher thread with no way to stop it. The first fixture version wrote the download straight into
`dest`, an unplanted real bug (a failed transfer leaves a truncated file) that both arms rated important, and the
refresher died on its first error; both were removed and both arms re-run. `crucible eval --nits --no-write
--budget 5 --cases nit-py-reliability`, 3 rounds per arm, before = bf1c513 + case:

| | before | after |
|---|---|---|
| planted issues found | 3/3, 3/3, 3/3 | 3/3, 3/3, 3/3 |
| blocking findings (scored as false blocking) | 0, 1, 1 | 1, 1, 1 |
| nits kept | 11, 9, 8 | 8, 8, 6 |
| $ per round | 0.46, 0.50, 0.53 | 0.52, 0.50, 0.52 |

Reading: the case is at the ceiling in both arms, like the maintainability cases (11-13), so it guards against a
regression and shows no gain. The blocking item, read in one kept "after" review, is the planted no-timeout itself
rated important ("pull and the refresher thread can hang forever"): a severity call on a true issue, seen in both arms;
3 vs 2 of 3 rounds is not a difference. Cost per round is the same within noise; the paragraph adds ~170 prompt
tokens per pass. Regression check on the new prompt, 1 round (`--budget 1.5`, the other 5 nit cases and 6 clean
cases): 15/15 planted, 0 false blocking, 3 nits kept on clean cases (11-16's full run: 1; 11-12 runs: 3 and 5), $3.51.
The recall claim waits for ReviewBench run 5's reliability category (run 4: 42.3 macro, 22/58). Count kept items
there in the four shapes and how many the judge calls true.
Spend this shift: $6.94 A/B (incl. the discarded first fixture, $3.91) + about $0.95 for two kept-review reads + $3.51
regression = about $11.40, before self-review.

## Lens mode and the small tier (2026-11-17, a399276/3c4e5a7)
`crucible eval` on 21 bug + clean cases (no --nits), the same budget ($1.5) and models, plain vs `--lens`, which turns on the small tier:

| | plain | --lens |
|---|---|---|
| recall (blocking) | 0.867 (13/15) | 0.867 (13/15) |
| recall (any severity) | 1.0 | 1.0 |
| false blocking on clean cases | 0 | 0 |
| true findings dropped | 1 | 0 |
| cost, 21 cases | $4.67 ($0.222/case, max $0.36) | $3.80 ($0.181/case, max $0.31) |

The same two cases were missed in both runs (js-refcount, rated medium; py-race). Every case is under 200 changed lines, so all ran in the small tier. Its $1 cap never bound, because no case cost more than $0.36. The 19% saving comes from the lens prompt: no draft and no house-style section. The cap is a ceiling for the host, not where the saving came from. One round each, so the cost difference is within noise for single cases.

**PKCE pair, re-run 2026-11-17 18:08 ET (72212c6, `--cases pkce --no-write`, outputs read in eval/last-run.json):** `py-pkce-unchecked` caught: critical at authsrv/server.py:31, "token() accepts code_verifier but never verifies it", which is the planted line (token() at 31–37 never reads `code_verifier`); plus an important at :21 (required positional PKCE args break the API) and a low at :23 (challenge format unchecked); 1 true finding dropped by the verifier. `clean-py-pkce-enforced`: 0 blocking; a medium at :28 (PKCE required for all clients) and a low at :13 (bad input raises instead of invalid_grant), both fair and non-blocking. $0.919 for the pair. n=1 each, too few to quote; the 15:05 caught/clean result now has a read output behind it.

## 2026-11-18: absence findings answered FIXED, then re-raised (BLAZE two-anchor ask, read-only, $0)
Over stored reviews started since 2026-10-19 (`~/.crucible/reviews`, each project's branches.json for round order). An absence finding is one `absence_anchor()` returns non-None for (model `anchor_files` or an `ABSENCE_RX` title).

| | count |
|---|---|
| kept absence findings | 461 |
| answered FIXED | 55 |
| FIXED, and the same finding (id, or same file + `similar_loose` title) kept in the next reviewed round | 5 (2 three-mesh-bvh, 3 crucible) |
| of those 5, answer carried silently | 0 (4 re-answered by hand, 1 re-answered deferred) |
| kept findings re-checked because their anchor changed (`anchor_changed`) | 40 |
| of those 40, answer carried | 12: 7 deferred, 5 refuted, 0 fixed |

So the silent FIXED carry BLAZE describes had not happened here: 0 of 55. The code still allowed it (`carry_forward` checked only the cited region), so it is closed now with a falsifier test (FIXED, then the anchor file changes and the re-check holds: fails on the old code) and two companions that must still carry (FIXED with neither anchor changed; deferred across an anchor change). The 5 refuted answers carried across an anchor change are left as they are: a refutation can depend on the anchor file too, but no case of one going stale has been seen. 5 of 55 re-raised (9%, Wilson about 4-20%) vs BLAZE's 3 of 94; different units (BLAZE counts followed findings, this counts FIXED answers), so no ranking.

### 2026-11-18 · BLAZE's three never-found classes as eval cases: crucible already finds them at fixture size ($2.80)

ARMOR's 11-18 draw named three classes behind 4 of 5 serious misses (BLAZE's own engine): (a) code in one file
relying on what another file says it returns, broken without a signature change; (b) a denylist an odd spelling gets
past; (c) a missing value treated like an empty one, or the reverse. The cases were written from the class names
alone. Each fixture's own tests pass and each bug was reproduced by hand before any review ran (a login order 900, 2
makes 2 the leader; `/%61dmin` and `/docs/../admin` reach the admin route; `allowed_origins: []` allows every origin).

| case | class | shape | before (crucible 123e902, no `--nits`, $1.5 budget) |
|---|---|---|---|
| py-declared-order-broken | a | a set drops the login order the docstring promises; leader.py takes `ids[0]` | caught, important, registry.py:29 |
| py-declared-order-indirect | a | same, but the promise is in an unchanged file and the set is one file further down | caught, important, index.py:8 |
| py-denylist-odd-spelling | b | host denylist on `urlsplit().hostname`: `localhost.`, `127.1`, `[::1]` pass | caught, important, send.py:21 |
| py-denylist-path-encoding | b | prefix denylist on the raw path; the unchanged upstream unquotes and normpaths | caught, critical, proxy.py:15 |
| py-absent-vs-empty | c | `overrides.get(k) or default`: `allowed_origins: []` becomes `["*"]`, `retries: 0` becomes 3 | caught, important, merge.py:13 |
| ts-absent-vs-null-patch | c | the form sends null for every field the user didn't touch; the unchanged server clears on null | caught, critical, profileForm.ts:10 |
| clean-py-declared-order-kept | | `dict.fromkeys` keeps the order | 0 blocking |
| clean-py-absent-vs-empty | | `key in overrides` | 0 blocking |

6 of 6 caught (Wilson 61-100%, n=6), 0 false blocking on 2, $2.80 for both runs. Every catch names the root cause, not
a neighbour. The cases sit at the ceiling, so they can't show a gain, and no prompt change was made: one that can't
be measured here could still cost recall elsewhere. They stay as regression guards.

The real-PR side, $0, from the stored R4 judge output (`runs/r4/scoring/results.details.json` sha256 784ab0cf9d42…,
joined to `golden/<pr>.json` by index). A keyword pass over the 25 PRs' golden TPs, then read by hand, gives these R4
misses at medium or above:
(a) 3: a UI row that now loads from a handler that returns 503 when an optional store isn't wired; UI and adapter
naming the same config keys differently; a tracing callback that doesn't start the operation its API contract says
it wraps. (b) 1: a user path read without `resolve()`/normalising (traversal, not an odd spelling). (c) 2: an
"opt-in" checkpoint that always runs because its path defaults to a non-None value; `None` handled like one listed
value in a branch. The keyword counts (golden TPs found by R4: a 9 of 27, b 5 of 13, c 24 of 49) are loose, since
the regexes also hit unrelated text, so they are not a recall figure. The hand-read misses are mostly in mid-to-large
PRs (11 to 36 golden TPs, against a median of 12), so the gap is more likely reading reach in a big change than not
knowing the class. That is a hypothesis, n=6, not tested here.

### 2026-11-19 · ReviewBench run 5 (crucible cd17769): grounded F1 62.3 -> 64.3, about #4

Same 25 test PRs, adapter (`--nits`, `RB_CONFIG_BUDGET=5`, `RB_CONFIG_KEEP_REVIEW=1`) and Sonnet 5 judge (ReviewBench @
f223ce3), 1 round. Image `crucible-rb:r5` from a `git archive` of cd17769. PRs 0-12 ran on account #18. #18's 5-hour
window ran out during PR 13 (adapter: LIMIT, exit 1), so PRs 13-24 were re-run on #20 and PRs 0-12 were kept. The first
judge pass hit its 2 h timeout and resumed from its checkpoint. Both borrowed tokens were deleted from blaze3 afterwards.

What changed since R4 (all pushed):
- **Nit drop rule (2102990):** only a refutation the verifier is sure of drops a nit; doubted ones stay as "disputed" low nits (`CRUCIBLE_NITS_DROP`, lens keeps the old rule). Measured first at $0 on R4's stored output: R4 plus all 168 dropped nits, re-judged, gave grounded R 48.1 -> 53.7 and P 88.3 -> 86.6 (macro), F1 62.3 -> 66.3. Matched by message: the 45 nits refuted at medium confidence held 15 golden issues R4 had missed and 2 false ones; the 19 refuted at high confidence, 3 and 3; the 14 never verified (cap or budget), 0.
- **Content files reviewed as code (b1990d3):** templates, prompt/agent/skill files, config, CI and scripts. R4 missed 12 of 16 golden issues in .md files.
- **Review passes 2..n in parallel (8ba7507 .. 364199f):** `CRUCIBLE_PASS_JOBS`, reserved budget slots, a $1 slot floor. Five self-review rounds found an overspend, an over-tight cap, a lone tail pass capped at 1/n and weak tests; all fixed.
- BLAZE's never-found classes as eval cases (399f881, from the shift before).

| | R4 | **R5** |
|---|---|---|
| grounded P / R (macro) | 88.3 / 48.1 | **82.6 / 52.7** |
| **grounded F1 (macro)** | 62.3 | **64.3** |
| grounded P / R (micro) | 89.3 / 47.7 [42.6, 52.9] | 89.8 / 50.9 [45.6, 56.0] |
| augmented P / R / F1 (macro) | 94.0 / 68.3 / 79.1 | 91.1 / 74.5 / 82.0 |
| comments per PR | 19.4 | 23.7 |
| $ per PR, the 25 kept runs | mean 2.12, median 1.49, max 5.00 | mean 2.05, median 1.57, max 5.03 |
| $ incl. PR 13's cut-off first attempt | 53.08 | 56.09 (mean 2.16 over 26 runs) |
| wall per PR (25 kept) | mean 472 s, median 315 s | mean 480 s, median 366 s |

By category (macro grounded R, R4 -> R5): reliability 42.3 -> **62.6**, documentation 54.2 -> 62.5, testing 45.1 -> 56.2,
performance 43.8 -> 56.2, maintainability 54.9 -> 58.1, security 33.0 -> 38.3, api-architecture 29.2 -> 31.2,
correctness 51.7 -> 50.2, accessibility 33.3 -> 11.1 (n=10, 5 candidates). By severity: low 46.2 -> 52.8, medium 48.4 ->
60.2, high 54.5 -> 52.1.

Reading:
- Recall rose on the categories the night's prompt and nit-rule changes aimed at, at about the same cost. Macro precision fell 5.7 points while micro rose 0.5: a few PRs with few matched items now carry a disputed nit the judge calls false, which weighs heavily in a per-PR mean. The board ranks by grounded F1 from the published precision and recall. Computed the same way as R4 (macro), 64.3 sits between #4 diffox ultra (63.6) and #3 Klaussy (67.4) in review-bench.ai/api/leaderboard (profile official-2026-09). That's about #4, private, 25 PRs, 1 round; the official run is 219 PRs x 3 rounds.
- Parallel passes did not cut wall time here (mean 480 s vs 472 s). Most test PRs fit in one or two passes, and the long ones spend their time in verification and the nit tier, not in serial review passes. Speed needs work on verification next.
- PRs 1 and 13 still end at the $5 cap ($5.03, $4.74). The mean stays under the $3/PR rule.
- Next for top 3 (+3.1 F1): precision on disputed nits (route them through a second, cheaper check, or drop the ones refuted at low confidence; R4 data says those were 4 true / 5 false), api-architecture and security recall, accessibility (5 candidates for 10 golden).

### 2026-11-19 · the verifier judged "caused by this change" against the wrong base (from R5's stored output, $0 read, $2.38 re-verify)

FOCUS item 1 first (precision of disputed nits), read at $0 from R5's stored judge output (`runs/r5/scoring/results.details.json`
on blaze-3, joined to each PR's kept `review.json` by message; a re-scorer reproduces R5's 82.6 / 52.7 / 64.3 exactly).
ReviewBench's grounded P is matched_tp / matched, so only a candidate matched to a golden *false* item costs precision;
novel_fp doesn't. R5 kept 94 disputed nits: 16 matched golden TPs, 4 matched golden FPs. Dropping any confidence-defined
subset of them lowers F1 (all disputed 60.8, keep=false medium 61.4, keep=false low 63.9; keep=true low 64.3, no change).
The 5.7-point macro P drop R4 → R5 is two PRs, not disputed nits: emdash had 0 matches in R4 (left out of the mean) and
1 in R5, a verified nit matched to a golden FP (P = 0 enters the mean, about -3.5 points); chronicle went 2/3 → 0/1
(-2.7), also a verified nit. Both read like true claims. Nothing in the verifier's confidence predicts them, so FOCUS
item 1 is closed with no change.

What the same read found instead: R5's verifier dropped 71 claims (26 findings, 45 nits). **36 were refuted on causation**
("predates", "not in the diff", "HEAD commit only changes X"); **29** of those cite a line the PR's diff adds
(`pr/<key>/diff.patch`). The evidence shows why: the verifier is never told the review's base, so it checks `git show
HEAD`, `HEAD~1` or upstream main, and a multi-commit PR's earlier commits look "pre-existing". Several of these came
after the verifier had confirmed the mechanism ("Falsification test fails: no path sets success=False ... But causation
fails"). Only the re-check of carried findings had the range (`RECHECK_SCOPE`, 11-11). Hand-matched to the golden set,
the 36 hold 11 golden TPs R5 missed on 6 PRs (incl. a high one, undeclared test deps), among them PROTRIDER #20, an
exported helper that now only accepts a DataFrame (api-architecture).

Change: both verifiers get `change_scope()`: "The change under review is every commit from <merge-base> to HEAD, i.e.
`git diff <base> HEAD`, not only the last commit", plus whether the cited line is one the range adds (from the parsed
diff, $0). No base: the prompt is byte-identical (cached verdicts match). Eval cases can now have a second commit
(`change2/`, `message2`).

Re-verify ($2.38): the 36 stored claims, fresh clones at each PR's head, today's verifiers with the scope line: **32 of
36 kept** (findings 15/17, nits 17/19 incl. 2 disputed). The golden-FP one among them (a case-sensitive `== "TRUE"`)
is still dropped. $0 re-score of R5 adding the 11 matched golden TPs and, pessimistically, one golden-FP match
(PROTRIDER's fastparquet nit): grounded P / R / F1 82.6 / 52.7 / 64.3 → **84.8 / 55.1 / 66.8** (66.9 without the FP).
That is an estimate from hand matching, not a judged run; run 6 measures it.

Eval, new nit case `nit-py-earlier-commit` (3 planted lows in commit 1: an exported `rank()` that now only takes a
dict, a dataclass default that the shipped example config contradicts, a debug print; commit 2 changes only the
README). The first fixture had two unplanted real issues (a `None` settings path that differed from `Settings()`, old
input files silently ranking empty) that both arms flagged; fixed, both arms re-run. `crucible eval --nits --no-write
--budget 5 --cases nit-py-earlier-commit`, before = 7ffd136 + case:

| | before | after |
|---|---|---|
| planted issues found (9 rounds; first 3 on the first fixture) | 26/27 | 27/27 |
| rounds with a blocking item (a planted low rated important) | 2/9 | 5/9 |
| $ per round | 0.45-0.89 | 0.49-0.68 |

Reading: the case is near the ceiling in both arms. In the eval repo a `main` branch sits beside the change, so the
old verifier found the right base most of the time. ReviewBench checkouts have only a bare base sha. Kept review.json
from the last 3 rounds per arm: the reviewer proposes important or critical for these lows in both arms, and the
verifier usually lowers them to medium. The after arm kept one at important where before kept none verified (before's
one blocking item was unverified). 2/9 vs 5/9 is not a significant difference (n=9), but it is a plausible side
effect: a verifier told the line is the change's own downgrades less. ReviewBench doesn't score severity. For users it
would show as a true low rated important. Watch in run 6 by severity.
Self-review round 1 (fe9b47b): NOT_GREEN, 4 items. Fixed: the scope line moved into the prompt template (a regex had
put it on the first `Claim:` line, which a `since` text could contain), and the README/CONTRIBUTING case counts. This
entry answers the eval-result item. "Large new logic with no comments": the new functions have docstrings, no change.
Self-review round 2 (a142890): 5 lows. Fixed: README line 16 still said 37; this entry said "35 refuted, 30 kept", a
miscount of the stored output (36 refuted, 32 kept); no test for the `since`/`Claim:` placement, now pinned with the
rendered layout. Not changed: "hard-coded 8-space indent" (the rendered prompt lines up: dedent strips nothing once the
code region is in, and the new test pins the layout).
Self-review round 3: the change_scope docstring still said 35; fixed, plus a why-comment. Round 4: GREEN.
Spend this shift: $2.38 re-verify + about $9.6 eval A/B (18 rounds incl. the first fixture) + $1.42 self-review (4 rounds).

### 2026-11-19 · board figures reconciled: the site's default table is grounded F1 on high-severity issues only

The review-bench.ai figures (e.g. OhMyBug 92.0 / 75.6 / 83.0) are not a different scorer or PR set. They are the
same official run (profile official-2026-09, 219 PRs x 3 rounds, Sonnet 5 judge) restricted to **high severity**:
`/api/leaderboard/metrics?severities=High&preference=balanced` returns OhMyBug grounded P 91.999 / R 75.615, and
2PR/(P+R) = 83.0. The site's caption, `/leaderboard.md` and `/llms.txt` all say it: "ranked by grounded F1 on
high-severity issues", grounded = matched candidates only, F1 = beta 1 ("balanced"; "precise"/"thorough" are F0.5/F2).
Per methodology 7.3/7.4 the filter keeps golden items of that severity and candidates whose *matched golden* has it (the
classifier's label for unmatched ones), recomputed server-side; the High view lists each agent's top 3 configurations.
`/api/leaderboard` (no filter, what we used for 69.3 / 68.8 / 67.4 / 63.6 / 62.6) is the same F1 over all severities;
its `rank` field sorts by that, but it is not what the page shows by default.
Aggregation is not stated anywhere public. The published numbers look **macro** (per-PR mean): `novelYield` is below
the pooled `novelTruePositives / candidates` for every leader (OhMyBug 71.6 vs 75.9), which a per-PR mean gives and a
pooled ratio can't. So our macro figures are the like-for-like ones. F1 is from the published P and R, not a mean of
per-PR F1 (83.0 and augmentedF1 88.73 both check).

The public ranking (High, grounded F1, 11-19):
#1 OhMyBug 83.0 (92.0 / 75.6), #2 intent-review-agent 82.2, #3 intent-review-agent v1 78.7, #4 Copilot code review
Max 75.7, #5 Laude RevEngine (Opus 5.5) 73.3, ... #9 Klaussy opus 69.3, #10 Qodo 68.3, ... #16 diffox ultra 65.6.

R5 on the same measure, from its stored judge output (`runs/r5/scoring/results.json` on blaze-3, sha256 of
results.details.json 99c057dd…, the scorer's own `by_severity.high`): 36 high golden TPs on the 25 PRs, 18 matched
candidates, all 18 TP. Macro grounded P / R 100.0 / 52.1, **F1 68.5 → #10 of 25** (between Klaussy 69.3 and Qodo
68.3). Micro 100.0 / 50.0 (18/36, Wilson [34.5, 65.5]), F1 66.7 → #14. R4 was 100.0 / 54.5, F1 70.5 (#7): run 5's gains
were on medium and low, and high recall slipped one golden item's worth.

Reading:
- "About #4" for R5 holds only on the all-severity view the page doesn't show. On the page's default it is about #10,
  and the gap to top 5 (73.3) is high-severity recall: P is already 100; R must reach ~58 (21 of 36) for #5 and ~65
  for #3. That makes high-severity recall, not nit precision, the lever for the public table.
- Not like for like: 25 PRs / 36 high golden items vs 219 x 3 rounds; one item moves R by 2.8 points and F1 by ~2.
  The ReviewBench goal (project_reviewbench_goal) should name which view it targets; the site's is the High one.

### 2026-11-19 · high-severity misses (R5): 18 of 36, by bucket ($0, from stored output)

Read from R5's judge output (`results.details.json`, `covered_golden_indices`) joined to each PR's kept `review.json`
(findings, dropped, nits, nits_dropped with verdicts) and the golden file. A re-scorer reproduces the scorer's
`by_severity.high` exactly (macro R 52.1 over the 14 PRs that have a high golden item; R4 54.5). Two facts about the
judge decide the buckets: matching is **file-scoped** (`scripts/eval/matcher.ts`: "only compares findings in the
same file"), and the high view filters by the **golden** item's severity, so a low nit at the right file counts in
full. Macro weighting: each of the 14 PRs is 7.1 points of high recall, so a PR at 0/n is the cheapest place to gain.

| # | PR | golden (category) | bucket | bug class | what crucible had |
|---|---|---|---|---|---|
| 1 | aafactory | #0 reliability | refuted (causation) | test plugins missing from the manifest | important, dropped "pre-existing" (an earlier PR commit); R4 had it |
| 2 | tp_152 | #0 correctness | wrong file | command is a stub (advertised feature does nothing) | medium, verified, anchored at docs/UserGuide.md:343 |
| 3 | tp_152 | #1 api-architecture | wrong file | operation missing from the layer interface | low nit at AddressBook.java:96 ("removeNote has no production caller"); golden at Model.java |
| 4 | Codebase-Conversion | #33 reliability | never raised | devcontainer image build fails (apt repo key in the base image) | only devcontainer.json nits |
| 5 | translator-ingests | #9 correctness | judge split | `break` for one branch's None action ends the loop | critical `break` finding at :413 (inside the golden 411-450), matched to #0/#14 instead |
| 6 | TechDebtMCP | #0 security | never raised | user path to fs calls, no isAbsolute/resolve | the project's CLAUDE.md rule for this sits at char ~9.5k; crucible's rules excerpt is the first 5,000 chars of each file |
| 7 | jadx-collaboration | #1 correctness | never raised | nullable captured `var` passed in a non-inline lambda (Kotlin smart cast) | nothing |
| 8 | CrabTrap | #21 correctness | never raised | UI now depends on an endpoint that 503s in one deployment config | nothing |
| 9 | apilix | #0 reliability | wrong file | runtime deps missing from the manifest | medium nit at server/package-lock.json:14; golden at server/package.json |
| 10 | apilix | #6 correctness | refuted (causation) | debounced save cancelled on switch, edits lost | important, dropped "introduced in c8b6a1e" (an earlier PR commit); R4 had it |
| 11 | apilix | #19 correctness | refuted + wrong file | call to an IPC method nothing exposes | critical at README.md:356, dropped on causation; R4 had it at s3Adapter.ts:28 |
| 12 | apilix | #25 correctness | refuted + wrong file | same as #19 (second golden copy) | same item |
| 13 | apilix | #26 correctness | never raised | field names differ between writer (UI) and reader (adapter) | nothing |
| 14 | agents-config | #1 correctness | never raised (sibling) | tool-specific syntax copied to a sibling template | Codex twin found (matched #0), no also_at to the Gemini file |
| 15 | agents-config | #2 correctness | never raised | unverified tool behaviour (prose-wrapped @imports) | nothing |
| 16-18 | emdash | #0, #1, #4 correctness | never reviewed | OAuth baseUrl from the internal origin behind a proxy (3 routes) | the 3 files sit in pass 8 of 24; passes run in path order, so `.agents/`, `demos/`, `i18n/` went first; 261 of 408 files unreviewed at the $5 cap |

Buckets (primary): never raised **7**, wrong file **5** (2 of them also refuted), never reviewed **3** (one PR),
refuted on causation **2** (+2 above), judge split **1**, raised too low **0**. The four R4 items R5 lost (#1, #10,
#11, #12) were all wrong-base causation refutations, which fe9b47b fixes (its re-verify kept the #1 claim).

Fixes, in order of high-recall weight: (a) pass order under a budget: security-named code, then code, docs, lockfiles and
demo/example trees (emdash, up to 7.1 points); (b) project rules past the excerpt: the rule lines of a long
CONTRIBUTING/AGENTS/CLAUDE.md (TechDebtMCP, 7.1); (c) anchor at the line a fix changes, and keep the separate nit
on the doc text (tp_152 x2, apilix x3; a first wording that put the doc site in also_at lost the doc nit in 3 of 3
eval rounds and was not shipped). Never-raised one-offs (Kotlin smart cast, cross-layer 503, field-name mismatch,
devcontainer key) have no shared shape; no change for them now.

### 2026-11-19 · the three high-recall fixes, measured: targeted re-run of the 5 PRs holding 15 of R5's 18 misses, full eval

Changes (main): 81f65c8 pass order riskiest first (+326561b templates/ is code), 75d4ad7 guide rule lines past 5,000
chars (+326561b, 85fc223 cut-at-a-line-start fix and test), ea7d80f the "where a finding sits" paragraph (--nits).
fe9b47b (verify scope, 11-19) is in both arms' code since R5 ran without it.

**Targeted ReviewBench run** (image `crucible-rb:r6` = ea7d80f, same adapter and judge as R5, 1 round, account #20;
judge resumed on #24 after it hung idle at 17:13Z): PRs TechDebtMCP, emdash, apilix, aafactory, tp_152.

| PR | high golden | R4 | R5 | **R6t** | what moved |
|---|---|---|---|---|---|
| emdash | 3 | 0 | 0 | **3** | the auth routes were in passes 1-2 (was 8 of 24); raised at login.ts:28 and callback.ts:42 |
| TechDebtMCP | 1 | 0 | 0 | **1** | raised as a (disputed) nit at handlers.ts:441, "new fs call on the raw user path", with the CLAUDE.md rule in view |
| apilix | 11 | 6 | 6 | **9** | the IPC call kept at s3Adapter.ts:28/:31 (#19, #25), the debounced save kept at store.tsx:668 (#6); deps still cited at the lockfile (#0), field names (#26) still not raised |
| aafactory | 3 | 3 | 2 | **3** | undeclared test plugins kept (pyproject.toml:27 and the test file) |
| tp_152 | 2 | 0 | 0 | 0 | still cited at docs/UserGuide.md:344 and AddressBook.java:95, so the anchor paragraph did not move this one |
| **sum** | 20 | 9 | 8 | **16** | high precision 16/16 matched TP |

Review $ on these 5: 12.00 (R5 12.44). Splicing these 5 into R5's other 9 PRs: macro high R 52.1 → 70.7, F1 at P 100
68.5 → 82.9. That is an estimate from one round on the PRs chosen for their misses (regression to the mean works
in its favour); run 6 measures all 25.

**Full eval** (`crucible eval --nits`, 39 cases, budget 1.5, code ca76ecc, in the r6 image on blaze-3, $15.15):
recall 0.913 (build 19/21, holdout 2/2), any severity 1.0, false blocking 0 on 9 clean cases (11-18: 1), nit cases
19/21 planted issues (11-18: 18/18 on 6 cases), 0 false blocking there. The two build misses (py-declared-order-broken,
py-race) were found at medium; both are one-pass fixtures that the pass order and rules changes don't touch. Re-run
twice each at HEAD: 4/4 caught at important. py-race's severity has flipped before (11-12 entry). Not a regression.
Nit cases on the 6 the 11-18 run had: 16/18 (maintainability missed-reuse, reliability prune-counts-failures). Re-run 2
rounds per arm, 75d4ad7 (no where-it-sits paragraph) vs HEAD, on the maintainability, maintainability-cross and
reliability cases: 20/20 planted found in both arms, false blocking on those cases 2 vs 3 of 6 runs (11-18: 2). Variance.

### 2026-11-19 · ReviewBench run 6 (crucible 85fc223): high-severity F1 68.5 -> 73.7, about #5 on the site's table

Same 25 test PRs, adapter (`--nits`, `RB_CONFIG_BUDGET=5`, `RB_CONFIG_KEEP_REVIEW=1`), Sonnet 5 judge @ f223ce3, 1
round. Image `crucible-rb:r6f` from a `git archive` of 85fc223 (pass order, guide rule lines, where a finding sits,
plus 11-19's verify scope fe9b47b; later commits are docs). PRs 0-22 on account #18; its 5-hour window ran out in PR
23 (LIMIT, exit 1), so PRs 23-24 were re-run on #16. The judge stopped once on nebula ("matcher returned invalid
JSON") and was resumed from its checkpoint. All borrowed tokens were deleted from blaze-3 (the run scripts' trap).
`results.details.json` sha256 35747222e118….

| | R4 | R5 | **R6** |
|---|---|---|---|
| **high: grounded P / R / F1 (macro)** | 100.0 / 54.5 / 70.5 | 100.0 / 52.1 / 68.5 | **91.7 / 61.6 / 73.7** |
| high: found (micro) | 19/36 | 18/36 | **22/36** |
| high: augmented P / R | 100.0 / 65.9 | 100.0 / 63.4 | 98.2 / 73.3 |
| all severities: grounded P / R / F1 (macro) | 88.3 / 48.1 / 62.3 | 82.6 / 52.7 / 64.3 | **90.7 / 57.5 / 70.4** |
| all: augmented P / R | 94.0 / 68.3 | 91.1 / 74.5 | 93.5 / 75.9 |
| $ per PR, the 25 kept runs | mean 2.12, median 1.49, max 5.00 | mean 2.05, median 1.57, max 5.03 | mean 2.13, median 1.51, max 5.02 |
| $ incl. cut-off attempts | 53.08 | 56.09 | 54.48 |
| wall per PR (25 kept) | mean 472 s | mean 480 s | mean 450 s, median 387 s |

Rank on the site's table (High, grounded F1, `/api/leaderboard/metrics?severities=High&preference=balanced`,
fetched 11-19): #4 Copilot code review Max 75.7, **#5 Laude RevEngine 73.3**, #6 Copilot Balanced 72.7. R6's 73.7 sits
between #4 and #5, so about #5 (private, 25 PRs, 1 round; one high item moves F1 by ~2). On the all-severity API
(`/api/leaderboard`, not what the page shows) 70.4 is above #1 OhMyBug 69.3.

High-severity items, R5 -> R6: gained 7 (aafactory #0, apilix #6, #19, #25, agents-config #1, emdash #0, #1), lost 3
(apilix #28, #29, #35: a workspace switch that doesn't flush the pending save, at three call sites; R4 missed them too).
Still missed 14: tp_152 x2 (still cited at the guide and AddressBook), TechDebtMCP (found in the targeted run as a
disputed nit, not this time), CrabTrap, apilix #0 (lockfile) and #26, translator-ingests #9, Codebase-Conversion
#33, jadx #1, agents-config #2, emdash #4.

Precision on the high view fell from 100 to 91.7 by one item: a verified low nit on figlet's publish workflow
("installer manifest drops PortableCommandAlias: figprint") matched a golden issue labelled high and false ("winget
falls back to the exe name"). It is that PR's only high match, so its high P is 0 and enters the macro mean. Without
it, high P 100 and F1 76.2 (#4). The all-severity precision rose 82.6 -> 90.7.

Reading:
- The targeted run's 16/20 on its 5 PRs came out 15/20 here (apilix 9 -> 6 of 11, TechDebtMCP 1 -> 0, emdash 3 -> 2,
  agents-config not in it). One round per PR swings a PR by 1-3 items; the 25-PR gain (+4 net, +9.5 macro recall) is
  the measured one.
- Next for #4 (75.7) and #3 (78.7): the wrong-file bucket (tp_152 x2, apilix #0) via a fix-site step after
  verification, measured at $0 on this run's stored output first; then the switch-without-flush sibling sites
  (apilix #28/#29/#35), which an also_at from the store.tsx finding would carry.

**PKCE pair on the 11-18 nightly (6eb3179, full 37-case run 2026-11-18 17:11 ET; read from eval/RESULTS.md:32,47 on 11-20 00:1x ET):** `py-pkce-unchecked` caught (3 kept, 0 nits, $0.43). `clean-py-pkce-enforced`: **1 false blocking** (2 kept, $0.46), and it was the run's only false blocking. Against the 11-17 18:08 re-run (caught / 0 blocking), the bug arm held and the clean arm flipped. That is n=1 per arm per night, so it's variance-sized and too few to quote. The 11-19 full eval reported 0 false blocking on 9 clean cases (line ~1322); per-case output for that run was not written to RESULTS.md, so the clean twin's 11-19 state is read from the aggregate only.

**R4 merged items, countable by place? (asked 11-18, checked on blaze-3 at $0, read-only):** no. R4's per-PR
review.json sits next to findings.json in the run's out/<pr-key>/ (25 files); runs/r4 itself only keeps findings/,
judge.log and log-N.txt. 16 merged items on 11 kept items across 9 PRs (6 findings, 5 nits) are stored only as `also`
titles, with no file, line or severity, and no per-pass output was kept to rebuild them. The missing field is the
`merged` entry (title, file, line, severity, source) that 7f087c1 added, so any run on 7f087c1 or later answers this
as a read of review.json.

### 2026-11-20 · R6's wrong-file misses at $0, and two verifier refutations that cost high items

**Fix-site step (decision: not as a general step).** Read from R6's stored output (`results.details.json` sha256
35747222e118…, each PR's kept review.json, golden). A deterministic step that turns every `path:line` a kept item's
problem/fix/evidence names into an extra candidate (`also_at`) gives 341 extra candidates on the 25 PRs; 232 land on
no golden item, and only 1 lands on a missed high item. Limited to items that sit in a doc or lockfile: 22
candidates, the same 1 high item (apilix #0: lockfile -> `server/package.json`) and 9 near golden-false lows. So:
- apilix #0 is the one real fix-site case: lockfile <-> manifest. A small sibling rule (a kept lockfile finding also
  cites the manifest beside it) would carry it; worth ~0.6 points of macro high recall (1 of apilix's 11). Not built.
- tp_152 #0 (the delete stub) is not a fix-site problem: the doc nit names `DeleteNoteCommand.java:35-37` but was
  dropped by the nit verifier as "the stub predates this change". tp_152 #1 names `Model` with no line.

**Two refutations.** All 36 R6 drops read by hand (12 findings, 24 nits). Two missed high items were raised and
dropped at high confidence, each on a refutation that was right elsewhere in the same run:
| refutation | wrong on | right on |
|---|---|---|
| "other code already does the same" | TechDebtMCP #0 (high): new `fs.stat` on the raw user path; the nit quoted CLAUDE.md's path rule and its own falsifier failed at HEAD. Also #6 (low, true): the new error echoes the path | k1LoW: "new method has no doc comment" (no method in the file has one) |
| "that code predates this change" | tp_152: the delete stub, harmless before, loses data now that notes persist (doc site; matches only medium #29) | PROTRIDER: a docstring already stale at the base |

Fix (review.py `NIT_REFUTATIONS_NOTE`, nit verifier only): the first refutation settles style and consistency only;
a claim that quotes a written project rule is judged on whether the code the change adds follows it, as is a bug or
security gap the change repeats; "predates" doesn't answer "this change makes old code reachable or harmful".

A/B, re-verifying R6's 20 dropped nits (PR_DRAFT.md ones left out) with the stored items, `fresh`, same model
(claude-sonnet-5-5) and batching per PR; repos cloned at each PR's head (`/tmp/claude-1000/r6an/reverify_nits.py`):
| nit | old prompt (R6 + 4 rounds) | first wording (2) | **shipped wording (6)** | "sure refutation" wording (2) |
|---|---|---|---|---|
| TechDebtMCP:441 path rule (golden #0 high, tp) | 0/5 kept | 0/2 | **5/6** (5 verified) | 0/2 |
| TechDebtMCP:445 error echoes path (#6 low, tp) | 0/5 | 0/2 | **5/6** | 0/2 |
| k1LoW:76 no doc comment (style) | 0/5 | 0/2 | 4/6 disputed (low) | 1/2 disputed |
| agents-config AGENTS.md:1 (style) | 0/5 | 0/2 | 2/6 disputed | 1/2 disputed |
| tp_152 UserGuide:344 stub (#29 medium) | 2/5 disputed | 2/2 disputed | 1/2 disputed | 0/2 |
| the other 15 | as before within a round's noise | | | |
All 20, 2 rounds per arm: kept 16 (old) / 14 (first) / 22 (shipped) / 15 ("sure") of 40.
Reading: the first wording made the verifier say "this change doesn't make the stub newly harmful" but changed no
verdict. The shipped one tells it to read the quoted rule and judge the added line; in the rounds that kept 441 its
evidence quotes CLAUDE.md. The "sure refutation" variant's two drops say "the premise isn't a project rule" (it
never opened CLAUDE.md), so the phrase steered it back to the convention argument. n=6 on one item: the expected gain
on the High view is ~5/6 of TechDebtMCP's one item, about +6 points of macro high recall, if run 7 behaves like the
re-verify; the cost is 0-1 extra disputed low style nits per PR like k1LoW's, which land on no high golden item.
Spend: re-verify $2.62 + $1.17 + $1.16 + $0.68 = $5.63; eval $6.60 + A/B $1.42; self-review rounds below.

**Eval** (self-review round 1 asked for it). New build nit case `nit-py-rule-new-instance` (40 cases): a project
guide (CLAUDE.md) forbids absolute paths in error messages, an older message in the same function already breaks
it, and the change adds a size cap whose new error does too. Written from the class, not from the PR. Old code
(1cd5bb4) vs HEAD, `crucible eval --nits --budget 1.5 --cases nit-py-rule-new-instance`, 2 rounds each: found 2/2
vs 2/2, 0 false blocking in both, $0.36-0.40 vs $0.29-0.37. The reviewer raises it as a kept medium finding in every
round, so the nit verifier never judges it: the case is at the ceiling and guards the class, not this note.
`crucible eval --nits --no-write --budget 1.5 --cases nit- clean-` at HEAD (17 cases, $6.60): nit cases 22/22
planted issues (11-19 full run: 19/21 on the 7 older ones), false blocking 0 on 9 clean cases (7 build, 2 holdout),
1 on nit cases (maintainability-cross; the 11-19 A/B had it in 2-3 of 6 runs). Nits on clean cases 23 on 9 (11-18:
13 on 7); none of them is a rule-quoting or "predates" nit (tests, docstrings, edge cases), so the rise isn't read
as this change; no old-code arm was run on the clean cases.

Self-review round 1 (19396cf, $0.21): NOT_GREEN, 3 items, all fixed in 7059200: no eval run or fixture for a
verifier change (the eval above), a 170-char test comment, and the nit_verify_prompt docstring still saying the
prompt is unchanged without a base. Round 2 (7059200, $0.52): 1 low, "the new case passes with or without the note",
true and stated above; deferred (no fixture can make the reviewer raise it only as a nit). GREEN. 491 tests on
blaze-3, ruff clean. Shift spend about $14.3.

**Also seen in R6, not changed today:** 8 important findings shipped unverified because "the rest of the review
budget is held for nit verification" (emdash 7, nebula 1), and 4 findings had a failed verifier call
(`error_max_structured_output_retries`: apilix 2, translator-ingests, node-postgres, statswales). The first is the
11-18 Pickrate bug (blocking verification must come before the nit reserve); it is the next item. Neither costs the
benchmark (unverified findings are kept), but users get blocking findings nobody checked.

### 2026-11-20 · Pickrate fix (0fad47f..67cb577): blocking findings verify against the whole budget

Self-review round 34 asked what the change costs the nit tier, since blocking verification may now spend the nit
reserve. `crucible eval --nits --no-write --budget 1.5 --cases nit- clean-` at 67cb577 (17 cases, $6.82, local):
nit cases 22/22 planted issues (7059200 run: 22/22), false blocking 0 on 9 clean cases (same), 1 on nit cases
(nit-py-reliability; 7059200: maintainability-cross), nits kept 69 (21 on clean cases; was 23), dropped 6. Every case
cost $0.19-$0.58 of its $1.50, so no case comes near the reserve and the eval can't move either way; the cost shows only
on budget-capped ReviewBench PRs (run 2's PRs 1 and 13 are the shape to watch on the next run).

### 2026-11-21 · R6's 14 missed high issues by bucket, and expression sites ($0)

**Buckets** (R6, 25 PRs, 1 round; read from `results.details.json` sha256 35747222e118…, each PR's kept review.json and
golden, at $0; n = 36 high golden, 22 found, 14 missed). Beside BLAZE 2's held-out split (exchange
2026-11-20-blaze-miss-split: serious 5 never raised / 0 raised then dropped / 2 too low, n = 13 serious):
| bucket | n | items (class) |
|---|---|---|
| never raised | 4 | jadx #1 (nullable captured var in a lambda), CrabTrap #21 (UI now depends on an endpoint that 503s in one config), apilix #26 (writer/reader field names differ), Codebase-Conversion #33 (container build fails) |
| raised, then dropped by the verifier | 2 | TechDebtMCP #0 ("others do it too"), tp_152 #0 ("predates"; also cited at the guide). Both refutations fixed 19396cf (11-20) |
| raised in another file than the fault | 2 | tp_152 #1 (at AddressBook, fault in Model), apilix #0 (at the lockfile, fault in package.json) |
| found at one site, a sibling site not carried | 3 | emdash #4 (same `url.origin` flaw found in 2 routes, the 3rd not cited though the text named it), agents-config #2 (same `@` import in prose, cited in a sibling template), apilix #29 (sibling of #28) |
| right site, different mechanism (or judged to another item) | 3 | apilix #28/#35 (raised "switch discards unsaved edits", golden is "switch doesn't flush the debounced save"), translator #9 (the `break` finding covers 411-450 but was matched to #0/#14) |
| raised too low | 0 | (severity doesn't count on the High view) |
Reading: 4 of 14 never raised against BLAZE's 5 of 13 serious; 10 of our 14 were raised somewhere.

**Expression sites (built, feat/expr-sites).** For the sibling bucket: when a kept item quotes a code expression in
backticks that is on an added line within 3 lines of its own, crucible lists the first added line repeating it in each other changed file
as an extra `also_at` site, which the verifier then checks like the reviewer's own sites. Variants, replayed with the
shipped function on R6's stored reviews and diffs (`git diff --unified=5 base..head` of each PR's snapshot, blaze-3):
| variant | sites (25 PRs) | missed high reached | missed medium | on no golden item |
|---|---|---|---|---|
| any quoted span (8+ chars), any changed file | 778 | 3 (emdash #4, agents-config #2, translator #9 by position only) | 27 | 506 |
| span on an added line within 3 of the item's own, other files, 1 per file | 136 | 2 | 2 | 103 |
| + skip a site within 10 lines of any other item | 96 | 1 (lost emdash #4: a different finding sat 5 lines away) | 2 | 82 |
| + skip only near an item quoting the same span | 112 | 2 | 2 | 87 |
| + no bare names, no span in > 3 other files | 35 on 10 PRs | 2 | 1 | 21 |
| + each site claimed once per review (self-review round 1) | 27 on 9 PRs | 2 | 1 | 17 |
| + once per review per expression (round 2) | 31 on 10 PRs | 2 | 1 | 19 |
| **+ covered and claims per expression too (shipped, round 3)** | **30 on 9 PRs** | **2 (emdash #4, agents-config #2)** | **1** | **19** |
The emdash item's own finding was unverified in R6 (the nit-reserve bug, fixed 0fad47f), and an unverified claim keeps
no sites, so both fixes are needed for it. If both sites hold and the judge matches them, macro high recall goes up
about 4.8 points (emdash 2/3 -> 3/3, agents-config 1/3 -> 2/3, over 14 PRs): an estimate, for run 7 to measure.
Eval at 8b1ae92, `crucible eval --nits --no-write --budget 1.5 --cases nit- clean-` (17 cases, $7.04, local): nit
cases 22/22, false blocking 0 on 9 clean cases and 0 on nit cases (11-20 at 67cb577: 22/22, 0, 1), nits kept 75 (22 on
clean cases), dropped 9. last-run.json keeps no sites, so this shows no regression, not whether the sweep fired.
Self-review round 1 (review44, $1.21): NOT_GREEN, 1 medium (no eval: the run above; the CHANGELOG's "prompts are
unchanged" was wrong for the verifier of an item that gets sites) and 4 lows (docs said "own line" for a ±3 window;
two items quoting one expression both claimed the same third site; the finding and sweep paths untested end to end;
added_text rebuilt per swept item). All fixed; the shared-site fix took the replay from 35 to 27 sites.
Self-review round 2 (review45, $0.73): NOT_GREEN, 3 lows, answered before the fix commit: two comment lines over the
wrap width (fixed; the numbers moved here), the eval was at 8b1ae92 not HEAD (deferred: the later commits only
remove sites), and the one-claim rule blocked a different expression near a claimed site (fixed: keyed by
expression, 27 -> 31 sites; a dropped first claimant takes its site with it, kept on purpose and documented).
Self-review round 3 (review46, $0.29): NOT_GREEN, 1 medium (no bug-case eval) + 1 low (covered, the reviewer-site
seeding and the claims still per file). Both answered before the fix commit, then fixed (30 sites on 9 PRs).
Bug cases at the final code, `crucible eval --nits --no-write --budget 1.5` on the 23 js-/py-/ts- cases (the name
filter also ran clean-py-absent-vs-empty; $9.66): recall 0.913 (19/21 build, 2/2 holdout), any severity 1.0, false
blocking 0. Same recall as the 11-19 full run; the misses are the known severity calls js-refcount (medium, every run
since 11-04) and py-test-deleted.

### 2026-11-22 · lockfile -> manifest sites, from R6's wrong-file bucket (apilix #0), $0 replay + eval

**Replay ($0, blaze-3, the shipped `manifest_sites` on every kept and dropped item of runs 4-6, `git diff --unified=5
base..sha` of each PR's snapshot):** R4 0 sites; R5 1 (apilix, package-lock.json:14 -> server/package.json:17); R6 1
(apilix, package-lock.json:13 -> server/package.json:17). The golden high #0 spans server/package.json 1-23; the
lockfile item matched only medium #18 at the lockfile in both runs. No other kept lockfile item in 75 PR runs, so the
rule has no false-site exposure on the bench and an expected gain of 1 of apilix's 11 items (~0.6 points of macro high
recall over 14 PRs), if the verifier holds the site and the judge matches it: for run 7.

**Fixture, four tries (2 rounds per arm each, `--nits --budget 1.5`, HEAD vs main 29ced3b, $10.95 total):**
| fixture | HEAD | main | where raised |
|---|---|---|---|
| auth.js requires jsonwebtoken, multer 1.x, lines 10-14 | 2/2 | 2/2 | package.json (multer CVE findings beside it) |
| no code uses jsonwebtoken, multer 1.x, lines 10-14 | 2/2 | 2/2 (1 of them only a line hit by the multer CVE item at :12, the true item dropped at the lockfile) | package.json 3, lockfile 1 |
| no code uses it, multer 2.x, line 10 (apilix-like) | 1/2 (via the swept site) | 0/2 | lockfile 3/4; the true item dropped 2/4 |
| **shipped**: auth.js requires it, multer 2.x, keywords + line 10 | **2/2** | **2/2** | package.json, all 4 |
The middle shape was dropped: the verifier's refutation there ("an extra root dependency in the lock is pruned, not an
`npm ci` error", from memory, low confidence) is right. npm 11.20 `npm ci --dry-run`: an extra lock dependency installs
fine (5 packages, the extra one pruned); a declared dependency missing from the lock fails with EUSAGE "not in sync".
So golden #0's "npm ci will fail" mechanism is wrong; its real harm is the "Cannot find module" crash its own text
names. The shipped case guards the class at the ceiling; the sweep is covered by tests (unit, end-to-end held/not held,
mutation-checked) and this replay.

## 2026-11-23: dropped, then touched later (BLAZE 11-23 ask 2; a821117, read-only replay, $0)
a821117 stamps each previous-round verifier drop with `later_touched` on a re-review. Older reviews have no stamp, so
the same rule was replayed over the stored incremental pairs (`incremental.from` → this review, `git diff -U0
prev..sha` in a local clone that still holds both commits; /tmp/lt/replay.py, not committed): 376 pairs (1 had no
clone), 802 unique drops (by repo + id; scanner, style and rule drops left out).
| | drops | line (±3) touched later |
|---|---|---|
| all | 802 | 236 (29%) |
| crucible's own reviews | 475 | 139 (29%) |
| upstream reviews | 327 | 97 (30%) |
| proposed critical | 3 | 0 |
| proposed important | 60 | 24 (40%) |
| proposed medium | 229 | 72 (31%) |
| proposed low | 510 | 140 (27%) |
Touched is an upper bound on "dropped, then fixed by the author", not a count of fixes: a line within 3 of an edit
counts. BLAZE's falsifier (<5% fixed later on 50 PRs means the filter loses nothing) is not met by the upper bound;
whether it holds depends on the hand-check below.
**Hand read, the upstream drops proposed important and touched later (5; the other 19 of the 24 are crucible's own):**
- three-mesh-bvh `ndcToCameraRay` "public signature changes with no backward-compatible path": **a real miss.** Dropped in
  both rounds (5768380b, 7291129a), method read, confidence medium, because "there is precedent" (an earlier 0.9.x
  behaviour change) and "I could not check the maintainer's agreement". gkjohnson's first review asked for exactly the
  backward-compatible path (the 2-argument form kept, with a deprecation warning). The refutation rests on a sign-off the
  verifier guessed at and never found. That shape is a candidate for the next verifier change. Per the 11-20 lesson, A/B
  it on stored claims for at least 2 rounds before changing any wording.
- Lutris prefix.py:249, an absolute link to an unmounted drive replaced by an empty folder: dropped at high confidence
  (executed) as an existing limitation that the diff doesn't make worse; the edit nearby was other work. Probably a right drop.
- Lutris prefix.py:229, the translation-markup test, supavisor `reference` NOTICE: refuted on the claim itself
  (probe or test output); the later edits were unrelated. Right drops.
So 1 of 5 is a confirmed dropped-then-fixed. n=5, so no rate is given.
