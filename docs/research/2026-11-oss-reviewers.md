# What other reviewers do to raise more real bugs (open-source survey, 2026-11-25)

The question: crucible's high-severity precision on the sealed held-out 50 is 94%, but its high-severity recall is
about 39% (R8: 22 of 60, macro 39.4, F1 55.6, about #23 of 25 on review-bench.ai's High table). On TRAIN, 9 of 13
missed high items were never raised (5 with no finding in the file, 4 with a finding on the right line that made
another claim), 2 sat in the wrong file although crucible's own text named the right place, and 2 were cut by the
budget. The two R8 levers (text-named sites and the bug sweep) did not move held-out high recall. The gap is
first-look detection.

This survey reads the code and docs of open-source reviewers, and of the open entries on the ReviewBench board, for
mechanisms that make a first look raise more real high-severity bugs. johnr's brief: borrow, don't steal, and don't
anchor on crucible's design. Where the evidence says another design does better, this note says so.

Method: shallow clones, read only, no code run. No ReviewBench or paid runs ($0). No FINAL or held-out golden items
were read. Inside the ReviewBench repo only `docs/`, `agents/` and `examples/` were read, never `golden/` or `corpus/`.
Board figures come from `review-bench.ai/api/leaderboard` and `/api/leaderboard/metrics?severities=High`, fetched
2026-11-25. Short quotes from AGPL and proprietary sources (Kodus, Anthropic's claude-security plugin) are here only
as citations of an idea. Their wording must not be pasted into crucible's prompts or code; only MIT, Apache-2.0 and BSD
text may be adapted, with attribution in the file (the appendix lists each licence). Several repositories (TraceHound,
zeroshot, barsurfer, Kodus, SourceAnt, OpenCodeReview, pr-agent and the small ones) were read by two survey
subagents. Their key numbers and quotes were spot-checked against the files by hand.

## 1. What the board says before any code is read

Three facts from public data change how the rest should be read.

**(a) On this board, recall follows volume, and precision barely moves.** High-severity grounded recall by entry,
with the mean comments per PR at each severity (`commentsPerPr`, all-severity endpoint):

| entry | high P / R / F1 | comments per PR (H / M / L) | total per PR |
|---|---|---|---|
| #1 OhMyBug | 92.0 / 75.6 / 83.0 | 2.8 / 14.5 / 19.7 | 37 |
| #2 intent-review-agent | 92.0 / 74.4 / 82.2 | 2.1 / 8.2 / 7.4 | 18 |
| #4 Copilot code review, Max | 96.8 / 62.2 / 75.7 | 0.9 / 3.9 / 2.3 | 7 |
| #5 Laude RevEngine (Opus 5.5, open source) | 92.8 / 60.6 / 73.3 | 0.7 / 4.7 / 6.0 | 11 |
| #9 Klaussy, Opus 5.5 | 93.3 / 55.2 / 69.3 | 1.4 / 7.4 / 17.2 | 26 |
| #11 block/review, Sol+Opus panel (open source) | 94.3 / 53.5 / 68.2 | 0.5 / 2.7 / 2.7 | 6 |
| #20 Cursor | 96.0 / 44.5 / 60.9 | 0.3 / 1.0 / 0.4 | 2 |
| #24 Greptile | 95.2 / 20.2 / 33.4 | 0.1 / 0.7 / 1.4 | 2 |
| crucible R8, held-out 50, 1 round | 94.4 / 39.4 / 55.6 | 0.4 high-matched; 6.2 total kept | 6 |

Every entry sits at 91-99 high precision. What separates #1 from #24 is recall, and recall tracks how many claims an
entry makes. crucible already has top-board precision. Its precision has room to fall several points if that buys
recall: at P 92, R 60 gives F1 72.6, about #6.

**(b) The golden set is what other LLM reviewers raise.** `docs/METHODOLOGY.md` §5.5 (MIT) breaks the 219-PR golden
set down by producer. Of the high and medium TPs, 46.5% came from `llm_review:claude-sonnet-4.6`, 43.6% from
`ccr:gpt-5.5` (an LLM code-review system), 6.7% from `ccr:claude-opus-4.7`, 1.1% from human review comments, and
0.3% from Semgrep. Two consequences follow:
- Static analysers are not a recall lever here. Semgrep produced 8 of 2,565 TPs, and CodeQL and the language linters
  listed in `docs/EXTRACTION.md` §5 contributed none that survived. The Semgrep and CodeQL bug classes are fine as
  checklist text (§3, T13), but running them buys almost nothing on this board.
- The golden items are what an exhaustive single-pass LLM reviewer writes down: Sonnet 4.6 made 6.7 claims per PR at
  82% TP, and GPT-5.5 4.6 per PR at 90%. A reviewer that writes down what it noticed matches this set. A reviewer that
  writes down only what it would block on does not. The authors say so (§5.5): "A candidate reviewer whose earlier
  output contributed golden findings may be graded partly against its own prior output".

**(c) Reasoning effort is a measured lever on the board itself.** The same agent at several efforts, high recall:
Copilot Lite / Balanced / Max = 50.9 / 58.2 / 62.2. Codex GPT-5.6 Sol xHigh / Max = 51.4 / 55.3, and its
all-severity recall at Low / Medium / High / xHigh / Max = 9.7 / 13.7 / 15.8 / 17.7 / 18.5. Precision stays within
2 points across those efforts. crucible runs its review passes at `--effort high` (`util.claude` default).

**Where crucible looks worse, plainly.** On the held-out 50, crucible's 39.4 high recall is below single-agent
baselines that do much less: Codex Sol Max 55.3, Klaussy Sonnet default 43.9, Cursor 44.5. It is also below the one
open-source single-seat entry, RevEngine, at 60.6. RevEngine is one Opus 5.5 conversation over the whole PR, plus a
second look in the same conversation and one batched verifier call. Its README puts that at about $1 per review,
against crucible's $2.46. The samples differ (50 PRs, 1 round, against 219 PRs, 3 rounds), so the comparison has
error bars of about ±10 points. Even so, crucible's extra machinery (chunked passes, per-finding tiered
verification, nit tier, sweeps, sites) is not buying first-look recall. §2 lists the design differences that the
code shows.

## 2. crucible against the two open-source board entries, side by side

| | crucible (R8) | Laude RevEngine (#5, Apache-2.0) | block/review (#11, Apache-2.0) |
|---|---|---|---|
| unit of review | per pass of ≤45k chars of diff; each pass sees only its own files' diff plus the file list | the whole PR in one agent conversation; whole diff in the prompt up to 80k chars, else a `read_diff` tool | three lens panelists, each over the whole diff, × 2 models (GPT-6.1 Sol, Opus 5.5) |
| what the prompt asks for | "Report only real problems … Give at most 10 findings, ranked; merge findings that share a root cause. An empty list is a good answer." | "Be exhaustive: report every problem you can support … A thorough review of a change of a few hundred lines usually has ten or more findings" | "Assume the other panelists return no candidates: report every supported issue … Keep reviewing after the first candidate." |
| same flaw, several places | one finding + `also_at` (verified per site) | "The same defect in two files or two functions is also two findings, one at each place" | "When a defect occurs in several places, report one candidate per affected file" |
| two flaws, one line | merged if "they share a root cause" | "Two different problems in the same lines are two findings" | "Different defects in the same file are not duplicates" |
| order of work | read the hunk's function, grep callers, open tests | 1 understand the system (README, design docs, callers, data); 2 the change and its stated intent; 3 trace every change outward with search; 4 each lens in turn; 5 a coverage check before submitting | a procedure per lens (producer → consumer traces, failure injection, attacker paths) and a `coverage_summary` that maps every changed hunk to what was checked |
| PR title/body | judged as a draft for house style and length (`PR_DRAFT.md`) | read as the intent: "a defect in the very thing the change sets out to do is also high" | given to two lenses as untrusted evidence; withheld from the security lens on purpose |
| second look | a separate fresh call per pass (nit sweep, bug sweep) that sees only the raised titles; skipped above 50% spend; bug sweep ≤5 items, results become nits | in the same conversation, with the reviewer's tool history: "Changed files you have not opened yet" listed by name | none; diversity comes from the 6 panelists instead |
| verification | one call per finding, Haiku then Sonnet/Opus; keep only if it "survives AND is caused by this change AND is reachable in real use" | one call for all findings; `confirmed` / `rejected` / `uncertain`, and agent mode keeps `uncertain` | a coordinator drops only "with concrete counter-evidence … A candidate you tried and failed to disprove is kept"; a judge on the other model re-reads every drop and restores the real ones |
| reasoning effort | high | model default (the README's Opus run) | high by default |
| $ per PR | 2.46 (held-out mean) | "about $1" (Opus, README) | not published |

## 3. The catalogue, ranked by evidence

Ranked by the strength and relevance of the evidence that the technique raises real high-severity recall, not by how
easily it fits crucible. Evidence levels: **M** measured on ReviewBench or a published A/B; **C** a claim by the
project, with a reason, but no number; **I** inferred from design or composition only.

Miss classes (TRAIN, eval/NOTES 2026-11-24): **NF** no finding in the file (5), **RL** right line, another claim (4),
**WF** wrong file, place named in the text (2), **BU** cut by the budget (2).

Each test design runs on **the 10 TRAIN PRs that hold the 13 misses** (nestjs-yalc, dotnet/android, obot,
ia-dev-environment, Maui, agent-orchestrator, entebus, swarmbase, katana, mississippi), 1 round, the R7/R8 harness.
Control is the two stored rounds that already exist on those PRs (`runs/r8base` at 8a5d035 and `runs/r8train` at
fb540f5), so only the treatment arm is paid for: about 10 × $2.5 = $25. Score with the judge's matching step only
(RevEngine `scripts/match.ts` / `JUDGE_MODE=match`: the grounded P/R that the board ranks by come from matching
alone, which takes about a minute for 25 PRs). Report every high item on those 10 PRs (the 13 base misses and the
items already found there), so that losses show as well as gains: R8 lost 3 found items to one-round noise while
gaining 4. In-sample by construction: a lever that passes goes to a held-out run before any claim.

**The ranking.** The IDs (T1…) are stable names; this table is the order. Rank is by the evidence for more real
high-severity recall, then by fit to crucible's miss classes. Cost is per PR against R8's $2.46.

| rank | ID | technique | evidence | targets | $/PR |
|---|---|---|---|---|---|
| 1 | T2 | independent readings, unioned (another sample, model or narrow brief) | M: TraceHound on ReviewBench (+3.4 R, P up); Kodus heavy +13-17 R; RevEngine and Bugbot claims; crucible's own R8 gain/loss churn | NF, RL | +1.0-1.5 |
| 2 | T1 | ask for everything supportable; drop the restraint language and caps | M: RevEngine `ad13adf` (several points of R, P flat); Bugbot, Codex, Kodus, block designs | RL, NF, WF | +0.3-0.6 |
| 3 | T3 | one conversation over the whole change: system first, trace outward | M as RevEngine's package (60.6 high R at ~$1); parts unmeasured | NF, BU | +0.2-0.5 |
| 4 | T6 | keep unless disproved, batched, drop audit | M: TraceHound filters cost 8-15 R; Kodus and block designs | protects 1-3 | −0.8 to +0.1 |
| 5 | T4 | higher reasoning effort on review passes | M on the board for other vendors (+4 to +11 high R) | RL, NF | +0.5-1.0 (unmeasured) |
| 6 | T5 | an outward "consumers and siblings" reading | C (RevEngine swarm, block, Anthropic claude-security); Kodus's cross-file lenses inside its +13-17 | NF, WF | +0.4-0.8 |
| 7 | T10 | narrow lens readings beside the generalist | M (Kodus) as additions; mixed as replacements (block < RevEngine; barsurfer, TraceHound lens losses) | RL, NF | +1-2 as seats |
| 8 | T9 / T8 | a second look pointed at hunks, flagged files or unopened files | M as parts of RevEngine and TraceHound (+3.1 R); Kodus turns its rescue off for Opus | RL, BU | +0.1-0.6 |
| 9 | T7 | the PR's stated intent as a spec; an intent defect is high | C (RevEngine, zeroshot `hunt_claims`, pr-agent ticket compliance) | RL, NF | ~0 |
| 10 | T11 | leads or doubts, then followers | C (Anthropic claude-security, SourceAnt, Kodus rescue) | NF, RL | 0 to log, +0.3-0.8 to follow |
| 11 | T15 | deterministic per-file × rule coverage | M narrow (Kodus rules 40-58% → 91-100% occurrence recall) | rules, BU | +0.1-0.4 |
| 12 | T12 | probe the reviewer about its misses (diagnosis) | M as a tool (RevEngine) | decides between T3/T5 and T1/T11 | 0 in production |
| 13 | T13 | static-analysis bug classes as checklist text | I; Semgrep is 0.3% of golden TPs | none measurable | 0 |
| 14 | T14 | a repo map | I; Bugbot found dynamic (tool) context better | NF | 0-0.2 |

### T1. Ask for everything supportable; drop the restraint language (M, C ×3)

- **Sources.** RevEngine `src/prompts.ts` `REVIEWER_SYSTEM`, "What to report" section (Apache-2.0). Commit `ad13adf`
  (2026-10-15): "Drop the rule that being unable to check something is not a finding … In both the reviewer and
  verifier prompts it lowered recall on the benchmark's test set by several points, with precision unchanged, so the
  reviewer appears to read it as a reason to hold back findings it cannot fully prove." Cursor, "Building a better
  Bugbot" (blog, 2026-01-15, proprietary product): the agentic version was "too cautious", so prompts were made "more
  aggressive to flag potential issues"; newer versions "caught more bugs without a comparable rise in false
  positives". OpenAI Codex `codex-rs/prompts/templates/review/rubric.md` (Apache-2.0): "Output all findings that the
  original author would fix if they knew about it … Do not stop at the first qualifying finding. Continue until
  you've listed every qualifying finding." block/review `review/panelists.go` `panelistContract` (Apache-2.0): "Keep
  reviewing after the first candidate"; the host, not the model, filters on confidence. **Kodus**
  (`kodustech/kodus-ai`, AGPL-3.0 core, ideas only), `libs/code-review/infrastructure/agents/prompts/prompt-builder.ts`
  `DEFECT_HUNT_MINDSET`: "Assume every change is broken until you prove it is safe. Your default is to report — you
  need evidence to DISMISS, not evidence to report … High-recall mode: … emit the finding instead of self-censoring it.
  A later verifier will filter unsupported claims." Its reporting threshold: "report any defect the changed code makes
  you suspect, as long as you (1) anchor it to a specific changed line and (2) name the kind of failure … You do NOT
  need to prove the exact triggering input … Cross-file claims are welcome". It also asks for a one-line "Premise →
  Path → Verdict" note for every hunk dismissed as well as reported. Its own finder evals (`evals/investigation`,
  15 PRs, 2 runs per model) measure the finder at this setting. Anthropic's
  claude-plugins-official `code-review` (Apache-2.0) is the counter-example: "If you are not certain an issue is
  real, do not flag it", a precision-first design with no board entry.
- **How it works.** The discovery prompt asks for every problem the reviewer can support and leaves filtering to
  verification. It names how many findings a thorough review usually has, splits two flaws on one line and one flaw
  in two places into separate findings, and drops the phrases a model reads as "hold back".
- **What in crucible's prompt does the holding back** (`review.py` `review_prompt`): "Report only real problems", "Give
  at most 10 findings, ranked", "merge findings that share a root cause", "An empty list is a good answer" (in the
  review prompt and both sweep prompts), the security line "Flag only with a concrete path from untrusted input to the
  sink; 'could be unsafe' is not a finding", and the required `caused_by_this_change` / `reachable_in_real_use`
  booleans, which make the reviewer pre-judge what the verifier judges anyway. RevEngine's `ad13adf` is a measured case
  of exactly this kind of sentence costing recall at no precision gain.
- **Targets.** RL (4: "merge findings that share a root cause" and the 10-cap push the reviewer to stop at one flaw per
  place) and NF (5). Also helps WF, since "the same defect in two files is two findings" puts one at the fault site.
- **Where.** `review.py` `review_prompt` (the "Report only real problems … An empty list is a good answer." paragraph
  and the security bullet), `FINDINGS_SCHEMA` `maxItems: 10` (→ 25 or none) and its two booleans (move them to the
  verifier, which already decides both). Gate the change behind `--nits` or a new `CRUCIBLE_RECALL=1`, so the upstream
  `crucible review` default keeps its maintainer-facing bar.
- **Test.** Arm A: the T1 prompt only. Count high items found on the 10 PRs, high precision, findings per PR before and
  after verification, and how many dropped findings the verifier logs. Pass if at least +2 of the 13 missed come in
  with no loss beyond the known variance (R8 lost 3 found items to noise) and high P ≥ 90. Watch the clean eval cases
  (`crucible eval --cases clean-`, about $6) for false blocking, since T1 will raise more blocking candidates.
- **$/PR.** About +$0.3-0.6. More candidates reach per-finding verification (about $0.10 each on Haiku, more when
  escalated). The review passes themselves cost about the same, since the reviewer reads the same code. Combined with
  T6 (batched verification) the net is negative.

### T2. Independent seats, unioned (M, C)

- **Sources.** RevEngine commits `0df5787` and `7ef89d9` (swarm): "Two runs of the swarm find quite different
  problems, so a second copy of each agent finds problems the first missed"; "a second copy of every agent found
  problems the first missed without lowering precision, on the untuned test pull requests as much as on the tuned
  ones". The seat model in `src/review.ts` (`config.models` → one seat each, `Promise.allSettled`, union, then
  verify). Experiment queues `opus-astra-5.queue` and `four-seat-5.queue` (two and four seats across vendors). Cursor
  Bugbot (blog): "eight parallel passes, each with a randomized diff order", combined by majority vote, which it
  calls one of the most effective early quality improvements. block/review: every lens once per model (`sol-opus`,
  6 panelists). ReviewBench's own golden set was built as a union of 5 LLM producers (§1b). **TraceHound**
  (`sunnybagal/tracehound`, MIT, `docs/bench/reviewbench.md`, `results.md` §5), measured on ReviewBench's 25 test PRs
  with its judge: `pool-raw` run twice with the cache cleared and unioned (`pool-raw-x2`) took grounded recall from
  9.0 to 12.4 and precision from 70.6 to 76.3. On its own 40-PR dev set, no Critical item was missed by both of two
  runs, and on 29 held-out TS PRs the union of its reviewer and Haiku 5.5 caught 18 of 31 against 12 and 14 alone.
  The Open Engine's zeroshot `code-review` template (MIT, `src/native_v2_templates/code_review.rs`) runs the same
  unit prompt on Opus 5.5 and GPT-6.1 Sol per unit (`unit_broad_a` / `unit_broad_b`). **Kodus heavy mode** (idea
  only: the code is under `libs/ee/heavy-mode/`, proprietary) runs nine narrow lens readings beside the generalist,
  each capped at 3 steps and 4 findings, and unions them before verification. Its calibration file
  (`evals/heavy-recall/targets.json`, 2026-11-02, 15 PRs, 2 runs each) gives recall against balanced mode
  (`evals/investigation/targets.json`): Sonnet 5.5 0.388 → 0.562, GPT-6 Sol 0.489 → 0.622, Kimi 0.483 → 0.626,
  DeepSeek 0.391 → 0.528. Precision moves −15 to +1 points, mean findings per PR on Sonnet go 2.87 → 5.47, and tokens
  cost 1.3-2.1×. **SourceAnt** (MIT, `src/core/review/planning.py` `READING_FOCUSES`, premium plan) runs 3 independent
  discovery readings per model, each with a different focus (whole change; callers, runtimes and dependencies; one
  requirement at a time), and unions them. It publishes no numbers.
- **How it works.** Run N readings of the whole change that know nothing of each other, take the union, dedupe,
  verify. A reading can differ by sample (TraceHound, RevEngine copies), by model (zeroshot, block, RevEngine seats),
  by diff order (Bugbot) or by a narrow brief (Kodus heavy, SourceAnt focuses, RevEngine swarm tasks). Bugbot used votes to filter. For recall the
  union is the move, and crucible's verifier already does the filtering, so no vote is needed.
- **Why it should beat crucible's sweeps.** crucible's two sweeps are second looks that are told what was raised and
  asked for more. RevEngine found that "A model asked to look again in the same conversation tends to resubmit at
  once" (`review.ts` comment above `followUpSection`), and it runs its follow-up in a new conversation that is told to
  "do your own reading of the change from the start". An independent seat samples a different reading. A second look
  that sees the first reading's list mostly re-checks it.
- **Model choice.** The golden set is 46.5% Sonnet-4.6 findings among high+medium TPs (§1b), and crucible already
  routes Sonnet as the reviewer when Opus wrote the change. A Sonnet 5.5 seat beside the Opus seat is the cheapest
  diverse second sample within Claude Code. A GPT seat (block's and RevEngine's panels) is out of reach for a
  `claude -p`-only tool.
- **Targets.** NF and RL. Different samples stop at different places. In R8 one round lost 3 found items and gained 4
  ("one-round variance in the first pass, the same size as the gains"), which is direct evidence that the union of
  two samples beats either one.
- **Where.** `review.py` `run_review`, around `run_pass`: run each chunk once per seat (`CRUCIBLE_SEATS=opus,sonnet`),
  tag `seat` on each item, concatenate before `dedupe`. The dedupe must keep distinct claims on one line apart (it
  merged 54 restatements in TRAIN and no distinct claim, so it is already close). Retire or shrink the bug sweep, whose
  $0.60 budget the second seat takes over.
- **Test.** Arm B, nearly $0 first: the two stored rounds of all 60 TRAIN PRs (`r8base`, `r8train`) are already two
  independent samples of nearly the same code. The union of their kept items, re-matched (matcher only, judge
  calls of cents), estimates what a two-seat union finds, with precision included. From the R8 notes alone (base→R8
  "gained 4, lost 3" of 30 high items), the union reaches about 21 of 30 against 17-18 for either round. Do this
  first, then a paid arm (Opus+Sonnet seats, 1 round, about $35 on the 10 PRs) to confirm. The same union of the two
  stored held-out runs (R7 and R8 h50), scored for totals only, would be the strongest cheap test. It needs a judge
  pass over held-out PRs, so the main session decides whether the held-out rule allows it.
- **$/PR.** +$1.0-1.5 for a second full seat at today's pass cost, partly paid back by dropping the bug sweep ($0.36
  per PR average in R8-train: $21.78 / 60).

### T3. One conversation over the whole change, system first, then trace outward (M for the package, I for the parts)

- **Source.** RevEngine `REVIEWER_SYSTEM` "How to work", steps 1-5 (Apache-2.0); `reviewerPrompt` puts the whole diff
  in the prompt up to `INLINE_DIFF_CHARS = 80_000`, else hands over `read_diff`, with source, config and tests first
  and lockfiles skimmed. The board result for that package (single Opus seat, 60.6 high recall) is measured. The share
  due to each step is not.
- **How it works.** Before any finding, the reviewer must be able to say what the component does, who calls it, what
  it calls, what data passes through it, and what it promises its callers. Then it reads the stated intent and the
  whole diff, then searches for every caller and use of each touched function, type, schema and config key ("Many
  real defects sit in a caller the diff never shows"), then reviews lens by lens, then checks coverage. It has a turn
  and time budget, and it is told to use most of it: "The most common way a review fails is by stopping after the
  diff and a few files."
- **What crucible does instead.** A one-line "read the WHOLE enclosing function … grep for its callers" instruction,
  inside a prompt that spends most of its words on house style, PR-description style and (with `--nits`) eight nit
  categories. And a pass sees only its own files' diff, so a multi-pass PR (mississippi's 24, emdash's 24) cannot see
  that its pass's change feeds a consumer in another pass. NF items such as entebus #32 (the dashboard URL passes the
  raw id that consumer pages compare with `COMP-001`) and agent-orchestrator #4/#17 (a moved script still named
  elsewhere) are exactly "trace every change outward" items.
- **Targets.** NF (5). Also BU: one conversation with a `read_diff` tool degrades by skimming, not by dropping whole
  files.
- **A caution from TraceHound** (decision 057, MIT): putting more static context in a fixed budget cut its dev recall
  from 43.2 to 28.4, because the references crowded out the changed files ("only 12 of 48 chunks kept any
  reference"). The lesson is to have the reviewer *search* outward with its tools, as RevEngine does, rather than to
  pre-stuff more context into the prompt.
- **Where.** `review_prompt` (the "How to review each hunk" paragraph becomes the 5-step "How to work"; with `--lens` or
  `--nits` on a benchmark run, drop the house-style and PR-description paragraphs, which `--lens` already strips) and
  `diff.chunk` (raise `max_chars` toward 80k, and give every pass the full file list with changed line ranges, as
  RevEngine's `changedFilesSection` does, plus the other passes' diff on demand through `git diff` in its tools).
- **Test.** Arm C: the T3 prompt with T1's "what to report" (they belong together; testing T3 without T1 tests a
  prompt RevEngine never ran). Same metrics as T1, plus files opened per review from the CLI transcript
  (`--output-format stream-json`), to check that the reviewer actually traces outward.
- **$/PR.** +$0.2-0.5. More turns per pass. Partly offset by fewer passes at 80k, and by dropping the house-style
  material on benchmark runs.

### T4. Raise the review passes' reasoning effort (M on the board; untested on Claude)

- **Source.** The board's own configuration ladders (§1c): Copilot Lite → Max +11.3 high recall, Codex Sol xHigh → Max
  +3.9, with precision flat. LangChain's ReviewBench post (2026-07-31): models that "tended to stop after a few
  findings" scored lower, and a tuned run used high reasoning effort with a "map the change, trace dependent behavior,
  validate" prompt (0.32 F1 against Kimi and Opus on the same 20 tasks; no separate effect given for effort).
- **How it works.** `claude -p --effort xhigh` (or `max`) on the review passes only.
- **Targets.** RL and NF. More reasoning per hunk finds the second flaw at a line and the reader in another file.
  Unmeasured for Opus 5.5 under Claude Code. The Codex and Copilot ladders are other vendors.
- **Where.** `review.py` `run_pass` → `claude(..., effort=...)` (default `"high"`), behind `CRUCIBLE_REVIEW_EFFORT`.
- **Test.** Arm D: effort `xhigh` and nothing else, 1 round on the 10 PRs. Record the cost ratio as well as the item
  count. If it passes at under +$1/PR, combine it with T1+T3.
- **$/PR.** Unknown for Opus 5.5. Expect +30-80% on review-pass spend, about +$0.5-1.0. Measure it before deciding.

### T5. An outward "consumers and siblings" seat with a step checklist (C, I)

- **Sources.** RevEngine swarm `experiments/prototypes/swarm/tasks.ts` (Apache-2.0): the `callers`, `together` and
  `promise` tasks; `context.ts` gives each chunk agent "the code around every use of a name the chunk changes, the
  first lines of the functions it calls, the tests whose file names match … and the same places at the base
  revision". block/review's "Behavior & Contracts" procedure: "Trace every changed field, result, enum case,
  API/schema/proto, and configuration value from producer to consumer and back through storage/cache, serialization,
  and transport … Compare old/new paths, alternate backends, sync/async paths, real/test implementations,
  region/mode variants". Anthropic claude-security plugin `workflows/scan.js` (proprietary, ideas only): a change scan
  runs, beside the diff reviewers, a reviewer that works "outward from the changed lines rather than through them: the
  callers of every function, route or handler the change adds or alters, and what input they hand it; what the
  changed lines now call, write or store, and every reader of those values; any check, default, dependency or
  permission the change removes or loosens, and who relied on it".
- **How it works.** A dedicated seat whose only job is outside the diff. It lists every name, value, path, format and
  interface the change adds, alters, removes or moves, then searches for every reader, caller, sibling implementation
  and string reference, and reports at the reader's line. RevEngine's `together` step: "Report each sibling that the
  change should have updated and did not, at the sibling's own lines." crucible's bug sweep names the same shapes, but
  as one paragraph in a capped (≤5) second look that sees only the raised list and the pass's diff. Its results land as
  nits, and it was skipped on 11 of 60 TRAIN PRs. The ideas match; the execution is a side pass.
- **Targets.** NF (Maui's Tizen sibling, agent-orchestrator's moved script, entebus's consumer pages, swarmbase's
  snapshot path that never fires handlers) and WF (the reader's line is the fault site).
- **Where.** A new seat in `run_review` beside the passes (not after them), with its own budget slice. It reuses
  `callers_note` / `fields_note` / `docrefs` output as seed context, as RevEngine's `context.ts` seeds mentions with
  one `git grep`. Prompt text can be adapted from `tasks.ts` with an Apache-2.0 attribution header (§5).
- **Test.** Arm E: T5 seat + today's pipeline, 1 round. Count which of the 5 NF items it reaches (file and line in its
  raw output, before verification) and how many of its kept items the judge matches. Precision risk: readers it
  imagines. Its items go through normal per-finding verification.
- **$/PR.** +$0.4-0.8 (one Opus seat at about 60% of a pass's turns). If T2 ships, make T5 the second seat's brief
  instead of a third seat, which keeps cost near T2's.

### T6. Asymmetric verification: drop only on concrete counter-evidence, and audit the drops (M by design, C)

- **Sources.** block/review `review/prompts/coordinator.md`: "Drop a candidate as disproved only when you found that
  concrete counter-evidence, and cite it. 'Not reproduced', another panelist's silence, or a short list are not
  disproof. A candidate you tried and failed to disprove is kept." `review/prompts/judge.md`: a judge on a different
  model re-reads only the drops, and is "especially skeptical of drop reasons that rationalize a defect as a
  'pre-existing pattern', 'low confidence', 'preparatory plumbing', or 'not reproduced'". RevEngine
  `VERIFIER_SYSTEM`: one call checks every finding (`confirmed` / `rejected` / `uncertain`), and agent mode keeps
  `uncertain` ("Neither mode reports a claim the verifiers rejected"). Its `05b0fea`: the verifier rejected
  duplicated code as "style", so it was told "maintainability problems are not style preferences". **Measured
  against filtering:** TraceHound (MIT, `docs/bench/levers-v2.md`, `vote.md`, `pool-verify.md`): its keep/drop verifier
  cut mean recall 52.7 → 44.3 (3 Super) and 61.5 → 46.6 (3.5), and F rose in only 2 of 9 runs. Voting across 5 runs,
  confidence thresholds (the best threshold dropped nothing) and per-PR caps all lost recall. On ReviewBench its
  verified pipeline scored grounded R 7.6 against 9.0 unverified. **Kodus**
  `prompts/verifier-prompt.ts` (AGPL, ideas only): "The bar to remove a finding is a REFUTATION, not a doubt … When in
  doubt, KEEP … Recall of real defects matters more here than trimming the last few low-value findings". The verifier
  may not drop a finding because its trigger is concurrent, adversarial, cross-file or off a changed line, and an
  unparseable verdict keeps the finding. **SourceAnt's opposite rule is a trap:** with 2 evaluation passes and
  `maximum_rejections = 0` (its benchmark fixture), one rejecting vote kills a finding. zeroshot's finalizer: "Remove a finding only for one
  of these reasons … Keep every other finding, small ones included; when you are unsure, keep it." barsurfer's
  pr-review-agent (MIT, `docs/context/prompt/judge.md`): "the reviewer sets the recall ceiling", and test-gap findings
  its judge dropped "match golden labels about as often as kept findings do".
- **How it works.** The verifier's default flips from "keep only if it survives AND is caused AND is reachable" to "keep
  unless disproved with cited code", plus a cheap second-model audit of the drops only.
- **Targets.** None of TRAIN's 13 misses (0 dropped by verification). R5/R6 lost 4 high items to causation refutations
  (aafactory, apilix ×3; since fixed), and 2 to "others do it too" / "predates". Ranked here because T1, T2 and T5 all
  send more candidates to the verifier, and today's strict AND rule would eat part of that gain. It is the guard that
  lets the recall levers pay off. Batching every finding into one verifier call (RevEngine) would also pay for T2:
  crucible spends one tool-loop call per finding.
- **Where.** `verify_prompt` ("Keep the claim only if it survives AND …"), `verify_tiered`, the drop branch in
  `run_review`. Add a drop audit: one Sonnet call over all `dropped` items with their evidence, restoring as unverified
  low-confidence (block's judge).
- **Test.** $0 first: re-verify the stored dropped findings of the 10 TRAIN PRs plus R6's 36 drops (the
  `reverify_nits.py` setup of 11-20) under the new wording, and count restored items that land on golden TPs against
  golden-false ones. Then ride along with arm B or C.
- **$/PR.** Per-finding → batched: −$0.3 to −$0.8 on PRs with 6+ findings. Drop audit: +$0.05-0.15.

### T7. Read the PR's stated intent as a spec, and rate a defect in it high (C)

- **Sources.** RevEngine `REVIEWER_SYSTEM` severity: "A defect in the very thing the change sets out to do is also high,
  even when it needs particular conditions: if the change exists to fix or add one behavior, and that behavior is
  still wrong in a case the change should cover, the change has not done its job." Its "Completeness" lens and swarm
  `promise` task: "For each claim, follow the code from end to end and check it is delivered: wired up, registered,
  exported, reachable from the layer a user calls, configured and documented". block/review deliberately withholds
  intent from its security lens ("Do not seek the PR description … claimed intent"), so that the author's claim does
  not anchor it. That is worth copying too.
- **How it works.** The title and body are input for bug-finding: a list of claims to check end to end. That is a
  different job from judging the description's prose.
- **What crucible does.** On a benchmark run the PR body becomes `PR_DRAFT.md` and is reviewed for length, house style
  and missing call-outs. Its claims are never turned into checks. TRAIN's dotnet/android #0 ("library silently not
  rewritten", raised as a comment nit) and obot #0 (CreateCredential on an existing credential fails) look like
  claims the PR makes that the code does not deliver. Check their PR bodies before counting on it.
- **Targets.** RL (raise the intent defect at its line, at high) and NF.
- **Where.** `review_prompt`: a "What the change says it does" block built from the draft's title and body, separate
  from the house-style block, with RevEngine's severity sentence added to `SEVERITY_DEFS` under `--nits`/lens.
- **Test.** Folded into arm C (same prompt edit). Read-only check: on how many of the 10 TRAIN PRs the body makes a
  checkable claim.
- **$/PR.** About $0.

### T8. A second look in the same conversation that names the unopened files (M as part of RevEngine's package)

- **Source.** RevEngine `secondLookFor` + `SECOND_LOOK` in `src/prompts.ts`. After the first `submit_review`, the same
  conversation (tool history and prompt cache intact) gets "look again for what a first pass usually misses", plus the
  list "Changed files you have not opened yet". Variants `sweep` (hunk by hunk, up to 6 rounds, `sweepRounds`) and
  `small` exist but are off by default. The default (`RB_CONFIG_SECOND_LOOK=on`) shipped in the #5 entry.
- **How it works.** The reviewer's own session continues, so it costs cached tokens, not a fresh read. The harness
  knows which files were opened (`Workspace.opened`) and names the rest.
- **What crucible does.** Fresh sweeps with a new prompt, the raised titles and no memory of what was read.
  `--no-session-persistence` rules out `--resume` today. Claude Code can continue a session (`--resume <id>` with
  persistence on in an isolated `CLAUDE_CONFIG_DIR`, or `--input-format stream-json` to send a second user turn).
- **Targets.** NF, BU (files never opened inside a pass).
- **Where.** `util._claude_once` (a `continue_with` argument), `run_pass`. Unopened files can be counted from the
  stream-json transcript's Read and Grep calls.
- **Test.** Arm F, run with T1/T3 since it is part of that package: the second-look round's own new items, by
  file-opened status. If the second look adds no matched items in 10 PRs, drop it. RevEngine's own comment says a
  same-conversation look "tends to resubmit at once", which is why it also has a fresh follow-up seat.
- **$/PR.** +$0.1-0.3 (mostly cache reads).

### T9. Name the second flaw: a hunk-by-hunk sweep (C)

- **Source.** RevEngine `sweepMessage` / `sweepRounds` (commit `05b0fea`): "A reviewer pointed at a small piece of code
  finds problems it passed over while reviewing the change as a whole … A problem you already reported at another place
  is a new finding when it appears again in these lines". Off by default, no published number.
- **Also.** barsurfer's pr-review-agent (MIT, `src/review/breadth.ts`, `docs/context/review/fsm.md`) runs a
  "second look" that re-reads only the files that already have a finding: "Why: … lifts recall where the first pass
  stopped at one problem per file". A separate "breadth" pass covers the files with no finding yet. Its notes say run
  440 "found ~29% of HIGH goldens; most misses were scenario or cross-file failures no pass traced". TraceHound's
  missed-issue pass (`prompt-missed.ts`, MIT) took ReviewBench grounded R from 9.0 to 12.1. In its dev test the pass's
  own items were 41% TP on one model and 24% on the other (7 of 17, 8 of 34), far above its category lenses (about
  9%).
- **Read against crucible's bug sweep.** The sweep is this idea, and it carried 1 TRAIN high item and none net on the
  held-out set. The working versions differ in what they are pointed at: barsurfer and RevEngine name the files
  (flagged ones, unopened ones) or the hunks, and TraceHound feeds the pass the same context block as the first
  reviewer. crucible's sweep gets a list of titles and an open brief.
- **Targets.** RL (a second flaw at a line already flagged) and the sibling sites.
- **Where.** As T8's second round. **Test:** arm F variant. **$/PR:** +$0.2-0.6.

### T10. Specialist lenses with step-by-step procedures (M from Kodus as readings beside a generalist; mixed as a replacement)

- **Sources.** block/review's three procedures (`panelistRoles`: Behavior & Contracts, Reliability & Operations,
  Security & Trust Boundaries), each with a `coverage_summary` that has to account for every hunk. RevEngine's 10
  lenses in one prompt plus the narrow swarm tasks: `logic` (e.g. "For each early exit from a loop, check what happens
  when a value its condition needs is absent"; "A computed limit that is never applied usually means a missing check"),
  `types`, `compat`, `claims`. The Anthropic plugins' `pr-review-toolkit` agents (`silent-failure-hunter`,
  `pr-test-analyzer`, `type-design-analyzer`; Apache-2.0).
- **Kodus measures them, as an addition.** Its nine heavy-mode lenses (T2) added +13 to +17 recall *beside* the
  generalist. Two of its lens briefs target crucible's NF class directly: "contract-not-followed": "Reconstruct what
  the symbol looked like BEFORE this change and check every consumer against the new shape", and
  "changed-files-disagree": "list the symbols that appear in hunks of two DIFFERENT files. For each, read both sides".
  (Ideas only: the code is under `libs/ee`.)
- **As a replacement for the generalist, the board evidence is mixed.** block's 6-panelist specialist panel (53.5 high recall) is below RevEngine's single
  generalist Opus seat (60.6). RevEngine kept its specialist swarm experimental and registered the generalist.
  barsurfer's reliability lens "did not repeatably add golden hits or grounded F1", and its performance lens added
  none (`fsm.md`). TraceHound's lens B (tests, docs, typos) added recall but cut precision below its floor
  (`v3-recall.md`). zeroshot removed four of its hunters (`unit_depth`, `hunt_logic`, `hunt_state`, `hunt_errors`)
  after benchmark tuning (`planning/plans/code-review-template.md`, 2026-11-19). Lenses
  as headings inside one exhaustive prompt (T1+T3) look better supported than separate specialist calls. The
  procedures are still good checklist text.
- **Targets.** RL, NF. **Where.** The lens text goes into `review_prompt`, replacing the nit paragraphs on benchmark
  runs. **Test.** Not separately. It rides in arm C's prompt. **$/PR.** About $0 as prompt text, +$1-2 as separate
  seats.

### T11. Notes on leads (or doubts), then a follower for each (C, proprietary and MIT sources)

- **Source.** Anthropic `claude-security` plugin (all rights reserved, ideas only), `agents/scan-sheet-researcher.md`:
  "What may be a flaw, and you did not follow far enough to say, is a lead: one line, with your guess at its severity."
  `workflows/scan.js` follows up to 60 leads, each with its own agent ("Settle the lead … Report it if it is a flaw, and
  any flaw of the same kind beside it"). It also sends "packs", readers of whole files near where something was
  reported.
- **Also.** SourceAnt (MIT, `plugins/builtin/code_reviewer/reviewing.py`): with `review.evaluate_uncertain_findings`
  on, discovery is told to "report it anyway and state that reason in `doubt`", and evaluation decides. Off by
  default, its `certainty = possible` → NIT → dropped path silently discards every finding that rests on code the
  model was not shown (a trap to avoid). Kodus's "synthesis rescue" (`core/finder.agent.ts`) gives one more run the
  files already inspected, the last 20 tool calls and the findings, and asks for "concrete missed bugs". Its
  `finder-model-profile.ts` turns that rescue on for Sonnet, DeepSeek and Kimi, and off for Opus and GPT: for the
  strongest models, a same-context follow-up was not worth its cost.
- **How it works.** The reviewer's unproven suspicions stop being silently discarded. They become a cheap list that
  separate, focused calls resolve.
- **Targets.** NF and RL: the "I noticed but didn't follow it" items that T1's wording also aims at. A lead list catches
  what the reviewer still holds back after T1.
- **Where.** A `leads` field in `FINDINGS_NITS_SCHEMA` (file, line, one line, guessed severity). A follower call per
  lead, batched per file, Sonnet, read-only, bounded at 8 per PR. Its outputs are verified like findings.
- **Test.** Arm C+: log leads only (no followers) and count, at $0 over the arm's output, how many leads sit on a missed
  high item's file and span. Build the followers only if that count is above 2.
- **$/PR.** Logging: $0. Followers: +$0.3-0.8.

### T12. Diagnose misses by asking the reviewer (methodology, M as a tool)

- **Source.** RevEngine `scripts/probe.ts` (commit `78cd6ca`): continue the recorded reviewer conversation, point it at
  the lines of each missed expected finding without saying what is wrong, and ask whether there is a problem and why
  the review left it out. A second model decides whether the answer names it. Also `scripts/replay.ts`: replay only
  the reporting step with a new prompt over the recorded reads (about $3 per sample per 25 PRs after the first), and
  `scripts/coverage.ts`: did any reviewer read the code behind each expected finding.
- **Why it matters.** crucible's miss classes come from reading `review.json`. They cannot tell "never read it" from
  "read it and held back", and that split decides between T3/T5 (reach) and T1/T11 (restraint). This is the cheapest
  next measurement.
- **Where.** Record each review pass's transcript (`--output-format stream-json` into the review dir, opt-in
  `CRUCIBLE_TRANSCRIPTS=1`). A `crucible probe` (or `bench/` script) for TRAIN items only.
- **Test.** Needs one recorded TRAIN round, which can be arm C's run itself. Then $1-3 of probe calls on the 13
  misses.
- **$/PR.** $0 in production.

### T13. Checklists of bug classes from static-analysis rule packs (I; low value on this board)

- **Sources.** CodeQL query packs (`github/codeql`, MIT): class names such as "useless assignment", "unreachable
  code", "missing await", "comparison of identical values". Semgrep `p/bugs` (rules under the Semgrep Rules License,
  not OSI: ideas only). The open-code-review and pr-agent findings in §4.
- **Evidence against ranking it higher.** Semgrep made 0.3% of the golden set's TPs (§1b). The board rewards what LLM
  reviewers notice, and crucible's prompt already lists most of these classes.
- **Where/test/$.** At most a few lines in a lens. No separate arm. $0.

### T14. A repo map for context (I; superseded by tools)

- **Source.** aider `aider/repomap.py` (Apache-2.0): tree-sitter tags, then a PageRank over the def/ref graph,
  personalized to the mentioned identifiers. It fits a token budget.
- **Also seen.** Kodus feeds a `kodus-graph` call graph as `<CallGraph>` and offers a `getCallers` tool. SourceAnt
  has an opt-in tree-sitter index with callers and callees, plus a "review-search" model call that picks search terms
  ("the old name of a thing renamed, the caller about to break") for ripgrep. pr-agent extends each hunk up to its
  enclosing function header (`git_patch_processing.py`, "dynamic context"). None publishes a recall effect for the
  context alone.
- **Why it ranks low.** crucible's reviewer already has Grep/Read/`git grep`, and Bugbot reports that moving context
  "out of static upfront context" so the agent pulls what it needs did better. RevEngine's swarm uses mention-seeding
  (`git grep` of changed names) only for cheap no-tool agents. crucible's `callers_note` / `fields_note` already
  play that role.

### T15. Deterministic coverage: one small call per (file × rule) instead of letting the model choose (M, narrow)

- **Source.** Kodus Kody Rules (AGPL, ideas only; `collaborators/kody-rules-sharded.judge.ts`): replacing an agentic
  sweep over all team rules with a sharded judge, one call per changed file × applicable rules, raised rule-occurrence
  recall from 40%/58% (GPT-5.4 / Kimi) to 91-100%, per its header comment. OpenCodeReview (Apache-2.0,
  `internal/agent/agent.go`) gives every changed file its own agent with a full tool budget, and for files over 50
  changed lines first runs a plan call that lists severity-ranked hypotheses with tool guidance (`PLAN_TASK` in
  `internal/config/template/task_template.json`). Its own benchmark (1,505 human-annotated issues, `pages/`) reports
  only absolute figures, with no ablation.
- **Targets.** Written project rules (R5's TechDebtMCP class, where the rule sat past the excerpt), and BU and NF on
  large multi-file PRs: no file goes unread because the model spent its turns elsewhere.
- **Where.** `review_prompt`'s rules: for each changed file, the rule lines of CLAUDE.md, AGENTS.md and CONTRIBUTING
  that apply to it (`RULE_LINE_RX` already extracts them), judged in one Haiku/Sonnet call per file in batches. For BU:
  a cheap per-file "hypotheses" call for files a pass never opened.
- **Test.** Counts on TRAIN at $0 first: how many of the 13 misses are rule violations (none obviously are, so the gain
  here would be on other PRs) and how many sit in files the passes never opened (mississippi's 2). Build only if
  either count is above 1. **$/PR.** +$0.1-0.4.

## 4. Other projects read, and what they add

**Things that cost recall, seen in several projects. Avoid these.**
- Hard caps on findings: pr-agent `num_max_findings = 6` (`pr_agent/settings/configuration.toml`, also applied after
  chunk merging); crucible's "at most 10" per pass and "at most 5" in the bug sweep; TraceHound's per-PR caps (no gain
  when tested).
- "One comment on the first instance" or "comment on the most critical": run-gemini-cli `gemini-review.toml` ("No
  Duplicates"), shippie ("If many similar issues exist, comment on the most critical"). ReviewBench matches per file,
  so every further site of a flaw is a separate golden item.
- "Don't speculate about code outside the diff": pr-agent `pr_reviewer_prompts.toml` line 17 tells the model it sees
  only hunks, and barsurfer's base prompt says "assume code outside the diff works". crucible's NF class is code
  outside the diff.
- Confidence floors at generation: Gito's "Only report issues you are 100% confident" plus `confidence == 1`;
  claude-code-security-review's ">80% confident" and "Below 0.7: Don't report"; SourceAnt's `possible` → NIT → dropped.
  TraceHound measured the best threshold as the one that drops nothing.
- Veto verification: SourceAnt `maximum_rejections = 0`; crucible's "keep only if it survives AND is caused AND is
  reachable".
- One call per file or hunk with no cross-file view: Gito, ai-codereviewer, OpenCodeReview (OCR does give each file
  agent tools and the other files' diffs).

**Projects that add little beyond the above:** reviewdog (MIT; posts linter output; its `added` /
`diff_context` / `file` / `nofilter` filter modes are a reminder that keeping only added lines drops bugs on context
lines); ai-codereviewer (MIT; one call per hunk); shippie (MIT; one agent with tools, a QA browser agent, no evals);
Gito (MIT; per-file, precision-first); fangkangmi/deepseek-reviewer (MIT; one agentic run, "at most 30 findings",
never judge-scored); run-gemini-cli (Apache-2.0; no file reads, keyword evals); Anthropic claude-code-security-review
(MIT; precision-first security audit with a hard-exclusion filter, useful only as a category list).

## 5. Top 3, as concrete designs

Order of work for the improve shift: run the $0 union estimate (design 2, step 1) and record transcripts first. Then
run one paid arm per design on the 10 TRAIN PRs (about $25-35 each). Combine the arms that pass. Only then run the
held-out 50 (2 rounds, if the accounts allow, since one round can't resolve ±2 items).

### Design 1: recall-first discovery in one conversation (T1 + T3 + T7 + T8)

A new review prompt, used when `--nits` or `--lens` is on (benchmark and lens runs) or `CRUCIBLE_RECALL=1`. The
default upstream `crucible review` keeps today's prompt and bar.
1. **Unit of review.** `diff.chunk(max_chars=80000)`. Every pass gets the list of all changed files with their changed
   line ranges, and is told it may `git diff <base> -- <path>` any file outside its pass.
2. **How to work** (adapted from RevEngine `REVIEWER_SYSTEM`, Apache-2.0, credited in the file header): understand the
   system (README, design docs, callers, data), read the stated intent and the whole diff, trace each touched name
   outward with Grep/`git grep` and read the readers, review lens by lens (correctness, completeness, production
   safety, security, compatibility, tests, docs), then check coverage: every changed file opened.
3. **What to report**, replacing "Report only real problems … at most 10 … merge findings that share a root cause …
   An empty list is a good answer": "Report every problem you can support from code you read, including small ones;
   two problems in the same lines are two findings; the same defect at two places is two findings; a review of a few
   hundred changed lines usually has ten or more." `FINDINGS_SCHEMA` `maxItems` goes from 10 to 30.
   `caused_by_this_change` and `reachable_in_real_use` become optional: the verifier rules on both.
4. **Intent as spec.** A "What the change says it does" block from the PR title and body, separate from house style.
   Add to `SEVERITY_DEFS`: a defect in the very behaviour the change sets out to add or fix is critical/important
   even when it needs particular conditions.
5. **Benchmark runs drop** the house-style and PR-description paragraphs (as `--lens` already does). The nit
   categories move to a short lens list.
6. **Second look in the same session** (`claude -p --resume`, persistence on in the review's isolated
   `CLAUDE_CONFIG_DIR`): the unopened changed files are named, and the reviewer is asked for what a first pass usually
   misses.

Test: arm C on the 10 TRAIN PRs, 1 round, about $28. Pass: base-missed high items reached ≥ +3 of 13, no net loss on
the items already found on those PRs, high P ≥ 90, and the clean-case eval with 0 false blocking. Expected $/PR: +$0.3-0.8 before design 3's
savings.

### Design 2: two independent seats, unioned (T2, optionally T5's brief on seat 2)

1. **Near-$0 estimate first.** Union the kept items of `runs/r8base` and `runs/r8train` on all 60 TRAIN PRs (two
   independent samples of nearly the same code), and on the 10 miss PRs separately. Rescore with the matcher (cents), and record high items reached, high P,
   and items per PR. If the union reaches no more than either round alone, stop here.
2. **Build.** `CRUCIBLE_SEATS=opus,sonnet` (default off). Each pass runs once per seat in parallel. Each seat is a fresh
   conversation that knows nothing of the other (no "already raised" list: RevEngine's note that a model told to
   look again "tends to resubmit at once" is why). Items carry a `seat` tag. `dedupe` runs over the union, keeping
   distinct claims on one line apart. The bug sweep is off when seats ≥ 2, and its $0.60 goes to the second seat.
3. **Variant.** Seat 2 runs design 1's prompt with T5's outward brief (RevEngine's `callers` / `together` / `promise`
   steps, Apache-2.0) in place of the general lenses: diversity of brief as well as model.

Test: arm B on the 10 TRAIN PRs, 1 round, about $35. Report per-seat and union counts, so that "the union beats one
seat" is read from the same run. Expected $/PR: +$1.0-1.5 gross, about +$0.7-1.1 net of the bug sweep.

### Design 3: keep unless disproved, one batched check, and a drop audit (T6)

1. **Discovery findings** (not nits, not house style) go to the verifier in one call per pass (Sonnet, read-only plus
   probes where `--no-exec` is off), not one call per finding. Its prompt, adapted from block/review's coordinator
   (Apache-2.0): try to disprove each claim against the code; drop only with cited counter-evidence ("not reproduced"
   and "other code does it too" are not disproof); a claim you tried and failed to disprove is kept, at its honest
   severity; mark repeats.
2. **Drop audit**: one call on the other model over the dropped items and their reasons, restoring those whose drop
   rests on "pre-existing pattern", "low confidence" or "not reproduced" without cited code (block/review
   `judge.md`).
3. Upstream (non-benchmark) reviews keep today's per-finding tiered verification for blocking findings. Precision on
   real PRs matters more there.

Test: at $0 first, re-verify the stored drops of the 10 TRAIN PRs and R6's 36 drops with the new prompt, and count
restorations on golden TPs against golden-false. Then ride along with arm C (same run, verifier swapped). Pass: high
P ≥ 90 with design 1's extra candidates, and verification $ per PR down. Expected $/PR: −$0.3 to −$0.8 on PRs with
6+ candidates, +$0.1 for the audit.

**Also try (one line each):** `CRUCIBLE_REVIEW_EFFORT=xhigh` as its own arm (T4, the board's ladders say +4 to +11
high recall for other vendors; cost unknown for Opus 5.5). A `leads` field logged at $0 (T11). Transcripts recorded
for a RevEngine-style miss probe (T12).

## 6. Prior art and thanks (for the README)

crucible borrows ideas, and some wording under Apache-2.0 / MIT with credit in the source, from these projects:

- [Laude RevEngine](https://github.com/laude-institute/rev-engine) (Apache-2.0): the whole-change review conversation,
  "understand the system, then trace outward", exhaustive reporting, intent-based severity, the in-session second
  look, and its swarm task checklists.
- [block/review](https://github.com/block/review) (Apache-2.0): lens procedures, keep-unless-disproved coordination,
  and a judge that audits drops.
- [TraceHound](https://github.com/sunnybagal/tracehound) (MIT): pre-registered ablations, published losses included,
  showing that unioning runs raises recall and that filtering cuts it.
- [The Open Engine zeroshot](https://github.com/the-open-engine/zeroshot) (MIT): one review prompt run on two model
  families per unit, and a finalizer that keeps findings when unsure.
- [barsurfer/pr-review-agent](https://github.com/barsurfer/pr-review-agent) (MIT): breadth and second-look passes,
  and judge policy measured on ReviewBench.
- [OpenAI Codex](https://github.com/openai/codex) (Apache-2.0): the review rubric ("do not stop at the first
  qualifying finding").
- [Anthropic claude-code-security-review](https://github.com/anthropics/claude-code-security-review) (MIT) and
  [claude-plugins-official](https://github.com/anthropics/claude-plugins-official) code-review / pr-review-toolkit
  (Apache-2.0): security categories, specialist agents and per-issue validation.
- [Kodus](https://github.com/kodustech/kodus-ai) (AGPL-3.0, ideas only, no code): a finder that reports on
  suspicion, refute-to-drop verification, lens readings measured beside a generalist, and per-stage funnel evals.
- [OpenCodeReview](https://github.com/lizhengfeng101/open-code-review) (Apache-2.0) and
  [SourceAnt](https://github.com/sourceant/sourceant) (MIT): per-file agents with a plan of hypotheses, and focused
  independent readings.
- [qodo-ai/pr-agent](https://github.com/qodo-ai/pr-agent) (MIT at the time of reading; earlier releases AGPL-3.0;
  ideas only): ticket compliance and dynamic hunk context.
- [Aider](https://github.com/Aider-AI/aider) (Apache-2.0): the repo map as a context budget.
- [ReviewBench](https://github.com/review-bench/ReviewBench) (MIT): the benchmark, its methodology and its open
  board.
- Cursor's "Building a better Bugbot" (blog): parallel passes and the move to an agentic, less cautious reviewer.

## Appendix: per-project notes

| project | licence (as read) | read | what was taken | copy code? |
|---|---|---|---|---|
| laude-institute/rev-engine (Laude RevEngine, board #5) | Apache-2.0 | `src/prompts.ts`, `src/review.ts`, `src/config.ts`, `experiments/prototypes/swarm/{README.md,tasks.ts}`, `docs/REVIEWBENCH.md`, `AGENTS.md`, full git log (139 commits) | T1, T2, T3, T7, T8, T9, T10, T12; test-design method (matching-only scoring, replay, probe) | yes, with attribution |
| block/review (board #11) | Apache-2.0 | `review/panelists.go`, `review/prompts.go`, `review/prompts/{coordinator.md,judge.md}`, README | T1, T6, T10, intent withheld from security | yes, with attribution |
| sunnybagal/tracehound (board entrant) | MIT | via survey agent: `docs/bench/{reviewbench,results,levers-v2,vote,pool-verify,v3-recall}.md`, `packages/analyzer/src/review/*`; spot-checked by hand | T2 (measured union), T6 (measured filter cost), T3 caution | yes, with attribution |
| the-open-engine/zeroshot (board entrant) | MIT | via survey agent: `src/native_v2_templates/code_review.rs`, `code_review/*.md`, `planning/plans/code-review-template.md` | T2 (two model families per unit), T6 (keep when unsure), T10 (hunters removed) | yes, with attribution |
| barsurfer/pr-review-agent (board entrant) | MIT | via survey agent: `src/review/{breadth,lenses}.ts`, `docs/context/{review/fsm.md,prompt/judge.md}`; quote spot-checked | T6, T9, T10 (lens results) | yes, with attribution |
| fangkangmi/deepseek-reviewer (board entrant) | MIT | via survey agent | nothing new | n/a |
| sourceant/sourceant (board entrant) | MIT (cloud parts not in tree) | via survey agent: `src/core/review/{planning,orchestration,evaluation}.py`, `src/prompts/prompts.py` | T2 (focused readings), T6 (veto trap), T11 (doubt channel) | yes, with attribution |
| lizhengfeng101/open-code-review (Alibaba) | Apache-2.0 | via survey agent: `internal/agent/agent.go`, `internal/config/{template,rules,toolsconfig}` | T15 (per-file agents, plan of hypotheses), rule docs | yes, with attribution |
| kodustech/kodus-ai | AGPL-3.0 core; `ee/` and `.ee.` files proprietary (Kodus Enterprise Code License) | via survey agent; prompt and verifier quotes and eval files checked by hand | T1, T2, T6, T10, T11, T15 | **no: ideas only** |
| qodo-ai/pr-agent | MIT at HEAD ("Copyright (c) 2026 The PR Agent"); older releases were AGPL-3.0 | via survey agent: settings TOMLs, `algo/git_patch_processing.py`, `algo/review_merge.py` | anti-patterns (cap 6, no outside-diff speculation), ticket compliance | nothing copied; treat as ideas-only |
| anthropics/claude-plugins-official: `code-review`, `pr-review-toolkit` | Apache-2.0 | `plugins/code-review/commands/code-review.md`, `plugins/pr-review-toolkit/agents/*.md` | two bug agents with different briefs, per-issue validation, specialist agents | yes, with attribution |
| anthropics/claude-plugins-official: `claude-security` | proprietary ("All rights reserved") | `agents/scan-*.md`, `workflows/scan.js` (skimmed) | T5 (outward reviewer), T11 (leads, packs), lens-voter panel | **no: ideas only** |
| anthropics/claude-code-security-review | MIT | `claudecode/prompts.py`, `findings_filter.py` | security category list; precision-first counter-example | yes, with attribution |
| anthropics/claude-code | proprietary (Anthropic commercial terms) | plugin README only (plugins moved out) | nothing | no |
| openai/codex | Apache-2.0 | `codex-rs/prompts/templates/review/rubric.md`, `codex-rs/skills/src/assets/samples/review-agent/SKILL.md` | T1 ("do not stop at the first") | yes, with attribution |
| Aider-AI/aider | Apache-2.0 | `aider/repomap.py` | T14 (ranked low) | yes, with attribution |
| review-bench/ReviewBench | MIT | `docs/{METHODOLOGY,EXTRACTION,JUDGING}.md`, `agents/*.json` (registry), `examples/codex-cli`; **not** `golden/` or `corpus/` | §1b golden composition, matching rules, entrant registry | yes, with attribution |
| villesau/ai-codereviewer, reviewdog/reviewdog, mattzcarey/shippie, Nayjest/Gito, google-github-actions/run-gemini-cli | MIT / MIT / MIT / MIT / Apache-2.0 | via survey agent | anti-patterns only | n/a |
| coderabbitai/ai-pr-reviewer | repository no longer exists (clone failed, 2026-11-25) | — | — | — |
| Semgrep rules (`p/bugs`, `p/security-audit`) | Semgrep Rules License v1.0 (not OSI) | not cloned | T13 class names only | **no** |
| github/codeql query packs | MIT | not cloned (golden composition shows CodeQL contributed no surviving TP) | T13 class names only | yes, with attribution |
| Cursor Bugbot | proprietary product; public blog | blog "Building a better Bugbot" (2026-01-15) | T1, T2, T14 | no code exists to copy |
| OhMyBug (#1), intent-review-agent (#2), Klaussy, diffox, HeyDeer | closed (private or server-backed images) | registry entries and the OhMyBug CLI README only | volume per PR (§1a); OhMyBug runs a quick first step, a "fast hunt" and an optional deep hunt of up to 2 h | no |

Clones are in the session scratchpad (`oss-review-research/<name>`) and were only read. Board snapshot: entries dated
2026-09-28 to 2026-10-25, profile `official-2026-09`, 3 rounds each.
