# Raising first-pass high-severity recall: what papers and other reviewers' write-ups say (2026-11-25)

The problem, as measured in [eval/NOTES.md](../../eval/NOTES.md) (R7, R8): on the sealed held-out 50 crucible's
high-severity grounded precision is 94-95 and recall 37-39 (high F1 55.6, about #23 of 25 on review-bench.ai). On
TRAIN, 9 of the 13 missed high items were never raised: 5 had no finding in their file and 4 had a finding at the
right line with a different claim. 2 more were cited in the wrong file and 2 were cut by the budget. The R8 levers
(text-named sites, bug sweep) each carried the item they were built for but did not move held-out high recall (22 vs
23 of 60). The next lever has to change **what the first look raises**.

This file lists techniques from other reviewers' public write-ups and from papers, ranked by **evidence that they
raise recall of real, serious bugs**, not by how easily they fit crucible. Each entry gives its sources, grades the
evidence, names the miss class it targets, says where it would go in crucible, sketches a cheap test on the TRAIN PRs
that hold the misses, and estimates the $/PR change. The ideas are borrowed with citations. No proprietary text or
code is copied: the open-source RevEngine (Apache-2.0) is paraphrased, and the vendor pages are summarized.

Evidence grades:
- **A**: a controlled measurement on code review or bug finding, peer-reviewed or reproducible from published data.
- **B**: measured, with numbers, by a vendor or an industrial team, or in a preprint, but with no public data, no
  ablation, or a metric other than recall of real bugs.
- **C**: a design description or a marketing claim with no numbers behind it.
- **in-house**: crucible's own stored runs (eval/NOTES.md).

Miss classes (TRAIN, 13 high items on 10 PRs): **NF** = no finding in the file (5), **RL** = right line, another
claim (4), **WF** = wrong file (2), **BU** = budget cut the file (2).

## Where crucible looks worse than the leaders

This section is a plain comparison, written as johnr asked ("don't have biases, do research").

1. **Same model, much lower score.** Laude RevEngine reviews with the same model crucible uses (Claude Opus 5.5). Its
   ReviewBench row is high F1 73.3 (P 92.8 / R 60.6, all 219 PRs x 3 rounds), at about $1 and 3 minutes per review
   by its README. crucible's held-out figure is 55.6 (R 39.4) at $2.46 and about 7.5 minutes. The samples differ (50
   PRs x 1 round against 219 x 3), but RevEngine's recall of 60.6 sits above the top of crucible's held-out interval
   (micro R 36.7, Wilson 95% [25.6, 49.3]). So the model is not what holds crucible back: the harness, the prompt
   and how the budget is spent are.
2. **One sample per diff chunk.** Each 45k-character chunk gets exactly one review call. Every top system runs
   several independent searches: OhMyBug's "fleet of adversarial reviewers", Claude Code Review's parallel agents,
   Bugbot's 8 shuffled passes, RevEngine's seats and swarm copies. crucible's own runs show what that leaves unused:
   two rounds on the same PRs disagree by 3-5 high items (entry 1).
3. **A precision-first reporting contract.** The review prompt asks for "at most 10 findings, ranked; merge findings
   that share a root cause. An empty list is a good answer", and the schema enforces `maxItems: 10`. crucible's
   operating point (P 94 / R 39) sits well left of the leaders' (OhMyBug P 92 / R 75.6, intent-review-agent 92 /
   74.4). Each of them has a verifier too, so the precision is carried by verification, not by a timid first pass.
4. **The PR's intent is graded for style, not used as a spec.** On ReviewBench the PR title and body become
   PR_DRAFT.md, and the prompt shows it under "House style" as a description to judge. Nothing asks the reviewer to
   check that the code does what the description promises. `--lens` mode drops the draft entirely.
5. **Budget goes to tiers the High view doesn't count.** In R8, the nit tier, the nit sweep and the bug sweep (whose
   verified results are nits) moved all-severity recall (+21 items) and not high recall (22 vs 23 of 60). For the
   High table, that money is better spent on a second first look.
6. **Chunks don't see each other.** A pass sees only its own slice of the diff, plus the names of the other changed
   files. A fault that comes from two files changing together, but split across two passes, has to be found by
   tool reads alone. RevEngine puts diffs up to 80,000 characters inline in one conversation.

## Ranked catalogue

### 1. Several independent first looks, unioned, then verified ("seats")

**What it is.** Run the bug-finding pass k times independently. Vary the samples: shuffle the diff order, use a
different model, or give a different brief. Take the union of what they raise, dedupe it, and verify each candidate.
Do **not** majority-vote candidates away: voting is a precision tool and cuts recall (see the Lu et al. numbers).

**Sources and evidence.**
- *Project Naptime* (Google Project Zero, 2024-06-20, <https://projectzero.google/2024/06/project-naptime.html>).
  On CyberSecEval 2, running 20 independent trajectories with built-in verification instead of 1 took buffer-overflow
  success from 0.71 to 1.00 (GPT-4 Turbo) and from 0.40 to 0.99 (Gemini 1.5 Pro), and advanced memory corruption from
  0.36 to 0.76. The authors found that asking one trajectory to weigh several hypotheses was inefficient. **A**
  (vulnerability tasks, not PR review).
- *SWR-Bench* (arXiv 2509.01494, FSE 2026). Over 1,000 verified Python PRs, aggregating 10 independent runs of one
  reviewer (Gemini 2.5 Flash, "Self-Agg") raised overall recall from 13.91% to 30.44% (+119%) and F1 from 15.25% to
  21.91%. Five runs of the same model agreed on only 27 found change-points, and different models on only 36. The
  paper doesn't report precision for the aggregated runs, and the authors still call precision the bottleneck. **A**.
- *Towards Practical Defect-Focused Automated Code Review* (Lu et al., ICML 2025 spotlight, arXiv 2505.17928;
  industrial C++). Three independent reviewers merged by a meta-reviewer, against one: key-bug inclusion 25.93 ->
  31.11 (+5.2 points). Adding their validator then cut it to 20.00 while lowering the false-alarm rate 87.8% -> 75.4%.
  **A**.
- *A Single LLM Is an Incomplete Code Reviewer* (Stone, Zenodo 20519585, 2026-06-03; 154 confirmed defects, 8
  models, 5 providers). 56.5% of defects were found by exactly one model, and the median pairwise Jaccard overlap was
  0.37. Coverage went from 33.6% with one model to 57.1% with a second model from another provider, the biggest step
  on the curve. **B** (single organization, preprint).
- *Building a better Bugbot* (Cursor, 2026-01-15, <https://cursor.com/blog/building-bugbot>). The early pipeline ran
  8 parallel passes, each on a randomly reordered diff, then bucketed and majority-voted. The post calls it one of the
  most effective early gains, but the voting was there to cut false positives. **B/C** (no per-change numbers).
- *Claude Code Review* (Anthropic, 2026-03-09, <https://claude.com/blog/code-review>; docs
  <https://code.claude.com/docs/en/code-review>). Several agents search in parallel, then a verification step runs, then
  dedupe and rank; more agents on larger PRs. **C** for this technique (its numbers are internal usage figures).
- OhMyBug (<https://ohmybug.ai/>, FAQ, plugin README, fetched 2026-11-25): "an orchestrated fleet of adversarial
  reviewers", independent passes, then a second pass that tries to disprove each finding. #1 on ReviewBench, high F1
  83.0. **C** for the mechanism.
- RevEngine swarm prototype (<https://github.com/laude-institute/rev-engine>,
  `experiments/prototypes/swarm/README.md`, read at ca5a2ed 2026-11-24). Its "copies" setting runs each task with
  several independent agents, because two runs "find quite different problems". Its main review can also run several
  model "seats". **C** (no published ablation).
- **in-house.** Two rounds on the same PRs from adjacent builds (the losses sit on items no lever touched, so they are
  run-to-run variance): TRAIN base vs R8 found 17 and 18 of 30 high items, with 4 gained and 3 lost, so their union is **21/30**. Dev R6 vs
  R7 found 22 and 24 of 36, with 5 gained and 3 lost, so their union is **27/36**. Each round's high precision was
  92-100. One extra independent look is worth about +3-4 high items per 30, more than any single lever so far.

**Targets.** NF and RL (the misses that are never raised), and BU indirectly, since cheaper seats spread the budget.

**Where in crucible.** `review.py: run_review`, which drives the pass loop through `run_pass(i, ch, pbudget)` over
`diff.chunk()`. Add a seat index: seat 2 re-runs every chunk with its own cache key. Union the proposals, then run them
through the existing `dedupe()` (which keeps the first pass's item, as since fb540f5) and `verify_tiered()`. Off by
default (`CRUCIBLE_SEATS=1`), so prompts and cache keys stay byte-identical.

**Variants, cheapest first.** (a) the same model with the chunk's files and hunks in reverse order (the Bugbot
shuffle); (b) Sonnet 5.5 as seat 2 when Opus is seat 1 (model diversity, as in Stone and in CodeRabbit's model
comparisons); (c) seat 2 under `lens_prompt()`, with no house-style or description section, so its attention goes to
code.

**Cheap test (~$25-30).** Arm: `CRUCIBLE_SEATS=2` (variant b) with the bug sweep off, on the 10 TRAIN PRs that hold
the 13 misses. Run 1 round. Score against the two stored rounds (`runs/r8base`, `runs/r8train`): count "new carries"
(high items neither stored round credited), "losses" (items both stored rounds credited), golden-false high matches,
candidates sent to verification, and $/PR. Before spending anything, compute at $0 the union recall and union
golden-false count of the two stored rounds over all 60 TRAIN PRs. That is the ceiling a same-model seat can reach.

**$/PR.** Review passes are an estimated $1.0-1.5 of TRAIN's $2.67 mean. That figure is derived, so read the real
split from `tokens_by_kind` in the stored review.json files first. A Sonnet seat adds about 60-80% of that, plus about
$0.10 for each extra verified candidate (about 3 per PR). Turning the bug sweep off saves $0.36. Net: **+$0.5 to
+$1.2/PR**, which is over the ~$3 cap at the top of the range. So cap seat 2's spend (say 30% of the budget) and run
it riskiest chunk first (`review_rank` order already does this).

### 2. A recall-first reporting contract: enumerate, then let the verifier decide

**What it is.** Ask the first look to report every problem it can support, not the top few. Tell it that two
different problems at the same lines are two findings, and lift the hard cap. Precision is the verifier's job.

**Sources and evidence.**
- *Improving LLM-Based Go Code Review through Issue-List Generation and Context Augmentation* (Sun et al., arXiv
  2606.01859, 2026-06-01; 1,438 Go review instances). Prompting the model to enumerate all potential issues, instead of
  its primary issue, and integrating candidates from runs with and without extra context raised refinement exact match
  from 17.15% to 28.00% (+10.85 points, significant). The human upper bound was 36.09%. Pruning then cut the list from
  7.2 to 3.1 candidates and kept nearly all of the gain. **A-** (preprint; the metric is "a candidate matches the
  human's comment").
- Lu et al. (ICML 2025, above): each filtering stage traded recall for precision. Key-bug inclusion went 37.04 ->
  20.00 from the unfiltered list to the final one, while the false-alarm rate fell 94.4% -> 75.4%. **A**. This is the
  measured cost of asking the generator to be selective.
- *Building a better Bugbot* (2026-01-15): once Bugbot went agentic, it was "too cautious", and the team switched to
  aggressive prompts that tell the agent to investigate every suspicious pattern and lean toward flagging. The
  agentic switch as a whole was the biggest gain: bugs flagged per run 0.4 -> 0.7, resolution rate 52% -> 70%+. **B**
  (the prompt change isn't separated out).
- RevEngine `src/prompts.ts` (read 2026-11-24): its reviewer is told to be exhaustive, that a review of a few hundred
  lines usually has ten or more findings, that two problems at the same lines are two findings, and that the same
  defect in two places is two findings. Its human mode caps output at 25, after verification. Its leaderboard row is
  high F1 73.3 on the same model crucible uses. **B/C** (no ablation of the wording).
- Counter-evidence: OpenAI's Codex reviewer chose "modestly reduced recall" for trust ("A Practical Approach to
  Verifying Code at Scale", 2025-12-01, <https://openai.com/safety-alignment/scaling-code-verification/>), and
  CodeRabbit measured a model that caught 69.7% of known issues while only 31.6% of its comments were worth keeping.
  Recall-first only works with a strong verifier behind it, which crucible has: TRAIN dropped 0 high items in
  verification, and held-out high precision is 94-95.

**Targets.** RL directly. On TRAIN, all 4 RL items had a crucible finding at that line about another flaw: nestjs-yalc
#0, dotnet/android #0, obot #0, ia-dev-environment #28. Also NF, where the cap or the "empty list is good" framing
cut a candidate.

**Where in crucible.** `review.py: review_prompt()` (the "Give at most 10 findings, ranked; merge findings that share
a root cause. An empty list is a good answer." sentence) and `FINDINGS_SCHEMA` (`maxItems: 10`). Narrow "merge
findings that share a root cause" to "the same fault with the same fix". Add: "a second, different failure at a line
you already flagged is a separate finding". This is the bug sweep's first bullet, moved into the first look, where
the reviewer still has its own context.

**Cheap test ($0 first, then ~$25).** At $0: from the stored TRAIN review.json files, count passes whose findings
hit 8-10 (the cap binding), and `merged` entries whose members match different golden items. Then run the arm (new
contract, `maxItems` 20) on the 10 TRAIN PRs, 1 round, scored as in entry 1. Add a precision guard: run the 9 clean
cases of `crucible eval` (about $4) for false blocking.

**$/PR.** Longer outputs and about 2-4 more candidates to verify per PR: **+$0.2 to +$0.4/PR**.

### 3. Change-slice context: every mention of what the change touched, given up front

**What it is.** For each name, value, string, path, id format or schema field that the change adds, changes or
moves, grep the whole checkout and give the reviewer every line that mentions it, with a little context.
Deterministic, $0, before the model call. This is program slicing done cheaply.

**Sources and evidence.**
- Lu et al. (ICML 2025): slicing the context around the diff is the largest gain in the paper. Key-bug inclusion
  went from 23.70 (raw diff) to 37.04 with "left flow" (assignments and lifetimes of the changed variables) and to
  39.26 with "full flow" (also right-hand values and callee signatures). Each slice recalled some bugs the others
  missed. **A**.
- *ContextCRBench* (Hu et al., arXiv 2511.07017, 2025-11): in fine-grained review tasks, textual context (issue and PR
  descriptions) gave larger gains than surrounding code. At ByteDance, the benchmark drove a 61.98% relative
  improvement of a production reviewer. **A-** (the gains depend on the task and the model).
- RevEngine swarm, "rich" context: each chunk's agents get every checkout line that mentions a name the chunk defines
  or changes (one `git grep`), the code around those uses, callee heads, matching tests, and the base revision. **C**.
- CodeRabbit (code graph of symbol definitions, <https://coderabbit.ai/blog/context-engineering-ai-code-reviews>,
  2025-07), Augment (semantic context engine, 2026-03-10), Greptile v3 (multi-hop tool loop, 2025-11-26): all say
  cross-file context is where review wins. **C** (Augment reports F1 53.8 on its own 10-PR benchmark, with no
  ablation).
- *LocAgent* (arXiv 2503.09089, 2025): a dependency graph of files, classes and functions (imports, calls,
  inheritance) gave up to 92.7% file-level localization and +12% downstream issue resolution (Pass@10). **A-** for
  localization (a different task).

**What crucible has already.** `callers_note` (call sites, only when a signature changes, `callsites.changed_contracts`),
`docs_note` (prose lines naming touched names, `docrefs.mentions`), `fields_note` (field reads nothing writes), and
`name_sites` (after the fact, as sites). The gap: none of them fires when what the change alters is a **value** and not
a signature. TRAIN's NF misses are of that kind: a moved script whose old path string `packages/agent-orchestrator/
bin/ao.js` is still named elsewhere (agent-orchestrator #4, #17), and a dashboard URL that now carries the raw id,
which consumer pages compare with `COMP-001` (entebus #32).

**Targets.** NF; WF too, since the reader of the changed value is usually the file a fix would change.

**Where in crucible.** A new `mentions_note(repo, sha, files, ch)` beside `callers_note`, `fields_note` and
`docs_note` in `run_pass`, built on `docrefs.touched_names` plus string-literal and path tokens from removed and
added lines. Grep the checkout at HEAD; skip the changed files themselves, lockfiles and vendored trees; cap lines per
name and in total (as `callsites.sites` does).

**Cheap test ($0, then ~$25).** Replay the extractor on the diffs of the 10 TRAIN PRs at $0, as was done for
`text_sites` and `fields_note`: does a mention line land within ±3 of each of the 5 NF items, and how many lines land
on no golden item? Run the same replay on the 1,047 public commits for a size/noise check. Only if it reaches ≥2 of
the 5 NF items is it worth a 10-PR arm.

**$/PR.** Prompt tokens only: about 2-8k more input per pass, mostly cache-read on the agentic loop. **+$0.05 to
+$0.15/PR.**

### 4. The PR's intent as a specification, not as prose to grade

**What it is.** Read the title, body, linked issue and commit subjects as the author's claims. List what the change
promises (obligations). Check each one end to end: is the feature reachable, registered, on every platform or variant,
and does every consumer of a moved or renamed thing follow? A promise the code doesn't keep is high severity.
crucible's SEVERITY_DEFS already says "the change does not do what it claims" is critical, but nothing asks the
reviewer to check that.

**Sources and evidence.**
- *Testora* (Pradel, arXiv 2503.18597, ICSE 2026): it generates tests over the changed code, compares old and new
  behavior, and uses the PR's natural-language text to judge whether each difference was intended. It found 19
  regressions in popular Python projects (13 reported in v3, 11 confirmed, 9 fixed), at 12.3 min and $0.003 per PR.
  Terse or misleading descriptions weaken it. **A**.
- *ORION* (Fu et al., arXiv 2610.35223, 2026-10-26): it extracts the PR's intent plus AST impact analysis into
  per-function "structured oracles". RegBench-Py F1 is 0.61 (DeepSeek V3.2) and 0.56 (Claude 4.5 Haiku), above
  Testora, Codex and Claude Code. Of 9 regression candidates on 1,459 merged PRs, maintainers confirmed 8. **B**
  (preprint).
- *Just-in-Time Catching Test Generation at Meta* (Becker et al., arXiv 2601.22832, FSE 2026; Meta Engineering,
  2026-10-29). An "intent-aware" workflow infers the diff's intent and its risks, turns each risk into a mutant, and
  generates tests to catch it. Change-aware methods gave 4x the candidate catches of hardening tests. In production:
  74 serious privacy bugs caught before landing in H1 2026, and 60% true positives among engaged engineers. **B**.
- ContextCRBench (above): PR and issue descriptions gave larger gains than code context. **A-**.
- RevEngine's reviewer prompt has a "Completeness" lens: does the change deliver what its title and description
  claim, end to end (stubs, capabilities never exposed, files left out of packaging), plus an "Unexpected additions"
  lens. Its severity rule makes a defect in the very thing the change sets out to do high, even when it needs
  particular conditions. The swarm has a global "promise" task. **C**.
- OhMyBug reads a `ticket` field "as the author's stated intent" (plugin README). intent-review-agent (#2, high F1
  82.2, about 27 min per PR by its own ReviewBench issue #84) has published no method (Intent Lab blog, 2026-09-29).
  **C**.

**Targets.** NF: dotnet/android #0 (the designer is unresolved and the library is silently not rewritten),
agent-orchestrator #4/#17, Maui #3 (a platform path throws out of a discarded task). RL as well, since the obligation
gives the reviewer a second question to ask at a line it already flagged.

**Where in crucible.** `review_prompt()`: a short "What this change promises" block, built from `draft_text` (title
and body) and `clog` (commit subjects), separate from the House-style block, with an instruction to list the
obligations and check each before writing findings. Keep it in `lens_prompt()` too: today a lens "never reads the
draft". Today's style judgement of the description stays where it is.

**Cheap test ($0, then ~$25, can share an arm with entry 2).** At $0: read the 10 TRAIN PR bodies (not golden) and
mark which of the 13 missed items breaks an obligation the body states. If fewer than 3 do, stop. Otherwise run the
entry-2 arm with this block added, so both prompt changes share one $25 run, and report which items each part
reached by reading the findings' text.

**$/PR.** About 1-2k more prompt tokens per pass: **+$0.02 to +$0.05/PR.**

### 5. A hunk-by-hunk sweep with a narrow question per hunk

**What it is.** After the first look, the same conversation walks the changed hunks a group at a time, asking what
could be wrong in those lines, with their callers and tests, and what should have changed with them but didn't. The
existing bug sweep is a fresh call over the whole pass with a list of raised items. This sweep instead points the
model at a few lines at a time.

**Sources and evidence.**
- RevEngine `sweepMessage` (second-look mode "sweep"): its comment says that pointed at a small piece of code, a model
  finds problems it passed over while reviewing the change as a whole. It is optional; the registered configuration
  uses the plain second look. **C** (no ablation published).
- Lu et al. (ICML 2025): small, focused slices beat the raw diff (above). **A** for focus.
- *First Come First Served* (Fregnan et al., ESEC/FSE 2022, arXiv 2208.04259): human reviewers had 64% lower odds of
  finding a defect in the last file than in the first, for one of two seeded defect types. **A** (humans). *Lost in
  the Middle* (Liu et al., TACL 2024, arXiv 2307.03172): LLMs use information in the middle of a long context worse
  than at the ends. **A** (retrieval tasks, not review).
- **in-house, against.** crucible's bug sweep (a second look, two "where a first look stops" bullets) carried 1 high
  item on TRAIN and moved nothing on held-out. A second look that only repeats the brief is measured not to help.
  The hunk sweep's claim is that a narrower **scope** works where a repeated **brief** doesn't; that claim is
  untested.

**Targets.** RL (a second flaw at a line already looked at) and NF in large passes.

**Where in crucible.** It would replace `bug_sweep()` and `bug_sweep_prompt()`: same budget rules
(`bug_sweep_skip_reason`), but the prompt lists 3-6 hunks (from `diff.hunks_old_new`) per call instead of the whole
pass. Because `claude -p` calls are separate, "same conversation" becomes "the hunks plus the raised items at those
lines".

**Cheap test (~$10-15).** Run the sweep alone on the 10 TRAIN PRs, with the first passes taken from the review cache
if the r8train cache is kept (otherwise ~$27 for the full arm). Count new carries among the 13 and compare with the
old bug sweep's 1.

**$/PR.** About the old bug sweep's $0.36, plus more calls on big PRs: **+$0 to +$0.3/PR** if it replaces the sweep.

### 6. One review conversation over the whole diff, not isolated chunks

**What it is.** Give the reviewer the whole diff in one agentic conversation (RevEngine inlines up to 80,000
characters and lets the model read the rest with a tool), with an explicit "understand the system first, then trace
every change outward" method and a statement that stopping early is the usual failure.

**Sources and evidence.**
- RevEngine (same model as crucible): one seat, one conversation, plus a second look, then verify. High F1 73.3 at
  about $1 per review, against crucible's held-out 55.6 at $2.46. The prompt tells the reviewer that depth matters
  more than speed and to plan on using most of its turn budget. **B** (not the same PR sample, and many differences
  at once).
- Greptile v3 (2025-11-26): moving from a fixed pipeline to an open tool loop that can follow a call into a third file
  took the action rate from 34.75% to 59.24% (vendor metric, before/after, no controls). **B**.
- GitHub Copilot code review ("Better tools made Copilot code review worse", 2026-07-10): the same tools with
  coding-assistant instructions caught fewer issues at higher cost. The fix was review-shaped instructions: start
  from the diff, form specific questions, batch searches, read only known ranges. The production result was a cost
  cut of about 20% (quality reported as unchanged, no numbers). **B**.
- Against: SWR-Bench found its agentic reviewer (SWR-Agent) no better than a single-turn reviewer (F1 12.61 vs 12.49).
  **A**. So the agent loop alone isn't the gain; the instructions are.

**Targets.** NF where the cause sits in another chunk's file; WF.

**Where in crucible.** `diff.chunk(files, max_chars=45000)`: one constant. Raising it to ~80,000 makes most ReviewBench
PRs a single pass. Plus the method paragraph in `review_prompt()`.

**Cheap test (~$25).** `max_chars=80000` on the 10 TRAIN PRs, 1 round, scored as in entry 1. Mississippi (24 passes,
budget-cut) shows the risk: fewer, bigger calls may overrun the budget sooner.

**$/PR.** Fewer, longer calls: about **-$0.2 to +$0.3/PR**, depending on cache reuse. Measure it.

### 7. A catalogue of bug species as the first look's checklist

**What it is.** A short list of recurring high-severity defect shapes, mined from real misses, given to the first look
as questions. crucible already does this for nits (`NITS_NOTE`). The findings prompt has only the Security,
API/architecture and Docs bullets.

**Sources and evidence.**
- OhMyBug's "Bugarium" (<https://mcp.ohmybug.ai/bugs>, fetched 2026-11-25): bug species counted by sightings, each
  with a rule of thumb. Several are high-severity shapes that crucible's prompt doesn't name: one fact derived in two
  places, a fix applied to one copy only, a new member missing from a parallel registry, a second entry point that
  skips the check, a cache or lookup key that omits a dimension, a check-then-create race, a total computed over the
  wrong records. **C** (no recall data).
- BitsAI-CR (ByteDance, arXiv 2501.15134, FSE 2025 industry): a 219-rule taxonomy drives a fine-tuned detector plus a
  verifier, at 75.0% precision. AutoCommenter (Google, arXiv 2405.13565, AIware 2024): best practices keyed by
  guideline URL. It covered 68% of the URLs human reviewers cite, and 66% of the 50 most frequent were not
  linter-checkable. Both are **B**, and both are precision or coverage figures, not recall of serious bugs.
- Human inspection research. Dunsmore, Roper & Wood (IEEE TSE 29(8), 2003): of checklist, abstraction-driven and
  use-case reading, the checklist was most effective overall, and the abstraction-driven reading handled
  delocalized defects better. Porter, Votta & Basili (IEEE TSE 21(6), 1995): scenario-based reading found more
  defects than ad hoc or checklist reading (requirements documents). Gonçalves et al. (EMSE 2022): checklist effects
  were mixed and weak with mostly novice reviewers. **A** for humans; how far it transfers to LLMs is unknown.
- What humans miss: of 187 bugs missed in reviewed and merged PRs, 51% were semantic and 15.5% build (Khoshnoud et
  al., MSR 2022, arXiv 2205.09428). Mäntylä & Lassenius (IEEE TSE 35(3), 2009) and Beller et al. (MSR 2014) found that
  75% of review findings are evolvability, not function. Czerwonka et al. (ICSE-SEIP 2015) found that only about 15% of
  review comments point to defects. The functional share is where the high items are, and humans under-supply it.

**Targets.** NF, the shapes that need a reason to look elsewhere: parallel registry (the dotnet designer), second
entry point (obot CreateCredential on an existing credential), key or id format (entebus #32).

**Risk.** Each species written from a TRAIN miss is in-sample, which is how R4-R7 overfit dev. Write only species
that come from outside sources (the Bugarium list, the taxonomies above), never from TRAIN golden text.

**Where in crucible.** `review_prompt()`'s "Check these where the diff touches them" list: a "Correctness shapes"
bullet of 6-8 species, with or without `--nits`.

**Cheap test (~$25).** One 10-PR arm. Also count the bullets' hits on the 41 eval cases (about $20) to catch false
blocking.

**$/PR.** About 300 prompt tokens: **~$0.**

### 8. Executable "catching" tests generated from the change

**What it is.** Generate tests that tell the new behavior from the old, run them on both, and judge each difference
against intent (Testora, ORION, Meta's JiTTests, DiffTestGen). A failing test is near-perfect evidence.

**Sources and evidence.** Testora and ORION (**A**/**B**, entry 4). DiffTestGen (Hu, Cadar & Pradel, arXiv 2607.16024,
2026-07-17): it exposed behavior differences in 78.2% of 463 PRs, with union coverage of 90.7%. Meta JiTTest: 41
candidate catches sent to engineers, 8 true positives (4 serious), and assessors that cut review load by 70% (**B**).
"Fix-guided verification" (Jin & Chen, arXiv 2603.00539, 2026-02-28) runs a reviewer's proposed fix as a
counterfactual to filter over-correction (**B**).

**Fit.** Strong evidence for regressions, but ReviewBench gives no installed dependencies (the adapter runs
`--skip-checks`), and these systems take 12-15 min per PR. It is a better lever for real upstream PRs, where
crucible's verifier already runs probes, than for the High table.

**Targets.** NF for behavioral regressions.

**Where in crucible.** As a verifier-side probe generator (`verify_prompt`'s falsification step), not as a first look.

**Test.** Not on ReviewBench. On `crucible eval`'s bug cases, measure whether intent-derived probes raise blocking
recall (the eval cases run their checks).

**$/PR.** +$0.5 to +$2 where it runs.

### 9. Specialist agents by concern (security agent, tests agent, ...)

**Sources and evidence.** Qodo (2026-02-19, qualitative only, **C**). Uber uReview (2025-08-12): separate commenters
for bugs, best practices and AppSec, a grader, and category suppression; 75% rated useful, 65% addressed (**B**,
precision-side). cubic (2025-06-19): micro-agents cut false positives by 51% "without sacrificing recall" (**B**;
cubic is #23 on the ReviewBench High table at 35.8). RevAgent (arXiv 2511.00517): five category commentators plus a
critic, measured in BLEU (**B**, wrong metric). RevEngine "focus" seats (maintainability, tests) on cheap models,
tried on 5 PRs (**C**). Against: SWR-Bench's multi-agent CR-Agent scored F1 9.22 against 18.73 for the single-call
PR-Review, which the authors blame on interaction overhead and error propagation (**A**). Adversarial Review (arXiv
2608.18167) found that agent diversity mattered more than more independent samples, but with no recall numbers
(**B**).

**Reading.** The evidence for **splitting by concern** is mostly precision or qualitative, and one controlled result
is negative. The diversity it buys is better bought through entry 1's seats.

**Where/test/$.** If tried, as seat 2's brief in entry 1 (variant c), not as a separate stage.

### 10. Learning rules from misses and feedback

**Sources and evidence.** Bugbot learned rules (Cursor, 2026-04-08): reactions, replies and human comments that flag
missed bugs become candidate rules, promoted once enough signal accumulates. 44,000 rules across 110,000 repos;
resolution rate 78.13% on 50,310 public PRs (judged by an LLM). **B**. Uber's category suppression and AutoCommenter's
URL suppression (54% -> 80% useful) are precision-side **B**.

**Fit.** crucible's `learn` and `memory_text` exist. A "missed by crucible, raised by the maintainer" signal (ROADMAP
line 1: recall on real PRs) could feed `memory_text`. That is slow and per-project, with no effect on ReviewBench.
Long term only.

### 11. Don't add more filtering, and don't vote candidates away

Guardrail, not a lever. Lu et al.: the validator cost 11 points of key-bug inclusion. Sourcery (2024-02-26): a
generic post-filter agent moved usefulness from 42% to 43%; only per-criterion validators helped (to ~60%), on
usefulness, not recall. Bugbot's voting dropped single-pass findings, which is the opposite of entry 1. Huang et al.
(ICLR 2024, arXiv 2310.01798): LLMs don't reliably self-correct without outside feedback, which supports crucible's
separate, falsification-based verifier. On TRAIN no high item was lost to verification, so the verifier is not the
constraint now. With entries 1-2 the verifier will see 1.5-2x the candidates: watch the tier escalation rate and
"dropped true" in the eval.

### 12. More test-time compute per PR

**Sources and evidence.** OhMyBug's own OMBench (85 held-out changes, 742 known bugs, vendor-run): fast 76.5% (1.9
min) vs deep 86.1% (4.6 min) known-bug recall (**B**). intent-review-agent runs about 27 min per PR (ReviewBench issue
#84). OpenAI: recall fell faster with a lower thinking budget on model-written code than on human-written code (**B**,
figures without numeric labels). Naptime: room for reasoning improved accuracy (**B**).

**Fit.** crucible already runs effort "high", within ReviewBench's per-PR timeout (900 s unless raised; intent asked
for 3600). Entries 1 and 5 are the structured way to spend more compute. Raising effort alone is the unstructured
way, and was not cheaper per caught bug in the 11-09 Fable comparison.

## Top 3, as short designs

### Design A: seat 2 (entry 1), paid for by the bug sweep

- `CRUCIBLE_SEATS` (default 1: byte-identical prompts and cache keys). With 2, after seat 1's passes, `run_review`
  runs `run_pass` again over the same chunks with: the other review model (`pick_models` gives Opus; seat 2 takes
  Sonnet 5.5, or Opus when Sonnet is seat 1), each chunk's file order and hunk order reversed, `lens_prompt()` applied
  (no house-style or description sections), and a seat-tagged cache key.
- Proposals from both seats go to `dedupe()`, where the first seat's item stays the representative. Each kept item
  records `seat` in review.json, so a run can count what seat 2 alone carried. Then `verify_tiered()` as usual. No
  voting drop.
- Budget: seat 2 gets at most 30% of the budget (its own `ShareBudget`), riskiest chunk first, and stops when its
  share is spent. Its passes count toward the 50% spend rule. With seats=2, `bug_sweep_mode()` defaults to off.
- Falsifiers: seats=1 gives the same prompts as today (cache-key test). A seat-2 duplicate of a seat-1 finding never
  replaces it. A failed seat-2 pass doesn't mark the review failed (seat 1 covered the files).
- Test: entry 1's 10-PR arm (~$25-30), plus the $0 union read of the stored rounds first. Pre-registered bar: ≥3
  new carries of the 13, ≤1 loss, 0 new golden-false high, mean ≤ $3.0/PR. Only then a held-out run, and the
  held-out 50 has now been used twice, so say so with the number.

### Design B: recall-first contract plus intent obligations (entries 2 and 4, one prompt change)

- `review_prompt()`: replace the "at most 10 ... An empty list is a good answer" sentence with: report every problem
  you can support, a second different failure at a line already flagged is its own finding, and merge only the same
  fault with the same fix. `FINDINGS_SCHEMA` `maxItems` goes 10 -> 20. The verifier holds precision.
- A "What this change promises" block, built from the description's title and body and the commit subjects (data,
  not instructions; the existing untrusted-text handling applies). The reviewer lists the obligations, checks each end
  to end (reachable, registered, every platform or variant, every consumer of a moved or renamed thing), and reports
  an unkept one as critical (already in SEVERITY_DEFS). Kept in `lens_prompt()`.
- Without `--nits` and with the knob off, prompts are unchanged (the same byte-identical rule as `NITS_NOTE`). Ship
  it behind `CRUCIBLE_RECALL_CONTRACT=1` until measured.
- Test: the $0 reads of entries 2 and 4, then one 10-PR arm (~$25) plus the 9 clean eval cases (~$4) for false
  blocking. Bar as in design A, plus 0 false blocking on clean cases.

### Design C: mentions context (entry 3), $0 replay first

- `mentions_note(repo, sha, files, ch)`: tokens from the pass's removed and added lines (string literals with a `/`
  or `.`, ids of shape `[A-Z]+-\d+`, identifiers from `docrefs.touched_names`), `git grep -n -F` at HEAD, excluding
  changed files, lockfiles and vendored or generated trees; at most 5 lines per token and 60 per pass. Each line comes
  with its file:line and the token, and the note says these are readers of what changed.
- Called in `run_pass` beside `callers_note`, `fields_note` and `docs_note` (under `--nits`, like them, or for all
  runs once measured).
- Falsifiers: a token used in more than N files is dropped (too common to be one flaw's reader, as with
  `NAME_MAX_FILES`). A token only in the changed files gives no note. Mutation-check each rule, as with
  `fields_note`.
- Test: replay at $0 on the 10 TRAIN PRs' diffs and the 1,047 public commits. Proceed to a $25 arm only if ≥2 of the
  5 NF items are reached and the lines per PR stay under the cap.

All three can be measured on the same 10 PRs. Run them as separate arms, never stacked in one run, or no single
change can be credited with a gain, the lesson of R7 and R8. With about $25 per arm, the order is C's $0 replay, then
A, then B, then C's arm if its replay passed.

## Prior art

Leaderboard entries and their own write-ups:
- ReviewBench leaderboard, <https://review-bench.ai> (fetched 2026-11-25); ReviewBench issues
  [#84](https://github.com/review-bench/ReviewBench/issues/84) and [#102](https://github.com/review-bench/ReviewBench/issues/102)
  (intent-review-agent timings and scores).
- OhMyBug: <https://ohmybug.ai/>, <https://ohmybug.ai/faq.html>, plugin README
  <https://github.com/OhMyX-AI/ohmybug-plugin/blob/main/README.md>, Bugarium <https://mcp.ohmybug.ai/bugs> (all fetched
  2026-11-25).
- Intent Lab, "Building Review Agents for High-Quality Verification", 2026-09-29,
  <https://intentlab.ai/blog/building-review-agents-for-high-quality-verification>.
- Laude Institute, RevEngine, Apache-2.0, <https://github.com/laude-institute/rev-engine> (README, docs/REVIEWBENCH.md,
  src/prompts.ts, experiments/prototypes/swarm/README.md; read at ca5a2ed, 2026-11-24).
- GitHub Copilot code review: agentic architecture changelog, 2026-03-05,
  <https://github.blog/changelog/2026-03-05-copilot-code-review-now-runs-on-an-agentic-architecture/>; "Better tools
  made Copilot code review worse", 2026-07-10,
  <https://github.blog/ai-and-ml/github-copilot/better-tools-made-copilot-code-review-worse-heres-how-we-actually-improved-it/>.
- OpenAI, "A Practical Approach to Verifying Code at Scale", 2025-12-01,
  <https://openai.com/safety-alignment/scaling-code-verification/>.

Other reviewers' engineering write-ups:
- Cursor, "Building a better Bugbot", 2026-01-15, <https://cursor.com/blog/building-bugbot>; "Bugbot learning",
  2026-04-08, <https://cursor.com/blog/bugbot-learning>.
- Anthropic, "Bringing Code Review to Claude Code", 2026-03-09, <https://claude.com/blog/code-review>; docs
  <https://code.claude.com/docs/en/code-review>.
- Greptile, "Greptile v3, an agentic approach to code review", 2025-11-26,
  <https://www.greptile.com/blog/greptile-v3-agentic-code-review>; Martian benchmark write-up, 2026-07-30,
  <https://www.greptile.com/content-library/greptile-martian-code-review-benchmark>.
- CodeRabbit, context engineering (2025-07), <https://coderabbit.ai/blog/context-engineering-ai-code-reviews>; Opus 5
  model review, <https://coderabbit.ai/blog/opus-5-model-review>; Opus 5.5 coverage (IT Brief, 2026-10-06),
  <https://itbrief.com.au/story/coderabbit-says-opus-5-5-beats-baseline-on-bug-review>.
- Augment, "How we built a high quality AI code review agent", 2026-03-10,
  <https://augmentcode.com/blog/how-we-built-high-quality-ai-code-review-agent>.
- Qodo, "Single-agent vs multi-agent code review", 2026-02-19,
  <https://www.qodo.ai/blog/single-agent-vs-multi-agent-code-review/>.
- Cognition, "Devin Review", 2026-01-21, <https://cognition.com/blog/devin-review>.
- Uber, "uReview", 2025-08-12, <https://www.uber.com/blog/ureview/>.
- Ellipsis, "Lessons from 27 months building LLM coding agents",
  <https://nickbradford.substack.com/p/lessons-from-27-months-building-llm>.
- Sourcery, "Optimizing review comments for usefulness", 2024-02-26, <https://sourcery.ai/blog/improving-llm-responses>.
- cubic, "Learnings from building AI agents", 2025-06-19, <https://www.cubic.dev/blog/learnings-from-building-ai-agents>.
- Graphite, <https://graphite.com/blog/problems-with-ai-code-review>, <https://graphite.com/blog/how-graphite-uses-claude>.
- Microsoft, "Enhancing code quality at scale with AI-powered code reviews", 2025-07-14,
  <https://devblogs.microsoft.com/engineering-at-microsoft/enhancing-code-quality-at-scale-with-ai-powered-code-reviews/>.
- Meta, "Catching bugs before they land: JiTTesting", 2026-10-29,
  <https://engineering.fb.com/2026/10/29/security/catching-bugs-before-they-land-jittestings-human-on-the-loop-approach-at-full-scale/>.
- Google Project Zero, "Project Naptime", 2024-06-20, <https://projectzero.google/2024/06/project-naptime.html>.

Papers (ML and LLM review, bug finding, benchmarks):
- Lu et al., "Towards Practical Defect-Focused Automated Code Review", ICML 2025, arXiv 2505.17928.
- "SWR-Bench: Assessing LLM Performance in Real-World Code Review Comment Generation", FSE 2026, arXiv 2509.01494.
- Sun et al., "Improving LLM-Based Go Code Review through Issue-List Generation and Context Augmentation", arXiv
  2606.01859, 2026.
- Stone, "A Single LLM Is an Incomplete Code Reviewer", Zenodo 20519585, 2026-06-03.
- Hu et al., "Benchmarking LLMs for Fine-Grained Code Review with Enriched Context in Practice" (ContextCRBench), arXiv
  2511.07017, 2025.
- Pradel, "Testora: Using Natural Language Intent to Detect Behavioral Regressions", ICSE 2026, arXiv 2503.18597.
- Hu, Cadar & Pradel, "DiffTestGen", arXiv 2607.16024, 2026.
- Fu et al., "Behavioral Regression Detection for Pull Requests via Structured Oracles" (ORION), arXiv 2610.35223, 2026.
- Becker et al., "Just-in-Time Catching Test Generation at Meta", FSE 2026 companion, arXiv 2601.22832.
- Vijayvergiya et al., "AI-Assisted Assessment of Coding Practices in Modern Code Review" (AutoCommenter), AIware 2024,
  arXiv 2405.13565.
- "BitsAI-CR: Automated Code Review via LLM in Practice", FSE 2025 industry, arXiv 2501.15134.
- "Impact of LLM-based Review Comment Generation in Practice" (RevMate at Mozilla and Ubisoft), arXiv 2411.07091.
- Li et al., "CodeReviewer: Pre-Training for Automating Code Review Activities", ESEC/FSE 2022, arXiv 2203.09095.
- Li et al., "RevAgent: Issue-Oriented Agent-Based Framework for Automated Review Comment Generation", arXiv 2511.00517.
- Zhang et al., "Code Review Agent Benchmark" (c-CRAB), arXiv 2603.23448, 2026.
- Pereira et al., "CR-Bench", arXiv 2603.11078, 2026.
- Jin & Chen, "Are LLMs Reliable Code Reviewers? Systematic Overcorrection in Requirement Conformance Judgement", arXiv
  2603.00539, 2026.
- Qiu & Gill, "Adversarial Review: Structured Disagreement for Grounded Agentic Code Review", arXiv 2608.18167, 2026.
- McAleese et al., "LLM Critics Help Catch LLM Bugs" (CriticGPT), arXiv 2407.00215, 2024.
- Hu et al., "Large Language Model-Powered Smart Contract Vulnerability Detection: New Perspectives" (GPTLens), arXiv
  2310.01152, 2023.
- Li, Dutta & Naik, "IRIS: LLM-Assisted Static Analysis for Detecting Security Vulnerabilities", arXiv 2405.17238.
- Chen et al., "LocAgent: Graph-Guided LLM Agents for Code Localization", arXiv 2503.09089, 2025.
- Xia et al., "Agentless: Demystifying LLM-based Software Engineering Agents", arXiv 2407.01489, 2024.
- Wang et al., "Self-Consistency Improves Chain of Thought Reasoning in Language Models", ICLR 2023, arXiv 2203.11171.
- Liu et al., "Lost in the Middle: How Language Models Use Long Contexts", TACL 2024, arXiv 2307.03172.
- Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR 2024, arXiv 2310.01798.

Human code review and inspection:
- Mäntylä & Lassenius, "What Types of Defects Are Really Discovered in Code Reviews?", IEEE TSE 35(3), 2009.
- Bacchelli & Bird, "Expectations, Outcomes, and Challenges of Modern Code Review", ICSE 2013.
- Beller et al., "Modern Code Reviews in Open-Source Projects: Which Problems Do They Fix?", MSR 2014.
- Czerwonka, Greiler & Tilford, "Code Reviews Do Not Find Bugs", ICSE-SEIP 2015.
- Khoshnoud et al., "Which bugs are missed in code reviews", MSR 2022, arXiv 2205.09428.
- Fregnan et al., "First Come First Served: The Impact of File Position on Code Review", ESEC/FSE 2022, arXiv 2208.04259.
- Gonçalves et al., "Do explicit review strategies improve code review performance? Towards understanding the role of
  cognitive load", EMSE 2022, doi 10.1007/s10664-022-10123-8.
- Dunsmore, Roper & Wood, "The Development and Evaluation of Three Diverse Techniques for Object-Oriented Code
  Inspection", IEEE TSE 29(8), 2003.
- Porter, Votta & Basili, "Comparing Detection Methods for Software Requirements Inspections: A Replicated
  Experiment", IEEE TSE 21(6), 1995.
- Basili et al., "The Empirical Investigation of Perspective-Based Reading", EMSE 1(2), 1996.

## Caveats

- Vendor figures (OhMyBug's OMBench, Bugbot's resolution rate, Greptile's action rate, Claude Code Review's internal
  rates) are self-reported on private data. They show direction, not size.
- The ReviewBench rows are 219 PRs x 3 rounds. crucible's figures are 50 or 60 PRs x 1 round. Comparisons in "Where
  crucible looks worse" are like-for-like in metric, not in sample.
- The $/PR figures are estimates. Before any arm, take the real per-kind split from `tokens_by_kind` in the stored
  r8train review.json files ($0).
- The TRAIN tests are in-sample by design: the 10 PRs were picked for their misses, so regression to the mean favors
  every arm. A lever earns a held-out run only by passing the pre-registered bar, and only the held-out run decides.
- No golden item of heldout50 or final84 was read for this file. No paid review or ReviewBench run was made.
