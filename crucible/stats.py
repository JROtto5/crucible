"""`crucible stats`: the real-PR precision log, from the stored reviews, offline (no model calls).

Counts model findings only (scanner and style findings are recomputed every round and are not the reviewer's
precision). One finding shown in several rounds counts once: findings are the same when they share an id (carried
by an incremental round) or, within one project, a normalized title (a full re-review of an amended commit gives
the same finding a new id). Two different findings with one title in one project therefore count once; that
undercounts, it never inflates.

A unique finding is "kept" if verification kept it in any round, "dropped" if it was always dropped. Its answer is
the latest one given to any of its ids (answers are carried by id, so a fixed finding stays fixed)."""
import collections, glob, json, os, re

from .util import SEV, read_json

DISPOSITIONS = ("fixed", "deferred", "refuted")


def _norm(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


class _Groups:
    """Union-find over finding keys."""
    def __init__(self):
        self.parent = {}

    def find(self, k):
        self.parent.setdefault(k, k)
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _load(root, include_self, project):
    reviews, answers = [], {}
    for p in sorted(glob.glob(os.path.join(root, "*", "*", "review.json"))):
        rev = read_json(p)
        if not rev or rev.get("status") != "done":
            continue
        repo = rev.get("repo") or os.path.basename(os.path.dirname(os.path.dirname(p)))
        if not include_self and repo.endswith("__crucible"):
            continue
        if project and repo != project.replace("/", "__"):
            continue
        reviews.append((repo, rev))
        for fid, a in (read_json(os.path.join(os.path.dirname(p), "answers.json"), {}) or {}).items():
            if a and a.get("disposition") in DISPOSITIONS:
                prev = answers.get((repo, fid))
                if prev is None or (a.get("at") or "") >= (prev.get("at") or ""):
                    answers[(repo, fid)] = a
    return reviews, answers


def collect(root, include_self=False, project=None):
    """-> {"overall": row, "projects": {repo: row}, "reviews": n, "cost": usd}. A row counts unique findings."""
    reviews, answers = _load(root, include_self, project)
    g, findings = _Groups(), []                    # findings: (repo, id, title_key, kept, severity)
    for repo, rev in reviews:
        for f, kept in [(f, True) for f in rev.get("findings", [])] + [(f, False) for f in rev.get("dropped", [])]:
            if f.get("source") != "review" or not f.get("id"):
                continue
            ik, tk = ("id", repo, f["id"]), ("title", repo, _norm(f.get("title")))
            g.union(ik, tk)
            findings.append((repo, ik, kept, f.get("severity", "low")))
    uniq = {}
    for repo, ik, kept, sev in findings:
        u = uniq.setdefault(g.find(ik), {"repo": repo, "ids": set(), "kept": False, "sev": "low"})
        u["ids"].add(ik[2])
        if kept:
            u["kept"] = True
            if sev in SEV and SEV.index(sev) < SEV.index(u["sev"]):
                u["sev"] = sev                     # the worst severity it was kept at

    def row():
        return {"unique": 0, "kept": 0, "dropped": 0, "kept_by_severity": collections.Counter(),
                "fixed": 0, "deferred": 0, "refuted": 0, "unanswered": 0, "reviews": 0, "cost": 0.0}
    overall, per = row(), collections.defaultdict(row)
    for u in uniq.values():
        latest = None
        for fid in u["ids"]:
            a = answers.get((u["repo"], fid))
            if a and (latest is None or (a.get("at") or "") >= (latest.get("at") or "")):
                latest = a
        for r in (overall, per[u["repo"]]):
            r["unique"] += 1
            if not u["kept"]:
                r["dropped"] += 1
                continue
            r["kept"] += 1
            r["kept_by_severity"][u["sev"]] += 1
            r[latest["disposition"] if latest else "unanswered"] += 1
    for repo, rev in reviews:
        for r in (overall, per[repo]):
            r["reviews"] += 1
            r["cost"] += rev.get("cost_usd") or 0
    return {"overall": overall, "projects": dict(sorted(per.items()))}


def held_up(r):
    """Answered kept findings that were not refuted, as (held, answered); None when nothing is answered."""
    answered = r["fixed"] + r["deferred"] + r["refuted"]
    return (r["fixed"] + r["deferred"], answered) if answered else None


def _line(name, r):
    h = held_up(r)
    held = f"{h[0]}/{h[1]} ({h[0] / h[1]:.0%})" if h else "-"
    per = f"${r['cost'] / r['reviews']:.2f}" if r["reviews"] else "-"
    return (f"{name:<44} {r['reviews']:>4} {per:>7} {r['unique']:>6} {r['kept']:>5} {r['dropped']:>5} "
            f"{r['fixed']:>5} {r['deferred']:>5} {r['refuted']:>5} {r['unanswered']:>6}  {held}")


def report(s):
    o = s["overall"]
    head = (f"{'project':<44} {'revs':>4} {'$/rev':>7} {'unique':>6} {'kept':>5} {'drop':>5} "
            f"{'fixed':>5} {'defer':>5} {'refut':>5} {'unans':>6}  held up (answered, not refuted)")
    out = [head, "-" * len(head)] + [_line(p.replace("__", "/"), r) for p, r in s["projects"].items()]
    out += ["-" * len(head), _line("overall", o), ""]
    if o["unique"]:
        sev = ", ".join(f"{k} {o['kept_by_severity'][k]}" for k in SEV if o["kept_by_severity"][k])
        out.append(f"Unique model findings: {o['unique']}; verification kept {o['kept']} ({o['kept'] / o['unique']:.0%})"
                   f" and dropped {o['dropped']}. Kept by severity: {sev or 'none'}.")
    out.append("Counts are unique findings (same id, or same title in one project, count once); model findings only.")
    return "\n".join(out)


def to_json(s):
    def plain(r):
        return dict(r, kept_by_severity=dict(r["kept_by_severity"]), cost=round(r["cost"], 4))
    return json.dumps({"overall": plain(s["overall"]), "projects": {k: plain(v) for k, v in s["projects"].items()}},
                      indent=1)
