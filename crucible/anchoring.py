"""`crucible anchor-replay`: does the verifier do better without the reviewer's argument?

The verifier is shown a finding's claim and falsification test, not the reviewer's `problem`/`fix` text. This replays
findings the author has since answered, at the commit they were raised on, through the verifier twice: once with
today's prompt and once with the argument added back. Answers are the labels: refuted = a false alarm, fixed or
deferred = a real finding. It reports, per arm, how many false alarms each still keeps and how many real findings it
drops, and what it cost.

Only findings on tracked files are replayed. A finding on the PR draft can't be: the stored review keeps the draft's
hash, not its text. Each commit is checked out from a local clone that has it (`--clones`, searched a few levels
deep) into a throwaway `git clone --shared` under the temp dir, so the clone itself is never touched."""
import concurrent.futures as cf, glob, os, shutil, subprocess, tempfile

from .util import Budget, Failed, git, read_json

DISPOSITIONS = ("fixed", "deferred", "refuted")
ARMS = ("without", "with")      # without the argument = today's prompt


def answered(root, include_self=False):
    """One entry per answered model finding (repo, id), from the earliest stored round that raised it."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "*", "*", "review.json"))):
        d = os.path.dirname(p)
        repo = os.path.basename(os.path.dirname(d))
        if not include_self and repo.endswith("__crucible"):
            continue
        rev = read_json(p)
        if not rev or rev.get("status") != "done":
            continue
        ans = read_json(os.path.join(d, "answers.json"), {}) or {}
        for f in rev.get("findings", []):
            a = ans.get(f.get("id"))
            if f.get("source") != "review" or not a or a.get("disposition") not in DISPOSITIONS:
                continue
            key = (repo, f["id"])
            started = rev.get("started") or ""
            if key not in out or started < out[key]["started"]:
                out[key] = {"repo": repo, "sha": rev["sha"], "started": started, "finding": f,
                            "disposition": a["disposition"], "draft": (rev.get("inputs") or {}).get("draft")}
    return sorted(out.values(), key=lambda e: (e["repo"], e["finding"]["id"]))


def on_draft(e):
    """A finding on the PR description: its text at review time isn't stored, so it can't be replayed."""
    f = e["finding"]["file"] or ""
    return f == "PR_DRAFT.md" or os.path.isabs(f) or (e["draft"] and os.path.basename(e["draft"]) == os.path.basename(f))


def sample(entries, per_class):
    """Every refuted finding up to `per_class`, and as many held-up ones, taken evenly across the sorted list so one
    busy project doesn't fill the sample. Deterministic, so a re-run replays the same findings."""
    out = []
    for cls in (("refuted",), ("fixed", "deferred")):
        pool = [e for e in entries if e["disposition"] in cls]
        if per_class and len(pool) > per_class:
            step = len(pool) / per_class
            pool = [pool[int(i * step)] for i in range(per_class)]
        out += pool
    return out


def find_clones(dirs, depth=3):
    found = []
    for top in dirs:
        top = os.path.expanduser(top)
        for cur, subdirs, files in os.walk(top):
            if cur[len(top):].count(os.sep) >= depth:
                subdirs[:] = []
            if ".git" in subdirs or ".git" in files:
                found.append(cur)
                subdirs[:] = []
            subdirs[:] = [s for s in subdirs if s != "node_modules" and not s.startswith(".")]
    return found


def has_commit(clone, sha):
    """Without GIT_NO_LAZY_FETCH a partial clone asks its promisor remote for a commit it lacks: a network round trip
    per clone (~1.3 s each on the oss-grind clones) that would also write the fetched objects into the clone."""
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
    return subprocess.run(["git", "-C", clone, "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True,
                          env=env).returncode == 0


def checkout(clone, sha, into):
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", clone, into], check=True, capture_output=True)
    git(into, "checkout", "--quiet", "--detach", sha)
    return into


def judge(entries, verify, jobs=4):
    """verify(entry, argument: bool) -> (keep, cost). Returns one row per entry with each arm's keep and cost (an arm
    whose call failed has keep None and counts in neither tally)."""
    rows = [dict(e, arms={}) for e in entries]
    tasks = [(r, arm) for r in rows for arm in ARMS]

    def run(t):
        r, arm = t
        try:
            keep, cost = verify(r, arm == "with")
            return r, arm, {"keep": bool(keep), "cost": cost or 0.0}
        except Failed as ex:
            return r, arm, {"keep": None, "cost": 0.0, "error": str(ex)[:200]}

    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for r, arm, res in ex.map(run, tasks):
            r["arms"][arm] = res
    return rows


def tally(rows):
    t = {arm: {"false_alarms_kept": 0, "refuted": 0, "real_dropped": 0, "real": 0, "failed": 0, "cost": 0.0}
         for arm in ARMS}
    for r in rows:
        for arm in ARMS:
            res, s = r["arms"].get(arm), t[arm]
            if not res:
                continue
            s["cost"] += res["cost"]
            if res["keep"] is None:
                s["failed"] += 1
            elif r["disposition"] == "refuted":
                s["refuted"] += 1
                s["false_alarms_kept"] += res["keep"]
            else:
                s["real"] += 1
                s["real_dropped"] += not res["keep"]
    return t


def report(rows, skipped):
    t = tally(rows)
    out = [f"Anchoring replay: {len(rows)} answered findings re-verified at the commit they were raised on, "
           "with and without the reviewer's argument in the verifier prompt.",
           "Labels are the author's answers: refuted = false alarm; fixed/deferred = real."]
    for k, v in skipped.items():
        if v:
            out.append(f"  skipped {v}: {k}")
    out.append("")
    for arm in ARMS:
        s = t[arm]
        label = "without the argument (today's prompt)" if arm == "without" else "with the argument"
        out.append(f"- {label}: false alarms still kept {s['false_alarms_kept']}/{s['refuted']}, "
                   f"real findings dropped {s['real_dropped']}/{s['real']}, failed calls {s['failed']}, ${s['cost']:.2f}")
    diff = [r for r in rows if None not in (r["arms"].get("with", {}).get("keep"), r["arms"].get("without", {}).get("keep"))
            and r["arms"]["with"]["keep"] != r["arms"]["without"]["keep"]]
    if diff:
        out += ["", "Findings the two arms disagree on:"]
        for r in diff:
            f = r["finding"]
            out.append(f"  {r['repo']} {f['id']} [{r['disposition']}] without: {'kept' if r['arms']['without']['keep'] else 'dropped'}"
                       f", with: {'kept' if r['arms']['with']['keep'] else 'dropped'} · {f['title'][:70]}")
    return "\n".join(out)


def run(root, clones, per_class=0, jobs=4, budget=None, include_self=False):
    from .review import region, verify_tiers, verify_tiered, choose_models
    entries = answered(root, include_self)
    skipped = {"on the PR draft (its text isn't stored)": 0, "no local clone has the commit": 0}
    code = []
    for e in entries:
        if on_draft(e):
            skipped["on the PR draft (its text isn't stored)"] += 1
        else:
            code.append(e)
    picked = sample(code, per_class)
    repos = find_clones(clones)
    where = {}
    for e in picked:
        if e["sha"] not in where:
            where[e["sha"]] = next((c for c in repos if has_commit(c, e["sha"])), None)
    ready = [e for e in picked if where[e["sha"]]]
    skipped["no local clone has the commit"] = len(picked) - len(ready)
    tmp = tempfile.mkdtemp(prefix="crucible-anchor-")
    trees, bud = {}, Budget(budget)
    # replayed verdicts go to a throwaway cache: written to the real one, the "without" arm would replace the verdict
    # a later `review --force` on that commit is meant to reproduce
    old_cache = os.environ.get("CRUCIBLE_CACHE")
    os.environ["CRUCIBLE_CACHE"] = os.path.join(tmp, "cache")
    try:
        for e in ready:
            if e["sha"] not in trees:
                trees[e["sha"]] = checkout(where[e["sha"]], e["sha"], os.path.join(tmp, e["sha"][:12]))

        def verify(r, argument):
            tree, f = trees[r["sha"]], r["finding"]
            tiers = verify_tiers(choose_models(tree, "HEAD")[1])     # today's verifier, not the one that ran then
            v, trail = verify_tiered(f, region(tree, r["sha"], f["file"], f["line"]), tree, bud, tiers,
                                     fresh=True, argument=argument)
            return v["keep"], sum(t.get("cost", 0) for t in trail)

        rows = judge(ready, verify, jobs)
    finally:
        if old_cache is None:
            os.environ.pop("CRUCIBLE_CACHE", None)
        else:
            os.environ["CRUCIBLE_CACHE"] = old_cache
        shutil.rmtree(tmp, ignore_errors=True)
    return rows, skipped
