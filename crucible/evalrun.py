"""`crucible eval`: run the full review on labelled fixture changes and score it.

Each case in eval/cases/<name>/ has base/ (the tree before), change/ (the tree after) and expected.json:
  {"kind": "bug"|"clean", "split": "build"|"holdout", "message": "<commit subject>", "file": "...", "lines": [...],
   "keywords": [...], "also": [{"file": "...", "lines": [...]}]}
`also` lists other places a correct finding may anchor (the callee that really blocks, say); keywords apply there too.
`split` defaults to "build". Build cases are the ones prompts and verification have been tuned against, so their
recall flatters the reviewer. Holdout cases come from real catches and are never used to justify a prompt change; the
summary reports their recall and false blocking separately, so a gain on build cases that doesn't carry over shows.
A bug counts as caught when a kept finding at a blocking severity (critical/important) hits it: in the labelled file,
AND either naming one of the labelled root-cause keywords or citing a labelled line (±1). Proximity alone is not
enough on tiny fixtures, where an unrelated finding ("no tests for mean()") can sit within a few lines. Clean cases should produce
no blocking findings at all. Every case runs in its own temporary CRUCIBLE_HOME, so nothing leaks between cases
or into the user's state."""
import concurrent.futures as cf, datetime as dt, glob, json, os, shutil, subprocess, sys, tempfile, time

EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")
BLOCKING = {"critical", "important"}
# built at run time so no secret-shaped literal is ever committed (push protection, scanners)
SUBST = {"__SECRET_AWS__": "AKIA" + "Q7XJ2ZVN4L6PR8TB"}


SPLITS = ("build", "holdout")


def case_split(exp):
    """only a missing key means build; "" or null is a mistake that must not quietly move a held-out case."""
    return exp.get("split", "build")


def load_cases(names=None, split=None):
    out = []
    for d in sorted(glob.glob(os.path.join(EVAL_DIR, "cases", "*"))):
        name = os.path.basename(d)
        if names and not any(n in name for n in names):
            continue
        exp = json.load(open(os.path.join(d, "expected.json")))
        if case_split(exp) not in SPLITS:
            raise SystemExit(f"eval case {name}: split must be one of {', '.join(SPLITS)}, not {exp['split']!r}")
        if split and case_split(exp) != split:
            continue
        out.append((name, d, exp))
    return out


JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def _copy_tree(src, dst):
    """Copy a fixture tree, skipping build output that a local test run may have left in it (pytest wrote a
    __pycache__/*.pyc into a fixture, and reading it as text crashed the case with a UnicodeDecodeError)."""
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in JUNK_DIRS]
        for fn in files:
            if fn.endswith((".pyc", ".pyo")):
                continue
            s = os.path.join(root, fn)
            rel = os.path.relpath(s, src)
            t = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(t), exist_ok=True)
            txt = open(s).read()
            for k, v in SUBST.items():
                txt = txt.replace(k, v)
            open(t, "w").write(txt)


def _git(repo, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="eval", GIT_AUTHOR_EMAIL="eval@example.invalid",
               GIT_COMMITTER_NAME="eval", GIT_COMMITTER_EMAIL="eval@example.invalid",
               GIT_AUTHOR_DATE="2026-01-01T00:00:00Z", GIT_COMMITTER_DATE="2026-01-01T00:00:00Z",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")   # the user's git config can't change the fixtures
    subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)


def build_repo(case_dir, exp, where):
    """base/ committed on main, change/ committed on branch `change`. Returns the repo path (named after the case)."""
    repo = os.path.join(where, os.path.basename(case_dir))
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "main")
    _copy_tree(os.path.join(case_dir, "base"), repo)
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "change")
    for p in _git_ls(repo):
        os.remove(os.path.join(repo, p))
    _copy_tree(os.path.join(case_dir, "change"), repo)
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", exp.get("message", "change"))
    return repo


def _git_ls(repo):
    r = subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True, text=True, check=True)
    return [l for l in r.stdout.split("\n") if l]


def hits(f, exp):
    places = [{"file": exp.get("file"), "lines": exp.get("lines", [])}] + list(exp.get("also") or [])
    text = (f.get("title", "") + " " + f.get("problem", "")).lower()
    kw = any(k.lower() in text for k in exp.get("keywords", []))
    for p in places:
        if f.get("file") != p.get("file"):
            continue
        if kw or any(abs(int(f.get("line") or -99) - l) <= 1 for l in p.get("lines", [])):
            return True
    return False


def score_case(rev, exp):
    if not rev or rev.get("status") != "done":
        return {"ok": False, "error": (rev or {}).get("reason", "no review"), "cost": (rev or {}).get("cost_usd", 0)}
    kept, dropped = rev.get("findings", []), rev.get("dropped", [])
    blocking = [f for f in kept if f["severity"] in BLOCKING]
    out = {"ok": True, "cost": rev.get("cost_usd", 0), "cost_review": rev.get("cost_review_usd", 0),
           "cost_verify": rev.get("cost_verify_usd", 0), "kept": len(kept), "dropped": len(dropped),
           "blocking": len(blocking)}
    if "nits" in rev:                  # a --nits run: the nit tier never blocks, so it is counted on its own
        out.update(nits=len(rev["nits"]), nits_dropped=len(rev.get("nits_dropped") or []),
                   cost_nits=rev.get("cost_nits_usd", 0), nit_hits=sum(1 for f in rev["nits"] if hits(f, exp)))
    if exp["kind"] == "bug":
        out["caught"] = any(hits(f, exp) for f in blocking)
        out["caught_any_severity"] = any(hits(f, exp) for f in kept)
        out["true_dropped"] = sum(1 for f in dropped if hits(f, exp))
        out["extra_blocking"] = sum(1 for f in blocking if not hits(f, exp))
    else:
        out["false_blocking"] = len(blocking)
    return out


def run_case(name, case_dir, exp, args, cache_dir):
    tmp = tempfile.mkdtemp(prefix=f"crucible-eval-{name}-")
    try:
        repo = build_repo(case_dir, exp, tmp)
        home = os.path.join(tmp, "home")
        env = dict(os.environ, CRUCIBLE_HOME=home)
        if cache_dir:
            env["CRUCIBLE_CACHE"] = cache_dir
            env["CRUCIBLE_CACHE_VERIFY"] = "0"   # share review passes only, so each run pays (and measures) its own verification
        if args.review_model:
            env["CRUCIBLE_REVIEW_MODEL"] = args.review_model
        if args.verify_model:
            env["CRUCIBLE_VERIFY_MODEL"] = args.verify_model
        if args.cheap_model:
            env["CRUCIBLE_VERIFY_CHEAP"] = args.cheap_model
        cmd = [sys.executable, "-m", "crucible", "review", repo, "--base", "main", "--offline", "--skip-checks",
               "--budget", str(args.budget)]
        if args.no_tiers:
            cmd.append("--no-tiers")
        if getattr(args, "nits", False):
            cmd.append("--nits")
        t0 = time.time()
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=os.path.dirname(EVAL_DIR), timeout=3600)
        secs = round(time.time() - t0, 1)
        revs = glob.glob(os.path.join(home, "reviews", "*", "*", "review.json"))
        rev = json.load(open(revs[0])) if revs else None
        s = score_case(rev, exp)
        if not rev:
            s["error"] = f"review exited {proc.returncode} without a review.json: {(proc.stderr or proc.stdout)[-300:]}"
        s.update(case=name, kind=exp["kind"], split=case_split(exp), secs=secs)
        if rev:
            s["findings"] = [{k: f.get(k) for k in ("severity", "file", "line", "title")} for f in rev.get("findings", [])]
            s["tiers"] = rev.get("verify_tiers")
        return s
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _split_summary(results):
    """recall and false blocking for one split; None where the split has no case of that kind."""
    bugs = [r for r in results if r["kind"] == "bug" and r.get("ok")]
    clean = [r for r in results if r["kind"] == "clean" and r.get("ok")]
    return {"bug_cases": len(bugs), "clean_cases": len(clean), "caught": sum(r["caught"] for r in bugs),
            "errors": sum(1 for r in results if not r.get("ok")),
            "recall": round(sum(r["caught"] for r in bugs) / len(bugs), 3) if bugs else None,
            "recall_any_severity": round(sum(r["caught_any_severity"] for r in bugs) / len(bugs), 3) if bugs else None,
            "false_blocking": sum(r["false_blocking"] for r in clean) if clean else None}


def summarize(results):
    bugs = [r for r in results if r["kind"] == "bug" and r.get("ok")]
    clean = [r for r in results if r["kind"] == "clean" and r.get("ok")]
    return {
        "cases": len(results), "errors": sum(1 for r in results if not r.get("ok")),
        "recall": round(sum(r["caught"] for r in bugs) / len(bugs), 3) if bugs else None,
        "recall_any_severity": round(sum(r["caught_any_severity"] for r in bugs) / len(bugs), 3) if bugs else None,
        "false_blocking": sum(r["false_blocking"] for r in clean),
        "clean_cases_with_blocking": sum(1 for r in clean if r["false_blocking"]),
        "true_dropped": sum(r["true_dropped"] for r in bugs),
        "extra_blocking_on_bug_cases": sum(r["extra_blocking"] for r in bugs),
        "cost_usd": round(sum(r.get("cost", 0) or 0 for r in results), 3),
        "cost_review_usd": round(sum(r.get("cost_review", 0) or 0 for r in results), 3),
        "cost_verify_usd": round(sum(r.get("cost_verify", 0) or 0 for r in results), 3),
        "secs": round(sum(r.get("secs", 0) for r in results), 1),
        **({"nits": sum(r.get("nits", 0) for r in results), "nits_on_clean": sum(r.get("nits", 0) for r in clean),
            "nits_dropped": sum(r.get("nits_dropped", 0) for r in results),
            "cost_nits_usd": round(sum(r.get("cost_nits", 0) or 0 for r in results), 3)}
           if any("nits" in r for r in results) else {}),
        "by_split": {sp: _split_summary([r for r in results if r.get("split", "build") == sp])
                     for sp in SPLITS if any(r.get("split", "build") == sp for r in results)},
    }


def _fmt_split(sp, s):
    rec = "n/a (no bug cases)" if s["recall"] is None else \
        f"{s['recall']} ({s['caught']}/{s['bug_cases']} bug cases)"
    fb = "n/a (no clean cases)" if s["false_blocking"] is None else f"{s['false_blocking']} on {s['clean_cases']} clean cases"
    err = f", {s['errors']} errored (not scored)" if s.get("errors") else ""
    return f"{sp}: recall {rec}, false blocking {fb}{err}"


def write_results(label, settings, summary, results, partial=False):
    """A partial run (--cases/--split) only appends its history row: its few cases must not replace the full run's
    table in RESULTS.md. The history table shows build and held-out recall in their own columns, so a partial row
    can't pass for a full one."""
    hist_p = os.path.join(EVAL_DIR, "history.jsonl")
    row = {"at": dt.datetime.now().isoformat(timespec="minutes"), "label": label, "settings": settings, **summary}
    with open(hist_p, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    if partial:
        return
    hist = [json.loads(l) for l in open(hist_p) if l.strip()]
    L = ["# crucible eval results", "",
         "Generated by `crucible eval`. Bug cases count as caught when a kept **blocking** finding (critical/important) "
         "is in the labelled file and names the labelled root cause or cites the labelled line (±1). Clean cases "
         "should have no blocking findings.", "",
         f"## Latest run: {row['label']} ({row['at']})", "",
         f"Settings: `{json.dumps(settings)}`", "",
         f"- **recall {summary['recall']}** (any severity: {summary['recall_any_severity']}) on "
         f"{sum(1 for r in results if r['kind'] == 'bug')} bug cases",
         *[f"  - {_fmt_split(sp, ss)}" for sp, ss in summary["by_split"].items()],
         f"- **false blocking findings on clean cases: {summary['false_blocking']}** "
         f"({summary['clean_cases_with_blocking']} of {sum(1 for r in results if r['kind'] == 'clean')} clean cases)",
         f"- true findings dropped by verification: {summary['true_dropped']} · extra blocking findings on bug cases: "
         f"{summary['extra_blocking_on_bug_cases']}",
         f"- cost ${summary['cost_usd']} (review passes ${summary['cost_review_usd']}, verification "
         f"${summary['cost_verify_usd']}) · {summary['secs']} s · errors: {summary['errors']}", "",
         "| case | kind | split | result | blocking | kept / dropped | cost |", "|---|---|---|---|---|---|---|"]
    for r in results:
        if not r.get("ok"):
            L.append(f"| {r['case']} | {r['kind']} | {r.get('split', 'build')} | ERROR: {r.get('error', '')[:200].replace('|', '/').replace(chr(10), ' ')} | | | ${r.get('cost', 0)} |")
            continue
        res = ("caught" if r["caught"] else "caught (non-blocking)" if r["caught_any_severity"] else "**missed**") \
            if r["kind"] == "bug" else ("clean" if not r["false_blocking"] else f"**{r['false_blocking']} false blocking**")
        L.append(f"| {r['case']} | {r['kind']} | {r.get('split', 'build')} | {res} | {r['blocking']} | {r['kept']} / {r['dropped']} | ${r['cost']} |")
    notes_p = os.path.join(EVAL_DIR, "NOTES.md")       # hand-written context that must survive regeneration
    if os.path.exists(notes_p):
        L += ["", open(notes_p).read().strip()]
    L += ["", "## History", "",
          "Compare verification cost across runs: with a shared cache, a later run's review passes are cache hits ($0).", "",
          "| when | label | cases | build recall | held-out recall | any-sev recall | false blocking | true dropped | review cost | "
          "verification cost | shared cache |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for h in reversed(hist):
        sp = h.get("by_split")
        if sp is None:      # rows from before splits: every case was a build case
            sp = {"build": {"recall": h["recall"], "caught": None, "bug_cases": None}}
        cols = []
        for k in SPLITS:
            s = sp.get(k) or {}
            cols.append("–" if s.get("recall") is None else
                        f"{s['recall']}" + (f" ({s['caught']}/{s['bug_cases']})" if s.get("bug_cases") else ""))
        st = h.get("settings") or {}
        scope = f"{h.get('cases', '?')}" + (f", {st['split']} only" if st.get("split") not in (None, "all") else "") \
            + (", subset" if st.get("subset") else "")
        L.append(f"| {h['at']} | {h['label']} | {scope} | {cols[0]} | {cols[1]} | {h['recall_any_severity']} | {h['false_blocking']} | "
                 f"{h['true_dropped']} | ${h.get('cost_review_usd', '?')} | ${h.get('cost_verify_usd', '?')} | "
                 f"{'yes' if (h.get('settings') or {}).get('shared_cache') else 'no'} |")
    open(os.path.join(EVAL_DIR, "RESULTS.md"), "w").write("\n".join(L) + "\n")
    json.dump(results, open(os.path.join(EVAL_DIR, "last-run.json"), "w"), indent=1)


def run_eval(args, log=print):
    if not os.path.isdir(os.path.join(EVAL_DIR, "cases")):
        raise SystemExit("crucible eval runs from a git clone of crucible (eval/cases is not part of the installed package)")
    cases = load_cases(args.cases, getattr(args, "split", None))
    if not cases:
        raise SystemExit("no eval cases matched")
    cache_dir = args.cache or None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    settings = {"review": args.review_model or "default", "verify": args.verify_model or "default",
                "cheap": "off" if args.no_tiers else (args.cheap_model or "default"), "budget": args.budget,
                **({"nits": True} if getattr(args, "nits", False) else {}),
                "cases": len(cases), "split": getattr(args, "split", None) or "all", "subset": bool(args.cases), "shared_cache": bool(cache_dir)}
    log(f"crucible eval: {len(cases)} case(s) · {settings}")
    results = []
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        by_name = {n: e for n, d, e in cases}
        futs = {ex.submit(run_case, n, d, e, args, cache_dir): n for n, d, e in cases}
        for fut in cf.as_completed(futs):
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001 - one broken case must not lose the run
                exp = by_name[futs[fut]]
                r = {"case": futs[fut], "kind": exp["kind"], "split": case_split(exp), "ok": False,
                     "error": f"{type(e).__name__}: {e}", "cost": 0}
            results.append(r)
            tag = (("caught" if r.get("caught") else "MISSED") if r.get("kind") == "bug"
                   else ("clean" if not r.get("false_blocking") else f"{r['false_blocking']} FALSE BLOCKING")) if r.get("ok") \
                else f"error: {r.get('error')}"
            log(f"  {r['case']:<28} {tag:<20} ${r.get('cost', 0)}")
    results.sort(key=lambda r: (r.get("kind") != "bug", r["case"]))
    summary = summarize(results)
    partial = bool(args.cases or getattr(args, "split", None))
    if not args.no_write:
        write_results(args.label or ("tiers-off" if args.no_tiers else "default"), settings, summary, results, partial)
        if partial:
            log("partial run: history row appended; RESULTS.md keeps the last full run (its history table updates on the next one)")
    log(f"recall {summary['recall']} (any severity {summary['recall_any_severity']}) · false blocking "
        f"{summary['false_blocking']} · true dropped {summary['true_dropped']} · ${summary['cost_usd']} · {summary['secs']} s")
    for sp, ss in summary["by_split"].items():
        log(f"  {_fmt_split(sp, ss)}")
    if "nits" in summary:
        log(f"  nits kept {summary['nits']} ({summary['nits_on_clean']} on clean cases) · dropped {summary['nits_dropped']} "
            f"· nit verification ${summary['cost_nits_usd']}")
    return summary
