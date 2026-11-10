"""`crucible stats`: the real-PR precision log, from the stored reviews, offline (no model calls).

Counts model findings only (scanner and style findings are recomputed every round and are not the reviewer's
precision). One finding shown in several rounds counts once: findings are the same when they share an id (carried
by an incremental round) or, within one project, a normalized title (a full re-review of an amended commit gives
the same finding a new id). Two different findings with one title in one project therefore count once; that
undercounts, it never inflates.

A unique finding is "kept" if verification kept it in any round, "dropped" if it was always dropped. Its answer is
the latest one given to any of its ids (answers are carried by id, so a fixed finding stays fixed).

`since` keeps the reviews that finished at or after it (a finding counts in the window if a round in the window
showed it; its answer may come from any round). Every report says what it read and how new the newest review is,
and a window with no reviews prints "no data", never a row of zeros: a store that stopped being written looks
exactly like a quiet day otherwise.

Tokens: a review is metered when it stored `tokens_review` and `tokens_verify` and every model call in it reported
its usage, with no result served from the cache (the review that paid for a cached result may be overwritten by
a --force re-run, failed, or outside the window). Other reviews are "not recorded", never 0. Tokens per held-up finding is computed on the metered
reviews alone (their tokens over the findings that held up among them), so both halves of the ratio cover the same
reviews. A failed review's tokens are not counted, as its cost isn't."""
import collections, glob, json, math, os, re

from .util import SEV, TOKEN_KINDS, read_json

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


QUOTE_N = 60      # answered findings before a held-up share is worth quoting (Wilson half-width ~9 pp at 83%)


def when(rev):
    """When a stored review finished (else started), as its ISO string; None for an undated legacy record."""
    return rev.get("finished") or rev.get("started") or None


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes of n, as (lo, hi); None when n is 0."""
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def metered(rev):
    """True when a stored review has complete token counts (see the module note)."""
    tr, tv = rev.get("tokens_review"), rev.get("tokens_verify")
    return bool(tr and tv) and not any(t.get(k) for t in (tr, tv) for k in ("unmetered_calls", "cached_calls"))


def _load(root, include_self, project, since=None):
    reviews, answers, seen = [], {}, []
    for p in sorted(glob.glob(os.path.join(root, "*", "*", "review.json"))):
        rev = read_json(p)
        if not rev or rev.get("status") != "done":
            continue
        repo = rev.get("repo") or os.path.basename(os.path.dirname(os.path.dirname(p)))
        if not include_self and repo.endswith("__crucible"):
            continue
        if project and repo != project.replace("/", "__"):
            continue
        seen.append(when(rev))
        if not since or (when(rev) or "") >= since:
            reviews.append((repo, rev))
        for fid, a in (read_json(os.path.join(os.path.dirname(p), "answers.json"), {}) or {}).items():
            if a and a.get("disposition") in DISPOSITIONS:
                prev = answers.get((repo, fid))
                if prev is None or (a.get("at") or "") >= (prev.get("at") or ""):
                    answers[(repo, fid)] = a
    dated = [t for t in seen if t]
    window = {"since": since, "project": project, "stored": len(seen), "undated": len(seen) - len(dated),
              "newest": max(dated) if dated else None, "in_window": len(reviews)}
    return reviews, answers, window


def collect(root, include_self=False, project=None, since=None, metered_only=False):
    """-> {"overall": row, "projects": {repo: row}, "window": {...}, "metered": row}. A row counts unique findings,
    plus the reviews, their cost and tokens. "window" says what was read: stored reviews, the newest one's time, and
    how many fell in `since`. "metered" is the overall row over the metered reviews only (for tokens per held-up
    finding); `metered_only` restricts everything to them."""
    reviews, answers, window = _load(root, include_self, project, since)
    if metered_only:
        reviews = [(repo, rev) for repo, rev in reviews if metered(rev)]
    g, findings = _Groups(), []                    # findings: (repo, id, title_key, kept, severity)
    for repo, rev in reviews:
        for f, kept in [(f, True) for f in rev.get("findings", [])] + [(f, False) for f in rev.get("dropped", [])]:
            if f.get("source") != "review" or not f.get("id"):
                continue
            if (f.get("verification") or {}).get("method") == "rule":   # never judged by the verifier
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
                "fixed": 0, "deferred": 0, "refuted": 0, "unanswered": 0, "reviews": 0, "cost": 0.0,
                "metered_reviews": 0, "tokens": dict.fromkeys(("total", "review", "verify") + TOKEN_KINDS, 0),
                "by_kind_reviews": 0, "by_kind": {}}
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
            if metered(rev):
                r["metered_reviews"] += 1
                t = r["tokens"]
                for part in ("review", "verify"):
                    p = rev[f"tokens_{part}"]
                    t[part] += p.get("total", 0)
                    t["total"] += p.get("total", 0)
                    for k in TOKEN_KINDS:
                        t[k] += p.get(k, 0)
                if rev.get("tokens_by_kind"):          # stored since per-kind metering; older reviews lack it
                    r["by_kind_reviews"] += 1
                    for name, k in rev["tokens_by_kind"].items():
                        a = r["by_kind"].setdefault(name, {"calls": 0, "no_tools": True, "cost_usd": 0.0,
                                                           **dict.fromkeys(TOKEN_KINDS, 0)})
                        a["calls"] += k.get("calls", 0)
                        a["cost_usd"] += k.get("cost_usd", 0)
                        if k.get("calls"):
                            a["no_tools"] = a["no_tools"] and k.get("no_tools", False)
                        for n in TOKEN_KINDS:
                            a[n] += k.get(n, 0)
    out = {"overall": overall, "projects": dict(sorted(per.items())), "window": window}
    if not metered_only:
        out["metered"] = collect(root, include_self, project, since, metered_only=True)["overall"]
    return out


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


def _source(w):
    newest = (w["newest"] or "never").replace("T", " ")[:16]
    undated = f", {w['undated']} undated" if w["undated"] else ""
    of = f" of {w['project']}" if w.get("project") else ""
    n = w["stored"]
    return f"Read {n} finished review{'' if n == 1 else 's'}{of}{undated}; the newest is from {newest}."


def no_data(s):
    """True when the window holds no review: the report must say "no data", not print zeros."""
    return s["window"]["in_window"] == 0


def report(s):
    o, w = s["overall"], s["window"]
    if no_data(s):
        scope = (f" of {w['project']}" if w.get("project") else "") + (
            f" since {w['since'].replace('T', ' ')}" if w["since"] else " stored")
        where = "in this window" if w["since"] else "here"
        return (f"No data: no finished review{scope}. {_source(w)}\n"
                f"That is missing data, not a zero: nothing {where} was reviewed or stored.")
    head = (f"{'project':<44} {'revs':>4} {'$/rev':>7} {'unique':>6} {'kept':>5} {'drop':>5} "
            f"{'fixed':>5} {'defer':>5} {'refut':>5} {'unans':>6}  held up (answered, not refuted)")
    out = [head, "-" * len(head)] + [_line(p.replace("__", "/", 1), r) for p, r in s["projects"].items()]
    out += ["-" * len(head), _line("overall", o), ""]
    if o["unique"]:
        sev = ", ".join(f"{k} {o['kept_by_severity'][k]}" for k in SEV if o["kept_by_severity"][k])
        out.append(f"Unique model findings: {o['unique']}; verification kept {o['kept']} ({o['kept'] / o['unique']:.0%})"
                   f" and dropped {o['dropped']}. Kept by severity: {sev or 'none'}.")
        h = held_up(o)
        if h:
            lo, hi = wilson(*h)
            quote = "" if h[1] >= QUOTE_N else f"; n={h[1]} < {QUOTE_N}, too few to quote as a rate"
            out.append(f"Held up: {h[0]}/{h[1]} = {h[0] / h[1]:.0%} (Wilson 95% {lo:.0%}-{hi:.0%}{quote}).")
            out.append(f"Held up covers only answered findings: {o['unanswered']} of {o['kept']} kept are unanswered.")
            if h[0]:
                out.append(f"Cost per held-up finding: ${o['cost'] / h[0]:.2f} (${o['cost']:.2f} over {h[0]}).")
    out.append(tokens_line(s))
    if w["since"]:
        out.append(f"Window: reviews finished since {w['since'].replace('T', ' ')}: {w['in_window']} of {w['stored']}.")
    out.append(_source(w))
    out.append("Counts are unique findings (same id, or same title in one project, count once); model findings only.")
    return "\n".join(out)


def tokens(s):
    """The token figures, or None when no review in the window was metered."""
    m = s.get("metered") or {}
    n = m.get("metered_reviews", 0)
    if not n:
        return None
    t, h = m["tokens"], held_up(m)
    kinds = {name: dict(k, cost_usd=round(k["cost_usd"], 4)) for name, k in sorted(m.get("by_kind", {}).items())}
    return {"metered_reviews": n, "reviews": s["overall"]["reviews"], **t, "per_review": round(t["total"] / n),
            "by_kind_reviews": m.get("by_kind_reviews", 0), "by_kind": kinds,
            "held_up": {"held": h[0], "answered": h[1]} if h else None,
            "per_held_up": round(t["total"] / h[0]) if h and h[0] else None}


def tokens_line(s):
    t = tokens(s)
    if not t:
        return ("Tokens: not recorded (no review here has complete token counts: reviews before token metering "
                "stored cost only, and a review with a cache hit or an uncounted call is left out).")
    parts = ", ".join(f"{k.replace('_', ' ')} {t[k]:,}" for k in TOKEN_KINDS)
    line = (f"Tokens ({t['metered_reviews']} of {t['reviews']} reviews metered): {t['per_review']:,} per review "
            f"({t['total']:,} in all: {parts}; review passes {t['review']:,}, verification {t['verify']:,}). ")
    line += kinds_line(t)
    h = t["held_up"]
    if not h:
        return line + "Tokens per held-up finding: none answered yet in the metered reviews."
    if not h["held"]:
        return line + f"Tokens per held-up finding: none held up ({h['answered']} answered in the metered reviews)."
    lo, hi = wilson(h["held"], h["answered"])
    quote = "" if h["answered"] >= QUOTE_N else f"; n={h['answered']} < {QUOTE_N}, too few to quote as a rate"
    return line + (f"Tokens per held-up finding: {t['per_held_up']:,} ({h['held']}/{h['answered']} held up in the "
                   f"metered reviews, Wilson 95% {lo:.0%}-{hi:.0%}{quote}).")


def kinds_line(t):
    """By call kind, over the metered reviews that stored it: calls, the CLI's own $ and the cache write / read
    tokens. The split the no-tools caching A/B starts from (a no-tools call is one turn: its cache writes are only
    re-read by a later identical prefix). Empty when no metered review has it."""
    if not t.get("by_kind"):
        return ""
    parts = [f"{name}{' (no tools)' if k['no_tools'] else ''} {k['calls']} calls ${k['cost_usd']:.2f}, "
             f"cache write {k['cache_creation']:,} / read {k['cache_read']:,}" for name, k in t["by_kind"].items()]
    return f"By call kind ({t['by_kind_reviews']} of {t['metered_reviews']} metered reviews): " + "; ".join(parts) + ". "


def to_json(s):
    def plain(r):
        return dict(r, kept_by_severity=dict(r["kept_by_severity"]), cost=round(r["cost"], 4),
                    by_kind={n: dict(k, cost_usd=round(k["cost_usd"], 4)) for n, k in r["by_kind"].items()})
    if no_data(s):                         # "answered": false, as for any figure that isn't there
        return json.dumps({"answered": False, "overall": None, "projects": {}, "window": s["window"]}, indent=1)
    h = held_up(s["overall"])
    ci = wilson(*h) if h else None
    return json.dumps({"answered": True, "overall": plain(s["overall"]),
                       "projects": {k: plain(v) for k, v in s["projects"].items()}, "window": s["window"],
                       "held_up": {"held": h[0], "answered": h[1], "wilson95": [round(ci[0], 4), round(ci[1], 4)],
                                   "quotable": h[1] >= QUOTE_N} if h else None,
                       "tokens": tokens(s) or {"answered": False, "reason": "not recorded"}}, indent=1)
