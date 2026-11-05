"""Cost routing by change type, and the replay over stored reviews that decides which routing rules may be used.

Routing is off unless asked for (`crucible review --route`, or CRUCIBLE_ROUTE=1/true/yes). One rule is implemented:
a round whose changed files are all docs/PR text gets one cheaper pass (the mid model reviews, and verification
stops at the cheap tier). Code changes keep the full pipeline.

`crucible routing-replay` replays the stored reviews (~/.crucible/reviews/*/*/review.json) offline, at no model
cost, and reports what each candidate rule would have changed: findings lost or downgraded by severity (and
whether the author later answered them "fixed"), extra findings kept, and the refuted share before and after.
A rule that would lose an important/critical finding, or lose or downgrade a medium, stays off."""
import collections, glob, os, re

from .util import MODELS, SEV, read_json

# docs and PR text: prose markup files and the usual extension-less top-level prose files. Not .txt (requirements.txt,
# CMakeLists.txt) and not "anything under docs/" (docs/conf.py runs). Agent instructions, and prompt/guide files outside
# a docs/ tree, are prose that changes a tool's behaviour, so they count as code.
DOC_RX = re.compile(r"(\.(?:md|markdown|rst|adoc)$|(?:^|/)(?:README|CHANGELOG|CHANGES|LICENSE|CONTRIBUTING|AUTHORS|NEWS)"
                    r"(?:\.txt)?$)", re.I)
AGENT_RX = re.compile(r"(?:^|/)(?:CLAUDE|AGENTS|GEMINI|SKILL)\.md$|(?:^|/)\.(?:claude|cursor)/", re.I)
# outside a docs tree: improve-prompt.md, copilot-instructions.md, prompts/, a package's guides/
PROMPT_RX = re.compile(r"(?:^|/)[^/]*(?:prompt|instruction)[^/]*$|(?:^|/)(?:prompts?|guides)/", re.I)
DOCS_TREE_RX = re.compile(r"(?:^|/)docs?/", re.I)


def is_doc(path):
    if not DOC_RX.search(path) or AGENT_RX.search(path):
        return False
    return bool(DOCS_TREE_RX.search(path)) or not PROMPT_RX.search(path)


def change_kind(paths):
    """"docs" when every changed path is docs or PR text (and there is at least one), else "code"."""
    paths = [p for p in paths if p]
    return "docs" if paths and all(is_doc(p) for p in paths) else "code"


def enabled(flag=None):
    """--route wins; otherwise CRUCIBLE_ROUTE, where only 1/true/yes turn it on (so "false" or "off" don't)."""
    if flag is not None:
        return bool(flag)
    return os.environ.get("CRUCIBLE_ROUTE", "").strip().lower() in ("1", "true", "yes")


def route(kind, review_model, tiers, authors=()):
    """-> (review_model, tiers) for this round. A docs round is reviewed by the mid model (unless it wrote the
    change; then the normal reviewer stays) and verified by the cheap tier only. Code is unchanged."""
    if kind != "docs":
        return review_model, tiers
    mid = os.environ.get("CRUCIBLE_ROUTE_DOCS_MODEL", MODELS["sonnet"])
    return (review_model if mid in authors else mid), tiers[:1]


# ---------- replay ----------
def _reviews(root, include_self):
    for p in sorted(glob.glob(os.path.join(root, "*", "*", "review.json"))):
        rev = read_json(p)
        if not rev or rev.get("status") != "done":
            continue
        if not include_self and rev.get("repo", "").endswith("__crucible"):
            continue
        yield p, rev


def _answers(root):
    """Every answer by finding id, across all reviewed commits (answers are carried by id)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "*", "*", "answers.json")), key=os.path.getmtime):
        for fid, a in (read_json(p, {}) or {}).items():
            out[fid] = (a or {}).get("disposition")
    return out


def _files(rev):
    inc = rev.get("incremental")
    if inc:
        return inc.get("files") or []
    return [p for c in (rev.get("coverage") or {}).get("chunks", []) for p in c.get("files", [])]


def replay(root, include_self=False):
    """Replay the stored reviews under `root` against each candidate rule. No model calls."""
    answers = _answers(root)
    r = {"reviews": 0, "cost": 0.0, "split": 0, "cost_review": 0.0, "cost_verify": 0.0, "raw": 0, "dropped": 0,
         "docs": {"reviews": 0, "cost": 0.0, "at_risk": collections.Counter()},
         "low_cheap": {"decided": 0, "lost": collections.Counter(),
                       "downgraded": collections.Counter(), "extra_kept": 0, "lost_fixed": [], "examples": [],
                       "sightings": 0, "sightings_lost": 0, "sightings_extra": 0},
         "repeat_full": {"reviews": 0, "cost": 0.0}}
    seen, decided, fixed = set(), {}, set()
    for p, rev in sorted(_reviews(root, include_self), key=lambda x: x[1].get("started", "")):
        r["reviews"] += 1
        r["cost"] += rev.get("cost_usd") or 0
        if "cost_review_usd" in rev:               # older reviews only stored the total
            r["split"] += 1
            r["cost_review"] += rev["cost_review_usd"] or 0
            r["cost_verify"] += rev.get("cost_verify_usd") or 0
        model_found = [(f, True) for f in rev.get("findings", []) if f.get("source") == "review"] + \
                      [(f, False) for f in rev.get("dropped", []) if f.get("source") == "review"]
        r["raw"] += len(model_found)
        r["dropped"] += sum(1 for f, kept in model_found if not kept)
        # a full review of a branch already reviewed on the same base: an amended commit, so not incremental
        key = (rev.get("repo"), rev.get("base"), (rev.get("inputs") or {}).get("draft"))
        if key in seen and not rev.get("incremental"):
            r["repeat_full"]["reviews"] += 1
            r["repeat_full"]["cost"] += rev.get("cost_usd") or 0
        seen.add(key)
        if change_kind(_files(rev)) == "docs":
            r["docs"]["reviews"] += 1
            r["docs"]["cost"] += rev.get("cost_usd") or 0
            for f, kept in model_found:
                if kept:
                    r["docs"]["at_risk"][f["severity"]] += 1
        lc = r["low_cheap"]
        for f, kept in model_found:
            trail = (f.get("verification") or {}).get("tiers") or []
            if len(trail) != 2:
                continue
            cheap = trail[0]
            # the reviewer's proposal is only stored for dropped findings (and new reviews); unknown counts as low,
            # which can only overstate what the rule loses
            proposed = f.get("proposed_severity") or (f["severity"] if not kept else "low")
            if cheap.get("severity") != "low" or proposed != "low":
                continue
            lc["sightings"] += 1                   # one strong-tier call avoided
            if kept and not cheap.get("keep"):
                outcome, sev_ = "lost", f["severity"]
                lc["sightings_lost"] += 1
            elif kept and SEV.index(f["severity"]) < SEV.index("low"):
                outcome, sev_ = "downgraded", f["severity"]
            elif not kept and cheap.get("keep"):
                outcome, sev_ = "extra_kept", None
                lc["sightings_extra"] += 1
            else:
                outcome, sev_ = "same", None
            # a finding carried through several rounds counts once, at its worst outcome
            k = (rev.get("repo"), f["title"])
            worst = decided.get(k)
            if worst is None or RANK[outcome] > RANK[worst[0]] or (
                    outcome == worst[0] and sev_ and SEV.index(sev_) < SEV.index(worst[1])):
                decided[k] = (outcome, sev_)
            if answers.get(f.get("id")) == "fixed":
                fixed.add(k)
    lc = r["low_cheap"]
    for (repo, title), (outcome, sev_) in decided.items():
        lc["decided"] += 1
        if outcome in ("lost", "downgraded"):
            lc[outcome][sev_] += 1
            lc["examples"].append((repo, sev_ if outcome == "lost" else sev_ + "→low", title))
            if (repo, title) in fixed:
                lc["lost_fixed"].append((repo, sev_, title))
        elif outcome == "extra_kept":
            lc["extra_kept"] += 1
    return r


RANK = {"same": 0, "extra_kept": 1, "downgraded": 2, "lost": 3}


def safe(lost, downgraded=None):
    """The switch-on bar: no important/critical finding lost, and no medium lost or downgraded."""
    bad = collections.Counter(lost) + collections.Counter(downgraded or {})
    return not any(bad[s] for s in ("critical", "important", "medium"))


def replay_report(r):
    n, ns = r["reviews"] or 1, r["split"] or 1
    raw = r["raw"] or 1
    lc, dc, rf = r["low_cheap"], r["docs"], r["repeat_full"]
    after_dropped = r["dropped"] - lc["sightings_extra"] + lc["sightings_lost"]
    sev = lambda c: ", ".join(f"{c[s]} {s}" for s in SEV if c[s]) or "none"
    lines = [
        f"Replayed {r['reviews']} stored reviews (no model calls).",
        f"Now: ${r['cost'] / n:.2f}/review (where split: review pass ${r['cost_review'] / ns:.2f}, verification "
        f"${r['cost_verify'] / ns:.2f}, over {r['split']} reviews); "
        f"{r['raw']} model findings, {r['dropped']} refuted by verification ({100 * r['dropped'] / raw:.0f}%).",
        "",
        f"Rule 1, docs/PR-text-only round → one cheap pass: {dc['reviews']} of {r['reviews']} reviews qualify "
        f"(${dc['cost']:.2f} of ${r['cost']:.2f}); kept findings in them, at risk: {sev(dc['at_risk'])}. "
        + ("No stored review qualifies, so the replay can neither clear nor reject it; it stays behind --route."
           if not dc["reviews"] else "Nothing important/critical/medium at risk." if safe(dc["at_risk"])
           else "NOT safe: stays off."),
        f"Rule 2, low findings settled on the cheap tier: {lc['decided']} unique findings ({lc['sightings']} strong-tier "
        f"calls) decided by the cheap tier instead of the strong one; lost: {sev(lc['lost'])}; downgraded to low: {sev(lc['downgraded'])}; "
        f"extra kept that the strong tier refuted: {lc['extra_kept']}. Refuted share would go "
        f"{100 * r['dropped'] / raw:.0f}% → {100 * after_dropped / raw:.0f}%. "
        + ("Passes the bar." if safe(lc["lost"], lc["downgraded"]) and not lc["lost_fixed"] else "Fails the bar: stays off."),
    ]
    for repo, s, t in lc["lost_fixed"]:
        lines.append(f"  lost and later fixed by the author: [{s}] {t} ({repo.replace('__', '/')})")
    for repo, s, t in lc["examples"][:12]:
        lines.append(f"  - [{s}] {t[:90]} ({repo.replace('__', '/')})")
    lines += ["",
              f"Repeat full reviews (an amended commit on a branch already reviewed on the same base, so not "
              f"incremental): {rf['reviews']} of {r['reviews']} reviews, ${rf['cost']:.2f} of ${r['cost']:.2f}."]
    return "\n".join(lines)
