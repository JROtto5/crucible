#!/usr/bin/env python3
"""crucible: an independent, evidence-first reviewer for upstream open-source contributions.

  crucible review  [REPO] [--base REF] [--budget USD] [--force]   checks → scanners → review → verification
  crucible status  [REPO]                                         verdict + readiness for the current HEAD
  crucible answer  ID fixed|refuted|deferred "note" [--repo R]
  crucible learn   [REPO]                                         maintainer rules + house style from merged PRs
  crucible prep    [REPO]                                         likely maintainer questions → PREP.md
  crucible polish  [REPO]                                         PR_DRAFT.md → PR_DRAFT.polished.md in house style
  crucible reply   PR_URL [--repo R]                              draft answers to review comments → REPLIES.md
  crucible vote    ID up|down "reason" [--repo R]                 feedback; down-votes become memory proposals
  crucible remember PROJECT "lesson"                              curated repeat-mistakes memory
  crucible proposals PROJECT [--accept N]                         review proposed memory entries
  crucible eval    [--cases ...] [--split S] [--no-tiers] [--label L] score the reviewer on fixtures (eval/)
  crucible routing-replay [--include-self]                        what cost-routing rules would lose, on stored reviews
  crucible anchor-replay --clones DIR [--per-class N] [--votes N] verifier with vs without the reviewer's argument
  crucible model-replay --clones DIR [--models opus sonnet] [--rounds N]  reviewer models on stored rounds, scored by answers
  crucible stats   [--project P] [--since T] [--include-self] [--json]  real-PR precision, held up with its 95% interval

crucible never pushes, comments, approves or posts. A human submits."""
import argparse, datetime as dt, os, sys
from . import __version__
from .util import Failed, HOME, MODELS, project_dir, project_key, read_json, write_json


def _p(repo):
    return os.path.abspath(repo)


def cmd_review(a):
    from .review import run_review
    try:
        run_review(_p(a.repo), a.base, a.force, a.budget, a.author, a.draft, a.base_checks, a.offline, a.skip_checks,
                   full=a.full, fresh=a.fresh, no_tiers=a.no_tiers, route=a.route or None, no_exec=a.no_exec)
    except Failed as e:
        sys.exit(f"crucible: {e}")
    return cmd_status(a)


def cmd_status(a):
    from .review import load, load_waivers, report, verdict, waiver_key
    project, sha, d, rev, ans = load(_p(a.repo))
    if not rev:
        print(f"NO REVIEW for HEAD {sha[:10]}. Run: crucible review {a.repo}")
        sys.exit(2)
    txt = report(rev, ans, load_waivers(project, waiver_key(_p(a.repo))))
    open(os.path.join(d, "report.md"), "w").write(txt)
    print(txt)
    print(f"(report: {os.path.join(d, 'report.md')})")
    v = verdict(rev, ans)[0]
    sys.exit(0 if v == "GREEN" else 1)


def cmd_answer(a):
    from .review import load, verdict
    project, sha, d, rev, ans = load(_p(a.repo))
    if not rev or rev.get("status") != "done":
        sys.exit("no completed review for this HEAD (a new commit needs a new review)")
    if a.id not in {f["id"] for f in rev["findings"]}:
        sys.exit(f"unknown finding {a.id} for HEAD {sha[:10]}")
    ans[a.id] = {"disposition": a.disposition, "note": a.note, "at": dt.datetime.now().isoformat(timespec="seconds")}
    write_json(os.path.join(d, "answers.json"), ans)
    print(f"{a.id} → {a.disposition}. Verdict now {verdict(rev, ans)[0]}")


def cmd_waive(a):
    from .review import load, waiver_key, waivers_path
    project, sha, d, rev, ans = load(_p(a.repo))
    if not rev or rev.get("status") != "done":
        sys.exit("no completed review for this HEAD")
    items = {i["item"] for i in rev["readiness"]["items"]}
    if a.item not in items:
        sys.exit(f"unknown readiness item {a.item!r}; one of: {sorted(items)}")
    if len(a.reason.strip()) < 20:
        sys.exit("give a real reason (20+ characters): it is printed in the report")
    key = waiver_key(_p(a.repo))
    allw = read_json(waivers_path(project), {}) or {}
    allw.setdefault(key, {})[a.item] = a.reason.strip()
    write_json(waivers_path(project), allw)
    print(f"waived {a.item!r} on detached commit {sha[:10]} (a new commit needs its own waiver)"
          if key.startswith("HEAD@") else f"waived {a.item!r} on branch {key}")


def cmd_learn(a):
    from .learn import run_learn
    try:
        run_learn(_p(a.repo), a.prs, style=not a.no_style)
    except Failed as e:
        sys.exit(f"crucible: {e}")


def cmd_prep(a):
    from .assist import run_prep
    run_prep(_p(a.repo))


def cmd_polish(a):
    from .style import polish
    polish(_p(a.repo), project_key(_p(a.repo)))


def cmd_reply(a):
    from .assist import run_reply
    run_reply(a.url, a.repo)


def cmd_vote(a):
    project = project_key(_p(a.repo))
    with open(os.path.join(HOME, "votes.jsonl"), "a") as fh:
        import json
        fh.write(json.dumps({"project": project, "id": a.id, "vote": a.vote, "reason": a.reason,
                             "at": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
    if a.vote == "down":                       # a proposal, not a rule: one bad vote must not silence a class forever
        with open(os.path.join(project_dir(project), "proposals.md"), "a") as fh:
            fh.write(f"- {dt.date.today()} ({a.id}): do not flag: {a.reason}\n")
        print(f"recorded; proposed memory entry (accept with: crucible proposals {project} --accept N)")
    else:
        print("recorded")


def cmd_remember(a):
    with open(os.path.join(project_dir(a.project.replace("/", "__")), "memory.md"), "a") as fh:
        fh.write(f"- {dt.date.today()}: {a.lesson}\n")
    print("remembered")


def cmd_eval(a):
    from .evalrun import run_eval
    run_eval(a)


def cmd_proposals(a):
    proj = a.project.replace("/", "__")
    p = os.path.join(project_dir(proj), "proposals.md")
    items = [l for l in (open(p).read().split("\n") if os.path.exists(p) else []) if l.startswith("- ")]
    if a.accept:
        i = a.accept - 1
        if not 0 <= i < len(items):
            sys.exit("no such proposal")
        with open(os.path.join(project_dir(proj), "memory.md"), "a") as fh:
            fh.write(items[i].replace(": do not flag:", ": DO NOT flag:", 1) + "\n")
        items.pop(i)
        open(p, "w").write("\n".join(items) + ("\n" if items else ""))
        print("accepted into memory")
        return
    for n, l in enumerate(items, 1):
        print(f"{n}. {l[2:]}")
    if not items:
        print("no proposals")


def cmd_routing_replay(a):
    from . import routing
    print(routing.replay_report(routing.replay(os.path.join(HOME, "reviews"), include_self=a.include_self)))


def cmd_anchor_replay(a):
    from . import anchoring
    rows, skipped = anchoring.run(os.path.join(HOME, "reviews"), a.clones, a.per_class, a.jobs, a.budget,
                                  a.include_self, a.votes)
    print(anchoring.report(rows, skipped, a.votes))


def cmd_model_replay(a):
    from . import modelreplay
    models = [MODELS.get(m, m) for m in a.models]
    rows, skipped = modelreplay.run(os.path.join(HOME, "reviews"), a.clones, models, a.rounds, a.budget, a.include_self,
                                    log=lambda m: print(m, file=sys.stderr))
    print(modelreplay.report(rows, skipped, models))


def _positive_int(v):
    """argparse type: an integer of at least 1."""
    try:
        n = int(v)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"expected a whole number of at least 1, got {v!r}")
    return n


def _iso_time(v):
    """argparse type: a local ISO date or date-time, normalized to the form stored reviews use (2026-11-07T05:15:00)."""
    try:
        t = dt.datetime.fromisoformat(v.replace(" ", "T"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date or date-time: {v!r} (use YYYY-MM-DD or YYYY-MM-DDTHH:MM)")
    if t.tzinfo:
        raise argparse.ArgumentTypeError("give a local time without a zone: stored reviews are in local time")
    return t.isoformat(timespec="seconds")


def cmd_stats(a):
    from . import stats
    s = stats.collect(os.path.join(HOME, "reviews"), include_self=a.include_self, project=a.project, since=a.since)
    print(stats.to_json(s) if a.json else stats.report(s))


def main(argv=None):
    p = argparse.ArgumentParser(prog="crucible", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("review", help="checks, scanners, model review and per-finding verification of HEAD vs its base")
    r.add_argument("repo", nargs="?", default=".")
    r.add_argument("--base", help="branch or commit the PR targets (default: the upstream default branch)")
    r.add_argument("--force", action="store_true", help="review this commit again even if it was reviewed with the same "
                   "base and draft (cached results are reused; see --fresh)")
    r.add_argument("--budget", type=float, help="stop making model calls once this many USD are spent")
    r.add_argument("--author", help="model id that wrote the change (else read from Co-Authored-By trailers)")
    r.add_argument("--draft", help="path to the PR description draft (default PR_DRAFT.md in the repo)")
    r.add_argument("--base-checks", action="store_true", help="re-run failing checks on the base to spot pre-existing failures")
    r.add_argument("--skip-checks", action="store_true", help="don't run the project's lint/test commands (the "
                   "verifier may still run probes; see --no-exec)")
    r.add_argument("--no-exec", action="store_true", help="run nothing from the checkout: implies --skip-checks, and "
                   "the verifier only reads (no node/npm/python/pytest probes). For sandboxes and untrusted code "
                   "(also CRUCIBLE_NO_EXEC=1)")
    r.add_argument("--offline", action="store_true", help="no GitHub calls (readiness skips the issue, claim and "
                   "open-PR checks)")
    r.add_argument("--full", action="store_true", help="review the whole change, not just what changed since the last review")
    r.add_argument("--fresh", action="store_true", help="redo the review and bypass the review/verification cache (--force alone reuses it, so verdicts are stable)")
    r.add_argument("--no-tiers", action="store_true", help="verify every finding with the strong model only")
    r.add_argument("--route", action="store_true", help="route by change type: a docs/PR-text-only round gets one cheaper "
                   "pass (also CRUCIBLE_ROUTE=1); see `crucible routing-replay`")
    st = s.add_parser("status", help="print the stored report for HEAD (exit 0 when GREEN)")
    st.add_argument("repo", nargs="?", default=".")
    an = s.add_parser("answer", help="answer a finding on HEAD's review; the verdict is recomputed")
    an.add_argument("id", help="finding id, e.g. CR-1a2b3c4d")
    an.add_argument("disposition", choices=["fixed", "refuted", "deferred"])
    an.add_argument("note", help="the evidence: the fixing commit, or why the claim is wrong")
    an.add_argument("--repo", default=".")
    wv = s.add_parser("waive", help="mark a readiness item as not applicable, with a reason shown in the report"); wv.add_argument("item"); wv.add_argument("reason"); wv.add_argument("--repo", default=".")
    le = s.add_parser("learn", help="learn maintainer rules and house style from the project's merged PRs")
    le.add_argument("repo", nargs="?", default=".")
    le.add_argument("--prs", type=int, default=25, help="merged PRs to read (default 25)")
    le.add_argument("--no-style", action="store_true", help="rules only, skip the house-style pass")
    pr = s.add_parser("prep", help="likely maintainer questions for this change, into PREP.md")
    pr.add_argument("repo", nargs="?", default=".")
    po = s.add_parser("polish", help="rewrite PR_DRAFT.md in the house style, into PR_DRAFT.polished.md")
    po.add_argument("repo", nargs="?", default=".")
    rp = s.add_parser("reply", help="draft answers to a PR's review comments, into REPLIES.md (never posts)")
    rp.add_argument("url", help="the pull request URL"); rp.add_argument("--repo")
    vo = s.add_parser("vote", help="thumbs up/down on a finding; a down-vote becomes a memory proposal")
    vo.add_argument("id"); vo.add_argument("vote", choices=["up", "down"]); vo.add_argument("reason")
    vo.add_argument("--repo", default=".")
    rm = s.add_parser("remember", help="add a lesson to a project's memory (read by every later review)")
    rm.add_argument("project", help="owner/name"); rm.add_argument("lesson")
    pp = s.add_parser("proposals", help="list memory proposals from down-votes, or accept one")
    pp.add_argument("project", help="owner/name"); pp.add_argument("--accept", type=int, help="accept proposal N")
    rr = s.add_parser("routing-replay", help="replay stored reviews offline: what each cost-routing rule would lose")
    rr.add_argument("--include-self", action="store_true", help="include crucible's reviews of itself")
    ar = s.add_parser("anchor-replay", help="re-verify answered findings with and without the reviewer's argument "
                      "(model calls: costs money)")
    ar.add_argument("--clones", nargs="+", required=True, help="directories holding local clones of the reviewed repos")
    ar.add_argument("--per-class", type=int, default=0, help="at most N refuted and N held-up findings (default: all)")
    ar.add_argument("--jobs", type=int, default=4); ar.add_argument("--budget", type=float, help="stop spending at USD")
    ar.add_argument("--include-self", action="store_true", help="include crucible's reviews of itself")
    ar.add_argument("--votes", type=_positive_int, default=1,
                    help="verifier calls per arm; kept only if every vote keeps it (default 1; each vote costs a call)")
    mr = s.add_parser("model-replay", help="re-review stored full rounds with each reviewer model and score them "
                      "against the author's answers (model calls: costs money)")
    mr.add_argument("--clones", nargs="+", required=True, help="directories holding local clones of the reviewed repos")
    mr.add_argument("--models", nargs="+", default=["opus", "sonnet"],
                    help="reviewer models, the first being the one the stored rounds used (opus|sonnet|fable|haiku or "
                    "an id; default: opus sonnet)")
    mr.add_argument("--rounds", type=_positive_int, default=5, help="stored rounds to replay (default 5)")
    mr.add_argument("--budget", type=float, help="USD cap for each arm's review of one round")
    mr.add_argument("--include-self", action="store_true", help="include crucible's reviews of itself")
    sa = s.add_parser("stats", help="real-PR precision log from stored reviews: unique kept/dropped/fixed/deferred/refuted")
    sa.add_argument("--project", help="owner/name (default: every project)")
    sa.add_argument("--include-self", action="store_true", help="include crucible's reviews of itself")
    sa.add_argument("--since", type=_iso_time, help="only reviews finished at or after this local time (YYYY-MM-DD[THH:MM])")
    sa.add_argument("--json", action="store_true", help='machine-readable ("answered": false when there is no data)')
    ev = s.add_parser("eval", help="run the review on labelled fixture changes (eval/cases) and score it")
    ev.add_argument("--cases", nargs="*", help="substrings of case names to run (default: all)")
    ev.add_argument("--split", choices=("build", "holdout"), help="run only build or only held-out cases (default: both)")
    ev.add_argument("--review-model"); ev.add_argument("--verify-model"); ev.add_argument("--cheap-model")
    ev.add_argument("--no-tiers", action="store_true"); ev.add_argument("--budget", type=float, default=1.5)
    ev.add_argument("--jobs", type=int, default=4); ev.add_argument("--label")
    ev.add_argument("--cache", help="shared review/verification cache dir across cases and runs (default: none)")
    ev.add_argument("--no-write", action="store_true", help="don't update eval/RESULTS.md and history")
    a = p.parse_args(argv)
    {"review": cmd_review, "status": cmd_status, "answer": cmd_answer, "waive": cmd_waive, "learn": cmd_learn, "prep": cmd_prep,
     "polish": cmd_polish, "reply": cmd_reply, "vote": cmd_vote, "remember": cmd_remember, "proposals": cmd_proposals, "eval": cmd_eval,
     "routing-replay": cmd_routing_replay, "anchor-replay": cmd_anchor_replay, "stats": cmd_stats,
     "model-replay": cmd_model_replay}[a.cmd](a)


if __name__ == "__main__":
    main()
