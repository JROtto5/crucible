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
  crucible eval    [--cases ...] [--no-tiers] [--label L]         score the reviewer on labelled fixtures (eval/)
  crucible routing-replay [--include-self]                        what cost-routing rules would lose, on stored reviews

crucible never pushes, comments, approves or posts. A human submits."""
import argparse, datetime as dt, os, sys
from . import __version__
from .util import Failed, HOME, project_dir, project_key, read_json, write_json


def _p(repo):
    return os.path.abspath(repo)


def cmd_review(a):
    from .review import run_review
    try:
        run_review(_p(a.repo), a.base, a.force, a.budget, a.author, a.draft, a.base_checks, a.offline, a.skip_checks,
                   full=a.full, fresh=a.fresh, no_tiers=a.no_tiers, route=a.route or None)
    except Failed as e:
        sys.exit(f"crucible: {e}")
    return cmd_status(a)


def cmd_status(a):
    from .review import load, load_waivers, report, verdict
    project, sha, d, rev, ans = load(_p(a.repo))
    if not rev:
        print(f"NO REVIEW for HEAD {sha[:10]}. Run: crucible review {a.repo}")
        sys.exit(2)
    from .util import git
    txt = report(rev, ans, load_waivers(project, git(_p(a.repo), "rev-parse", "--abbrev-ref", "HEAD", check=False)))
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
    from .review import load, waivers_path
    from .util import git
    project, sha, d, rev, ans = load(_p(a.repo))
    if not rev or rev.get("status") != "done":
        sys.exit("no completed review for this HEAD")
    items = {i["item"] for i in rev["readiness"]["items"]}
    if a.item not in items:
        sys.exit(f"unknown readiness item {a.item!r}; one of: {sorted(items)}")
    if len(a.reason.strip()) < 20:
        sys.exit("give a real reason (20+ characters): it is printed in the report")
    branch = git(_p(a.repo), "rev-parse", "--abbrev-ref", "HEAD", check=False)
    allw = read_json(waivers_path(project), {}) or {}
    allw.setdefault(branch, {})[a.item] = a.reason.strip()
    write_json(waivers_path(project), allw)
    print(f"waived {a.item!r} on branch {branch}")


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


def main(argv=None):
    p = argparse.ArgumentParser(prog="crucible", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("review"); r.add_argument("repo", nargs="?", default=".")
    r.add_argument("--base"); r.add_argument("--force", action="store_true"); r.add_argument("--budget", type=float)
    r.add_argument("--author", help="model id that wrote the change (else read from Co-Authored-By trailers)")
    r.add_argument("--draft", help="path to the PR description draft (default PR_DRAFT.md in the repo)")
    r.add_argument("--base-checks", action="store_true", help="re-run failing checks on the base to spot pre-existing failures")
    r.add_argument("--skip-checks", action="store_true"); r.add_argument("--offline", action="store_true")
    r.add_argument("--full", action="store_true", help="review the whole change, not just what changed since the last review")
    r.add_argument("--fresh", action="store_true", help="redo the review and bypass the review/verification cache (--force alone reuses it, so verdicts are stable)")
    r.add_argument("--no-tiers", action="store_true", help="verify every finding with the strong model only")
    r.add_argument("--route", action="store_true", help="route by change type: a docs/PR-text-only round gets one cheaper "
                   "pass (also CRUCIBLE_ROUTE=1); see `crucible routing-replay`")
    st = s.add_parser("status"); st.add_argument("repo", nargs="?", default=".")
    an = s.add_parser("answer"); an.add_argument("id"); an.add_argument("disposition", choices=["fixed", "refuted", "deferred"])
    an.add_argument("note"); an.add_argument("--repo", default=".")
    wv = s.add_parser("waive", help="mark a readiness item as not applicable, with a reason shown in the report"); wv.add_argument("item"); wv.add_argument("reason"); wv.add_argument("--repo", default=".")
    le = s.add_parser("learn"); le.add_argument("repo", nargs="?", default="."); le.add_argument("--prs", type=int, default=25)
    le.add_argument("--no-style", action="store_true")
    pr = s.add_parser("prep"); pr.add_argument("repo", nargs="?", default=".")
    po = s.add_parser("polish"); po.add_argument("repo", nargs="?", default=".")
    rp = s.add_parser("reply"); rp.add_argument("url"); rp.add_argument("--repo")
    vo = s.add_parser("vote"); vo.add_argument("id"); vo.add_argument("vote", choices=["up", "down"]); vo.add_argument("reason")
    vo.add_argument("--repo", default=".")
    rm = s.add_parser("remember"); rm.add_argument("project"); rm.add_argument("lesson")
    pp = s.add_parser("proposals"); pp.add_argument("project"); pp.add_argument("--accept", type=int)
    rr = s.add_parser("routing-replay", help="replay stored reviews offline: what each cost-routing rule would lose")
    rr.add_argument("--include-self", action="store_true", help="include crucible's reviews of itself")
    ev = s.add_parser("eval", help="run the review on labelled fixture changes (eval/cases) and score it")
    ev.add_argument("--cases", nargs="*", help="substrings of case names to run (default: all)")
    ev.add_argument("--review-model"); ev.add_argument("--verify-model"); ev.add_argument("--cheap-model")
    ev.add_argument("--no-tiers", action="store_true"); ev.add_argument("--budget", type=float, default=1.5)
    ev.add_argument("--jobs", type=int, default=4); ev.add_argument("--label")
    ev.add_argument("--cache", help="shared review/verification cache dir across cases and runs (default: none)")
    ev.add_argument("--no-write", action="store_true", help="don't update eval/RESULTS.md and history")
    a = p.parse_args(argv)
    {"review": cmd_review, "status": cmd_status, "answer": cmd_answer, "waive": cmd_waive, "learn": cmd_learn, "prep": cmd_prep,
     "polish": cmd_polish, "reply": cmd_reply, "vote": cmd_vote, "remember": cmd_remember, "proposals": cmd_proposals, "eval": cmd_eval,
     "routing-replay": cmd_routing_replay}[a.cmd](a)


if __name__ == "__main__":
    main()
