"""`crucible model-replay`: which reviewer model finds the findings that held up, on our own upstream PRs?

The eval set's planted bugs can't say how a reviewer does on the changes we actually send upstream, so this replays
stored full review rounds (not incremental ones) whose code findings the author has since answered, once per
reviewer model, at the commit and base they were reviewed at. Answers are the labels: fixed or deferred = held up,
refuted = a false alarm. Each arm runs the whole pipeline as `review` would pick it for that reviewer (the verifier is
the next model in the preference list), so an arm is a configuration crucible would really run.

Findings get their ids from their titles, so a finding another model words differently has a different id. A replayed
finding matches a labelled one when it is on the same file and close to the same line, with some wording in common
(`match`); each labelled finding matches at most one. A replayed finding that matches nothing has no label: it is
counted, and listed for a person to judge, never scored. Labels exist only for findings the stored round's reviewer
(the first model) raised, so recall of held-up findings favours that arm by construction: another model's own real
findings show up as unlabelled, never as wins. Comparing how many false alarms each arm re-raises is fair; held-up
recall is a floor for the other arms, not a head-to-head. Only code findings are compared. A finding on the PR draft
can't be scored across rounds the same way (the draft's text isn't stored, only its hash); the draft is passed to
the replay when its current text still has the stored hash, so the reviewer sees the same prompt, and left out
otherwise.

Every arm runs with --no-exec (nothing from the checkout runs, on this machine), --offline, --full and --fresh, in a
throwaway CRUCIBLE_HOME that holds a copy of the project's learned rules and style, so stored reviews, the cache and
`stats` are never touched. Model calls: this costs money (--budget caps each arm's run)."""
import glob, os, re, shutil, subprocess, sys, tempfile

from . import anchoring, routing
from .util import HOME, MODELS, TEST_PATH_RX, Failed, git, norm_words, project_key, read_json

HELD = ("fixed", "deferred")
INCOMPLETE = "stored round's coverage incomplete"
# settings that would change an arm's pipeline away from the default for its reviewer: the verifier pick, cost
# routing (which can swap the reviewer on a docs-only round), the cheap tier, and cache/prompt switches
ARM_UNSET = ("CRUCIBLE_VERIFY_MODEL", "CRUCIBLE_ROUTE", "CRUCIBLE_ROUTE_DOCS_MODEL", "CRUCIBLE_VERIFY_CHEAP",
             "CRUCIBLE_CATALOG_DIGEST", "CRUCIBLE_CACHE_VERIFY", "CRUCIBLE_NO_TOOLS_CACHE")
DISPOSITIONS = HELD + ("refuted",)
LINE_NEAR, LINE_FAR, WORDS_MIN = 3, 15, 0.25
# the by-shape breakdown: production lines changed (outside tests and docs), upper bounds of each size bucket
SIZE_BUCKETS = ((50, "<=50"), (200, "51-200"), (None, ">200"))
TOO_FEW = 60                   # labelled findings a bucket needs before its rates are worth quoting


def _words(f):
    return set(w for w in norm_words(" ".join(str(f.get(k) or "") for k in ("title", "wrong_if"))) if len(w) > 2)


def similarity(a, b):
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def score(lab, got):
    """How well a replayed finding `got` matches a labelled one, or None when it can't be the same finding: another
    file, more than LINE_FAR lines apart, or (beyond LINE_NEAR lines) too little wording in common."""
    if (lab.get("file") or "") != (got.get("file") or ""):
        return None
    gap = abs((lab.get("line") or 0) - (got.get("line") or 0))
    sim = similarity(lab, got)
    if gap > LINE_FAR or (gap > LINE_NEAR and sim < WORDS_MIN):
        return None
    return sim - gap / (10 * LINE_FAR)


def match(labelled, produced):
    """Greedy one-to-one, best score first. Returns {labelled index: produced index}."""
    pairs = sorted(((s, i, j) for i, lab in enumerate(labelled) for j, got in enumerate(produced)
                    if (s := score(lab, got)) is not None), reverse=True)
    out, used = {}, set()
    for _, i, j in pairs:
        if i not in out and j not in used:
            out[i] = j
            used.add(j)
    return out


def _is_draft(f, draft):
    name = f.get("file") or ""
    return name == "PR_DRAFT.md" or os.path.isabs(name) or bool(draft and os.path.basename(draft) == os.path.basename(name))


def repo_answers(repo_dir):
    """Answers from every round of one repo, by finding id. A finding is usually answered on a later, incremental
    round (the one the author fixed it in), and an id is stable across rounds (file + title), so a full round's
    findings are labelled by what was answered anywhere in the repo. On a clash the later answer wins."""
    out = {}
    for p in sorted(glob.glob(os.path.join(repo_dir, "*", "answers.json")), key=os.path.getmtime):
        out.update({k: v for k, v in (read_json(p, {}) or {}).items() if isinstance(v, dict)})
    return out


def rounds(root, model, include_self=False, skipped=None):
    """Stored full rounds reviewed by `model` with at least one answered code finding, newest first. Rounds left out
    only because their stored coverage wasn't complete are counted in `skipped`."""
    out = []
    for p in glob.glob(os.path.join(root, "*", "*", "review.json")):
        d = os.path.dirname(p)
        repo = os.path.basename(os.path.dirname(d))
        if not include_self and repo.endswith("__crucible"):
            continue
        rev = read_json(p) or {}
        if rev.get("status") != "done" or rev.get("incremental") or rev.get("review_model") != model:
            continue
        ans = repo_answers(os.path.dirname(d))
        draft = (rev.get("inputs") or {}).get("draft")
        labelled = [dict(f, disposition=ans[f["id"]]["disposition"]) for f in rev.get("findings", [])
                    if f.get("source") == "review" and not _is_draft(f, draft)
                    and (ans.get(f.get("id")) or {}).get("disposition") in DISPOSITIONS]
        if labelled and not (rev.get("coverage") or {}).get("complete"):    # a replay would be incomplete too
            if skipped is not None:
                skipped[INCOMPLETE] = skipped.get(INCOMPLETE, 0) + 1
        elif labelled:
            out.append({"repo": repo, "sha": rev["sha"], "base": rev["base"], "started": rev.get("started") or "",
                        "inputs": rev.get("inputs") or {}, "labelled": labelled})
    return sorted(out, key=lambda r: r["started"], reverse=True)


def pick(cands, n):
    """Newest round of each project in turn, so one busy project doesn't fill the sample. Deterministic."""
    by = {}
    for r in cands:
        by.setdefault(r["repo"], []).append(r)
    order = sorted(by, key=lambda k: by[k][0]["started"], reverse=True)
    out = []
    while len(out) < n and any(by.values()):
        for k in order:
            if by[k] and len(out) < n:
                out.append(by[k].pop(0))
    return out


def score_arm(r, review):
    """One arm's result on one round: labelled findings re-found among the reviewer's raw findings (before
    verification) and among the kept ones, plus the kept code findings that match no label."""
    draft = r["inputs"].get("draft")
    kept = [f for f in review.get("findings", []) if f.get("source") == "review" and not _is_draft(f, draft)]
    raw = kept + [f for f in review.get("dropped", []) if f.get("source", "review") == "review" and not _is_draft(f, draft)]
    lab = r["labelled"]
    m_kept, m_raw = match(lab, kept), match(lab, raw)
    res = {"held": sum(f["disposition"] in HELD for f in lab), "refuted": sum(f["disposition"] == "refuted" for f in lab),
           "kept": len(kept), "raw": len(raw), "cost": review.get("cost_usd") or 0.0,
           "tokens": sum((review.get(k) or {}).get("total") or 0 for k in ("tokens_review", "tokens_verify")),
           "budget_hit": bool(review.get("budget_exhausted")),
           "found_held": 0, "kept_held": 0, "found_refuted": 0, "kept_refuted": 0,
           "unlabelled": [f for j, f in enumerate(kept) if j not in set(m_kept.values())],
           "missed_held": [f for i, f in enumerate(lab) if f["disposition"] in HELD and i not in m_raw]}
    for i, f in enumerate(lab):
        cls = "held" if f["disposition"] in HELD else "refuted"
        res["found_" + cls] += i in m_raw
        res["kept_" + cls] += i in m_kept
    return res


def _prepare(clone, r, tmp, label):
    label = re.sub(r"[^A-Za-z0-9._-]", "_", label)          # a model id like "a/b" stays one path component
    tree = anchoring.checkout(clone, r["sha"], os.path.join(tmp, f"{r['sha'][:10]}-{label}"))
    # the project key (and so the learned rules and style) comes from the remotes' slugs, upstream first; checkout()
    # may already have added the clone's origin (a fork) for a partial clone, so upstream is added on its own
    have = git(tree, "remote", check=False).split()
    for name in ("upstream", "origin"):
        url = git(clone, "remote", "get-url", name, check=False).strip()
        if url and name not in have:
            git(tree, "remote", "add", name, url)
    if project_key(tree) != r["repo"]:
        raise Failed(f"{r['repo']} {r['sha'][:10]}: the checkout resolves to {project_key(tree)}, not {r['repo']}")
    home = os.path.join(tmp, f"home-{r['sha'][:10]}-{label}")
    src = os.path.join(HOME, "projects", r["repo"])
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(home, "projects", r["repo"]))
    os.makedirs(home, exist_ok=True)
    return tree, home


def draft_still_matches(r):
    """The stored draft's path, when its submitted text still hashes to what the round judged."""
    from . import readiness
    import hashlib
    path, want = r["inputs"].get("draft"), r["inputs"].get("draft_sha")
    if not (path and want and os.path.exists(path)):
        return None
    text = readiness.submitted_text(open(path, errors="replace").read())
    return path if hashlib.sha256(text.encode()).hexdigest()[:16] == want else None


def run_arm(clone, r, model, tmp, budget=None, log=print):
    label = short(model)
    tree, home = _prepare(clone, r, tmp, label)
    cmd = [sys.executable, "-m", "crucible", "review", tree, "--base", r["base"], "--full", "--fresh", "--force",
           "--no-exec", "--offline"]
    draft = draft_still_matches(r)
    if draft:
        cmd += ["--draft", draft]
    if budget:
        cmd += ["--budget", str(budget)]
    env = dict(os.environ, CRUCIBLE_HOME=home, CRUCIBLE_CACHE=os.path.join(home, "cache"), CRUCIBLE_REVIEW_MODEL=model)
    for k in ARM_UNSET:                             # every arm runs crucible's defaults for its reviewer
        env.pop(k, None)
    # an empty PYTHONPATH entry would add the cwd to the child's import path
    env["PYTHONPATH"] = os.pathsep.join(p for p in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                    env.get("PYTHONPATH")) if p)
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    review = read_json(os.path.join(home, "reviews", r["repo"], r["sha"], "review.json"))
    if p.returncode not in (0, 1) or not review or review.get("status") != "done":
        raise Failed(f"{r['repo']} {r['sha'][:10]} {label}: review did not finish ({(p.stderr or p.stdout)[-300:]})")
    # a round whose review chunks failed (an unknown model id, a usage limit) is "done" with no findings: it would
    # score as a clean zero instead of being left out
    if not (review.get("coverage") or {}).get("complete"):
        raise Failed(f"{r['repo']} {r['sha'][:10]} {label}: review incomplete (a review chunk failed)")
    if review.get("review_model") != model:
        raise Failed(f"{r['repo']} {r['sha'][:10]} {label}: reviewed by {review.get('review_model')}, not {model}")
    review["_draft_passed"] = bool(draft)
    return review


def shape(clone, base, sha):
    """The change a round reviewed, by what routing would care about: its kind ("docs/PR text" when every changed file
    is docs, "tests only", "single-file" or "multi-file" by the production files changed, i.e. outside tests and docs)
    and its size bucket by production lines changed (added + deleted; binary files count 0; None with no production
    files). None when the diff can't
    be read, so an unreadable round is left out of the breakdown rather than counted as an empty change."""
    try:
        out = git(clone, "diff", "--numstat", "-z", "--no-renames", f"{base}..{sha}")
    except Failed:
        return None
    files = []
    for rec in out.split("\0"):
        parts = rec.split("\t", 2)
        if len(parts) == 3 and parts[2]:
            added, deleted, path = parts
            files.append((path, (int(added) if added.isdigit() else 0) + (int(deleted) if deleted.isdigit() else 0)))
    prod = [(p, n) for p, n in files if not routing.is_doc(p) and not TEST_PATH_RX.search(p)]
    lines = sum(n for _, n in prod)
    if not files:
        kind = "no files"
    elif routing.change_kind([p for p, _ in files]) == "docs":
        kind = "docs/PR text"
    elif not prod:
        kind = "tests only"
    else:
        kind = "single-file" if len(prod) == 1 else "multi-file"
    # a round with no production files has no production size: in "<=50" it would sit with small code changes
    size = next(label for top, label in SIZE_BUCKETS if top is None or lines <= top) if prod else None
    return {"kind": kind, "prod_files": len(prod), "prod_lines": lines, "size": size}


def short(model):
    return next((k for k, v in MODELS.items() if v == model), model)


def run(root, clones, models, n=5, budget=None, include_self=False, log=print):
    """Pairs: every arm on the same n rounds. A round where any arm fails is left out of all of them."""
    models = list(dict.fromkeys(models))      # an arm named twice would be run twice and counted twice
    incomplete = {}
    cands = rounds(root, models[0], include_self, incomplete)
    repos = anchoring.find_clones(clones)
    have = []
    for r in cands:
        c = next((c for c in repos if anchoring.has_commit(c, r["sha"]) and anchoring.has_commit(c, r["base"])), None)
        if c:
            have.append(dict(r, clone=c))
    sample = pick(have, n)
    skipped = {"no local clone has the commit and its base": len(cands) - len(have), "an arm failed": 0, **incomplete}
    tmp = tempfile.mkdtemp(prefix="crucible-modelreplay-")
    rows = []
    try:
        for r in sample:
            arms = {}
            try:
                for m in models:
                    log(f"  {r['repo']} {r['sha'][:10]}: {m}")
                    arms[m] = score_arm(r, run_arm(r["clone"], r, m, tmp, budget, log))
            except (Failed, subprocess.SubprocessError, OSError) as ex:
                log(f"    left out: {ex}")
                skipped["an arm failed"] += 1
                continue
            rows.append(dict(r, arms=arms, shape=shape(r["clone"], r["base"], r["sha"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows, skipped


def totals(rows, models):
    keys = ("held", "refuted", "found_held", "kept_held", "found_refuted", "kept_refuted", "kept", "raw", "cost", "tokens")
    t = {m: dict.fromkeys(keys, 0) for m in models}
    for r in rows:
        for m in models:
            a = r["arms"][m]
            for k in keys:
                t[m][k] += a[k]
            t[m]["unlabelled"] = t[m].get("unlabelled", 0) + len(a["unlabelled"])
    return t


def by_shape(rows, models):
    """Per arm, per bucket of change kind and of production size: held-up kept / labelled held, false alarms kept /
    labelled refuted, $, $ per held-up kept. Which change types a cheaper reviewer could take is a per-bucket question,
    and the buckets are small: one under TOO_FEW labelled findings is marked so nobody quotes its rate."""
    rows = [r for r in rows if r.get("shape")]
    if not rows:
        return []
    out = ["", f"By change shape (held kept/held, false alarms kept/refuted, $, $ per held kept; under {TOO_FEW} "
               "labelled findings = too few to quote):"]
    for dim, title in (("kind", "kind"), ("size", "production lines")):
        order = [lab for _, lab in SIZE_BUCKETS] if dim == "size" else sorted({r["shape"]["kind"] for r in rows})
        for b in order:
            sub = [r for r in rows if r["shape"][dim] == b]
            if not sub:
                continue
            t = totals(sub, models)
            labelled = t[models[0]]["held"] + t[models[0]]["refuted"]
            cells = []
            for m in models:
                s = t[m]
                per = f"${s['cost'] / s['kept_held']:.2f}" if s["kept_held"] else "n/a"
                cells.append(f"{short(m)} {s['kept_held']}/{s['held']}, {s['kept_refuted']}/{s['refuted']}, "
                             f"${s['cost']:.2f}, {per}")
            few = f" too few (n={labelled})" if labelled < TOO_FEW else f" n={labelled}"
            out.append(f"  {title} {b}: {len(sub)} round(s){few}: " + "; ".join(cells))
    return out


def report(rows, skipped, models):
    models = list(dict.fromkeys(models))
    t = totals(rows, models)
    out = [f"Reviewer replay: {len(rows)} stored full rounds, each re-reviewed by every arm at its commit and base "
           "(--no-exec --offline --full --fresh). Labels are the author's answers on the stored round: "
           "fixed/deferred = held up, refuted = false alarm. Code findings only.",
           f"Labels come only from what {short(models[0])} raised in the stored round, so held-up recall favours it; "
           "the other arms' own real findings are among the unlabelled ones below."]
    out += [f"  skipped {v}: {k}" for k, v in skipped.items() if v]
    for m in models:
        s = t[m]
        per = f"${s['cost'] / s['kept_held']:.2f}" if s["kept_held"] else "n/a (none kept)"
        out.append(f"- review {m}: held-up findings re-found {s['found_held']}/{s['held']} raw, kept {s['kept_held']}/{s['held']}"
                   f"; false alarms re-raised {s['found_refuted']}/{s['refuted']}, kept {s['kept_refuted']}/{s['refuted']}"
                   f"; kept code findings {s['kept']} ({s['unlabelled']} match no label); ${s['cost']:.2f}, "
                   f"{s['tokens']:,} tokens; $ per held-up finding kept {per}")
    out += by_shape(rows, models)
    out += ["", "Per round (held kept / false alarms kept / unlabelled kept / $):"]
    for r in rows:
        cells = "  ".join(f"{short(m)} {a['kept_held']}/{a['kept_refuted']}/{len(a['unlabelled'])}/${a['cost']:.2f}"
                          + (" (stopped by --budget)" if a.get("budget_hit") else "")
                          for m, a in r["arms"].items())
        sh = r.get("shape")
        where = f"; {sh['kind']}, {sh['prod_lines']} production lines" if sh else ""
        out.append(f"  {r['repo']} {r['sha'][:10]} (held {r['arms'][models[0]]['held']}, refuted "
                   f"{r['arms'][models[0]]['refuted']}{where}): {cells}")
    for m in models:
        miss = [(r, f) for r in rows for f in r["arms"][m]["missed_held"]]
        if miss:
            out += ["", f"Held-up findings {m} didn't raise at all:"]
            out += [f"  {r['repo']} {f['file']}:{f.get('line')} [{f['severity']}] {f['title'][:80]}" for r, f in miss]
    for m in models:
        un = [(r, f) for r in rows for f in r["arms"][m]["unlabelled"]]
        if un:
            out += ["", f"Kept by {m} with no label (judge by hand):"]
            out += [f"  {r['repo']} {f['file']}:{f.get('line')} [{f['severity']}] {f['title'][:80]}" for r, f in un]
    return "\n".join(out)
