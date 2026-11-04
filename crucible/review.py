"""The review pipeline: checks → scanners → chunked review → per-finding verification → verdict."""
import concurrent.futures as cf, datetime as dt, fcntl, hashlib, json, os, re, subprocess, textwrap
from . import checks as checks_mod, diff as diff_mod, readiness, style as style_mod
from .util import (BLOCKING, HOME, MODELS, PREFERENCE, SEV, TOOLS_READ, TOOLS_RUN, Budget, Failed, claude, default_base,
                   exclude_locally, git, is_dirty, norm_words, project_dir, project_key, read_json, review_dir,
                   stable_id, upstream_slug, write_json)

SEVERITY_DEFS = """Severity definitions (use them literally):
- critical: data loss or corruption, a security hole, or a crash/hang in normal use; or the change does not do what it claims.
- important: wrong behaviour in a realistic case, a backward-compatibility break of public API or wire/file format,
  a missing test for the core behaviour change, or a clear violation of a written project rule that would get the PR rejected.
- medium: an edge case that is real but uncommon, a meaningful perf regression, missing docs/types for a changed API.
- low: minor improvements a maintainer might mention. Never style/naming unless a project rule requires it."""

FINDINGS_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "findings": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
        "severity": {"type": "string", "enum": SEV}, "file": {"type": "string"}, "line": {"type": "integer"},
        "title": {"type": "string"}, "problem": {"type": "string"},
        "caused_by_this_change": {"type": "boolean"}, "reachable_in_real_use": {"type": "boolean"},
        "wrong_if": {"type": "string"}, "fix": {"type": "string"}},
        "required": ["severity", "file", "line", "title", "problem", "caused_by_this_change",
                     "reachable_in_real_use", "wrong_if", "fix"]}}},
    "required": ["summary", "findings"]}

VERIFY_SCHEMA = {"type": "object", "properties": {
    "keep": {"type": "boolean"}, "severity": {"type": "string", "enum": SEV},
    "method": {"type": "string", "enum": ["executed", "read"]},
    "actions": {"type": "string", "description": "exactly what you read or ran (files, commands)"},
    "evidence": {"type": "string"},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"],
                   "description": "high only if you checked the falsification test directly and the result is unambiguous"}},
    "required": ["keep", "severity", "method", "actions", "evidence", "confidence"]}


# ---------- models ----------
def author_models(repo, base):
    trailers = git(repo, "log", "--format=%(trailers:key=Co-Authored-By,valueonly)", f"{base}..HEAD", check=False)
    found = set()
    for fam, mid in MODELS.items():
        if re.search(fr"\b{fam}\b", trailers, re.I):
            found.add(mid)
    return found


def choose_models(repo, base, author=None):
    authors = set([author] if author else []) | author_models(repo, base)
    review = os.environ.get("CRUCIBLE_REVIEW_MODEL") or next((m for m in PREFERENCE if m not in authors), PREFERENCE[0])
    verify = os.environ.get("CRUCIBLE_VERIFY_MODEL") or next((m for m in PREFERENCE if m != review), PREFERENCE[0])
    return review, verify, sorted(authors)


# ---------- project knowledge ----------
def project_rules_text(repo, project):
    parts = []
    for name in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md", "AGENTS.md", "CLAUDE.md"):
        p = os.path.join(repo, name)
        if os.path.exists(p):
            parts.append(f"--- {name} (excerpt) ---\n" + open(p, errors="replace").read()[:5000])
    learned = os.path.join(project_dir(project), "rules.md")
    if os.path.exists(learned):
        parts.append("--- maintainer preferences learned from merged PR reviews ---\n" + open(learned).read()[:6000])
    return "\n".join(parts) or "(no contribution guide found)"


def style_text(project):
    p = os.path.join(project_dir(project), "STYLE.md")
    return open(p).read()[:5000] if os.path.exists(p) else "(no STYLE.md yet; run `crucible learn`)"


def memory_text(project, limit=40):
    p = os.path.join(project_dir(project), "memory.md")
    if not os.path.exists(p):
        return "(none yet)"
    lines = [l for l in open(p).read().split("\n") if l.startswith("- ")]
    return "\n".join(lines[-limit:]) or "(none yet)"


# ---------- helpers ----------
def cache_dir():
    """Review and verification results, keyed by everything they depend on. CRUCIBLE_CACHE can point several homes
    (e.g. eval runs) at one shared cache."""
    return os.environ.get("CRUCIBLE_CACHE") or os.path.join(HOME, "cache")


def cache_get(key):
    return read_json(os.path.join(cache_dir(), key + ".json"))


def cache_put(key, val):
    os.makedirs(cache_dir(), exist_ok=True)
    write_json(os.path.join(cache_dir(), key + ".json"), val)


def region(repo, sha, path, line, pad=40):
    try:
        txt = git(repo, "show", f"{sha}:{path}")
    except Failed:
        return "(file not present at this commit)"
    lines = txt.split("\n")
    a, b = max(1, line - pad), min(len(lines), line + pad)
    return "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(a, b + 1))


def similar(a, b):
    if a["file"] != b["file"]:
        return False
    wa, wb = set(norm_words(a["title"])), set(norm_words(b["title"]))
    jac = len(wa & wb) / max(1, len(wa | wb))
    return jac >= 0.6 or (abs(a["line"] - b["line"]) <= 2 and jac >= 0.3)


def similar_loose(a, b):
    wa, wb = set(norm_words(a)), set(norm_words(b))
    return len(wa & wb) / max(1, len(wa | wb)) >= 0.25


def dedupe(findings):
    out = []
    for f in sorted(findings, key=lambda f: (f.get("source") != "review", SEV.index(f["severity"]))):
        dup = next((g for g in out if similar(f, g)), None)
        if dup:
            dup.setdefault("also", []).append(f["title"])
            if SEV.index(f["severity"]) < SEV.index(dup["severity"]):
                dup["severity"] = f["severity"]
        else:
            out.append(f)
    return out


def apply_honesty(f):
    if not f.get("caused_by_this_change", True) or not f.get("reachable_in_real_use", True):
        if f["severity"] in BLOCKING or f["severity"] == "medium":
            f["capped_from"] = f["severity"]
        f["severity"] = "low"
        f["non_blocking"] = "not caused by this change" if not f.get("caused_by_this_change", True) else "not reachable in real use"
    return f


def assign_ids(findings):
    seen = {}
    for f in findings:
        base = stable_id(f["file"], f["title"])
        seen[base] = seen.get(base, 0) + 1
        f["id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return findings


# ---------- pipeline ----------
def review_prompt(project, sha, base, ch, rules, mem, facts, log, all_files, house="", draft=""):
    return textwrap.dedent(f"""\
        You are a strict senior maintainer of {project.replace('__', '/')} reviewing an outside contributor's change
        BEFORE it is submitted upstream. The checkout is at the change's HEAD ({sha[:10]}); the base is {base[:10]}.

        How to review each hunk: read the WHOLE enclosing function/class in the current file, grep for its callers,
        open the matching test file, and check the public types/exports it affects. Judge the change the way this
        project's maintainers do (rules below). Report only real problems: correctness, regressions, missing or wrong
        tests, API / wire-format / backward-compat breaks, perf traps, security, and violations of written project rules.
        Give at most 10 findings, ranked; merge findings that share a root cause. An empty list is a good answer.
        Every finding needs a concrete file and line in the NEW file, and a "wrong_if": the specific observation
        that would prove it false. Set caused_by_this_change / reachable_in_real_use honestly.

        {SEVERITY_DEFS}

        House style. This PR must read like a long-time regular of THIS project wrote it. As medium/low findings
        (never blocking unless a project rule requires it), flag: comments that narrate the obvious or are denser
        than the file's own style; MISSING comments where logic is non-obvious (invariants, ordering, GPU/netcode or
        concurrency subtleties, magic numbers); naming inconsistent with nearby code; and in the PR description:
        missing reviewer call-outs (risky lines or trade-offs, before/after numbers, how it was tested), generated-
        sounding prose, or length far from the project norm. Use file "PR_DRAFT.md" for description findings.
        {house}

        PR description draft, as it will be submitted (the author's private notes in PR_DRAFT.md are excluded and
        are not part of the PR, so don't count them toward length or style):
        {draft[:5000] or '(none)'}

        Facts from running the project's own checks (treat as true):
        {facts}

        Project rules:
        {rules}

        Repeat mistakes to watch for in this project:
        {mem}

        Commits in this change:
        {log}

        All files in the change: {', '.join(all_files)}
        This pass covers: {', '.join(ch['files'])}

        Diff for this pass:
        {ch['text']}
        """)


def verify_prompt(f, code):
    return textwrap.dedent(f"""\
        You are verifying ONE claim about a code change in this checkout. Try hard to DISPROVE it.
        Claim: {f['title']} (at {f['file']}:{f['line']}, proposed severity {f['severity']})
        Falsification test: {f['wrong_if']}

        Code around the cited line at HEAD:
        {code}

        Do the falsification test for real: read the cited code and its callers/tests, and where a concrete input
        can show it, write a tiny throwaway script or run the relevant existing test (node / npx vitest|jest|mocha /
        npm test / pytest). Do not modify tracked files. Keep the claim only if it survives AND is caused by this change
        AND is reachable in real use. You may change the severity. Report method=executed only if you actually ran
        something that demonstrated the result; list exactly what you read or ran in `actions`.
        """)


# ---------- stability, tiers, incremental ----------
def facts_key(chk):
    """The check results as the review cache sees them: commands and outcomes, not their (timing-dependent) output."""
    return ";".join(f"{r.get('cmd')}={r.get('status')}/{r.get('on_base', '')}" for r in chk.get("results", []))


def verify_tiers(strong, no_tiers=False):
    """[cheap, strong] or [strong]. CRUCIBLE_VERIFY_CHEAP picks the cheap tier ("none" turns tiering off)."""
    cheap = os.environ.get("CRUCIBLE_VERIFY_CHEAP", MODELS["haiku"])
    if no_tiers or not cheap or cheap.lower() == "none" or cheap == strong:
        return [strong]
    return [cheap, strong]


def needs_escalation(v):
    """After the cheap tier: escalate when the claim survived at a blocking severity, or the verifier wasn't sure.
    A confident drop or a confident keep at medium/low is final."""
    if v.get("confidence") != "high":
        return True
    return bool(v["keep"]) and v["severity"] in BLOCKING


def verify_tiered(f, code, repo, budget, tiers, fresh=False):
    """-> (verdict, trail). trail lists each tier's model, keep, severity and confidence."""
    trail, v = [], None
    prompt = verify_prompt(f, code)
    for i, model in enumerate(tiers):
        key = "v-" + hashlib.sha256((model + prompt).encode()).hexdigest()[:32]
        use_cache = not fresh and os.environ.get("CRUCIBLE_CACHE_VERIFY", "1") != "0"
        hit = cache_get(key) if use_cache else None
        if hit:
            v = hit
        else:
            v, _ = claude(prompt, model, VERIFY_SCHEMA, repo, budget, tools=TOOLS_RUN, effort="high")
            cache_put(key, v)
        trail.append({"model": model, "keep": v["keep"], "severity": v["severity"], "confidence": v.get("confidence"),
                      "cached": bool(hit)})
        if i < len(tiers) - 1 and not needs_escalation(v):
            break
    return v, trail


def previous_review(repo, project, sha, base):
    """The newest complete review of an ancestor commit on this branch with the same merge-base, or (None, None)."""
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    hist = (read_json(os.path.join(project_dir(project), "branches.json"), {}) or {}).get(branch, [])
    for prev in reversed(hist):
        if prev == sha:
            continue
        rev = read_json(os.path.join(HOME, "reviews", project, prev, "review.json"))
        if not rev or rev.get("status") != "done" or rev.get("base") != base or not rev.get("coverage", {}).get("complete"):
            continue
        if rev.get("budget_exhausted"):
            continue
        if subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", prev, sha]).returncode != 0:
            continue
        return prev, rev
    return None, None


def split_prev(findings, ranges, hunks, prev_sha):
    """Split a previous review's model findings into (carried, touched). A finding is carried, with its line mapped
    forward, when its cited region wasn't touched since prev_sha; otherwise it must be verified again.
    Scanner and style findings are recomputed every time, so they are neither carried nor re-verified."""
    carried, touched = [], []
    for f in findings:
        if f.get("source") != "review":
            continue
        rs = ranges.get(f["file"], [])
        if rs and diff_mod.region_touched(rs, f["line"]):
            touched.append(dict(f, reverified_from=prev_sha[:10]))
            continue
        moved = diff_mod.map_line(hunks.get(f["file"], []), f["line"]) if f["file"] in hunks else f["line"]
        if moved is None:
            touched.append(dict(f, reverified_from=prev_sha[:10]))
        else:
            carried.append(dict(f, line=moved, carried_from=prev_sha[:10]))
    return carried, touched


def run_review(repo, base_ref=None, force=False, budget_usd=None, author=None, draft=None, base_checks=False,
               offline=False, skip_checks=False, log=print, full=False, fresh=False, no_tiers=False):
    """full: ignore the previous review of this branch (no incremental re-review).
    fresh: bypass the review/verification cache. no_tiers: verify with the strong model only."""
    repo = os.path.abspath(repo)
    project = project_key(repo)
    if is_dirty(repo):
        raise Failed("working tree has uncommitted changes to tracked files; commit or stash them so the verdict matches HEAD")
    exclude_locally(repo)
    sha = git(repo, "rev-parse", "HEAD")
    base_ref = base_ref or default_base(repo)
    base = git(repo, "merge-base", base_ref, "HEAD")
    log(f"crucible: {project.replace('__', '/')} HEAD {sha[:10]} vs {base_ref} (merge-base {base[:10]})")
    d = review_dir(project, sha)
    lock = open(os.path.join(d, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise Failed("a review of this commit is already running")
    if os.path.exists(os.path.join(d, "review.json")) and not force:
        log("already reviewed this commit (use --force to redo)")
        return d
    started = dt.datetime.now().isoformat(timespec="seconds")
    budget = Budget(budget_usd)
    record = {"repo": project, "sha": sha, "base": base, "base_ref": base_ref, "started": started, "status": "running"}
    try:
        diff_text = git(repo, "diff", "--unified=5", "--no-color", f"{base}..HEAD")
        if not diff_text:
            raise Failed("empty diff against base")
        files = diff_mod.parse(diff_text)
        review_model, verify_model, authors = choose_models(repo, base, author)
        record.update(review_model=review_model, verify_model=verify_model, author_models=authors)
        log(f"  models: review {review_model}, verify {verify_model} (author: {authors or 'unknown'})")

        chk = {"results": [], "note": "skipped by --skip-checks"} if skip_checks else \
            checks_mod.run_all(repo, project, base, on_base=base_checks, log=log, paths=[f["path"] for f in files])
        record["checks"] = chk
        ready = readiness.evaluate(repo, project, base, files, draft=draft, offline=offline)
        record["readiness"] = ready
        draft_path, draft_full = readiness.find_draft(repo, draft)
        draft_text = readiness.submitted_text(draft_full)
        cut = readiness.split_draft(draft_full)["notes_line"]
        if cut:
            log(f"  draft: author notes from {os.path.basename(draft_path)}:{cut} on are not judged as the PR body")
        style_json = read_json(os.path.join(project_dir(project), "style.json"), {}) or {}
        house_findings = style_mod.check(repo, base, files, draft_path, draft_text, style_json)

        scanner = diff_mod.scan(files)
        rules, mem, facts = project_rules_text(repo, project), memory_text(project), checks_mod.facts(chk)
        clog = git(repo, "log", "--format=%h %s", f"{base}..HEAD")
        all_files = [f["path"] for f in files]
        code_files = [f["path"] for f in files if not f["binary"]]
        house = style_text(project)

        # incremental re-review: only what changed since the last complete review of this branch
        prev_sha, prev_rev = (None, None) if full else previous_review(repo, project, sha, base)
        carried, carried_dropped, reverify = [], [], []
        if prev_sha:
            delta = git(repo, "diff", "--unified=5", "--no-color", f"{prev_sha}..HEAD")
            dfiles = [f for f in diff_mod.parse(delta) if f["path"] in set(code_files)] if delta else []
            d0 = git(repo, "diff", "-U0", "--no-color", f"{prev_sha}..HEAD") if delta else ""
            ranges, hunks = diff_mod.changed_old_ranges(d0), diff_mod.hunks_old_new(d0)
            carried, reverify = split_prev(prev_rev.get("findings", []), ranges, hunks, prev_sha)
            carried_dropped, _ = split_prev(prev_rev.get("dropped", []), ranges, hunks, prev_sha)
            chunks, uncovered = diff_mod.chunk(dfiles)
            log(f"  incremental: since {prev_sha[:10]} · {len(dfiles)} changed file(s) to review · "
                f"{len(carried)} finding(s) carried · {len(reverify)} to re-verify (use --full for a full review)")
            record["incremental"] = {"from": prev_sha, "files": [f["path"] for f in dfiles], "carried": len(carried),
                                     "reverified": len(reverify)}
        else:
            chunks, uncovered = diff_mod.chunk(files)
        cands, chunk_status, summaries = list(scanner) + house_findings, [], []
        if prev_sha and prev_rev.get("summary"):
            summaries.append(prev_rev["summary"][:1500])
        fkey, review_cost = facts_key(chk), 0.0
        for i, ch in enumerate(chunks, 1):
            prompt = review_prompt(project, sha, base, ch, rules, mem, facts, clog, all_files, house,
                                   draft_text if i == 1 else "(reviewed in pass 1)")
            # keyed on the prompt with check output reduced to outcomes: a template change invalidates the cache, but
            # volatile output (timings) doesn't, so --force on the same commit is stable
            key_prompt = review_prompt(project, sha, base, ch, rules, mem, fkey, clog, all_files, house,
                                       draft_text if i == 1 else "(reviewed in pass 1)")
            key = hashlib.sha256((review_model + "\0" + key_prompt).encode()).hexdigest()[:32]
            hit = None if fresh else cache_get(key)
            if hit:
                out, cost = hit, 0
            else:
                log(f"  review pass {i}/{len(chunks)}: {', '.join(ch['files'])[:90]}")
                try:
                    out, cost = claude(prompt, review_model, FINDINGS_SCHEMA, repo, budget)
                    review_cost += cost or 0
                    cache_put(key, out)
                except Failed as e:
                    chunk_status.append({"files": ch["files"], "status": "failed", "reason": str(e)})
                    continue
            chunk_status.append({"files": ch["files"], "status": "reviewed", "cached": bool(hit)})
            summaries.append(out["summary"])
            for f in out["findings"][:10]:
                cands.append(dict(f, source="review"))
        reviewed = {p for c in chunk_status if c["status"] == "reviewed" for p in c["files"]}
        if prev_sha:                                   # files untouched since the previous complete review stay covered
            reviewed |= set(code_files) - set(record["incremental"]["files"])
        missing = sorted((set(code_files) - reviewed) | set(uncovered))
        record["coverage"] = {"files": len(code_files), "reviewed": len(set(code_files) & reviewed) - len(set(uncovered) & reviewed),
                              "missing": missing, "complete": not missing, "chunks": chunk_status}

        new = assign_ids(dedupe([apply_honesty(f) for f in cands]))
        taken = {f["id"] for f in carried + reverify}
        new = [f for f in new if not any(similar(f, c) for c in carried + reverify)]   # earlier findings win over re-reports
        for f in new:
            if f["id"] in taken:
                f["id"] += "-n"
        to_verify = [f for f in new if f["source"] == "review"] + reverify
        kept, dropped = [f for f in new if f["source"] in ("scanner", "style")] + carried, list(carried_dropped)
        tiers = verify_tiers(verify_model, no_tiers)
        record["verify_tiers"] = tiers

        def verify(f):
            try:
                return (f,) + verify_tiered(f, region(repo, sha, f["file"], f["line"]), repo, budget, tiers, fresh) + (None,)
            except Failed as e:
                return f, None, [], str(e)
        if to_verify:
            log(f"  verifying {len(to_verify)} finding(s), one per call" + (f" (tiers: {' → '.join(tiers)})" if len(tiers) > 1 else ""))
            with cf.ThreadPoolExecutor(max_workers=4) as ex:
                for f, v, trail, err in ex.map(verify, to_verify):
                    if v is None:                      # fail closed: keep, marked unverified
                        f["verification"] = {"status": "unverified", "reason": err}
                        kept.append(f)
                    elif v["keep"]:
                        f["verification"] = {"status": "verified", "method": v["method"], "actions": v["actions"],
                                             "evidence": v["evidence"], "confidence": v.get("confidence"), "tiers": trail}
                        f["severity"] = v["severity"]
                        kept.append(apply_honesty(f))
                    else:
                        f["verification"] = {"status": "dropped", "method": v["method"], "actions": v["actions"],
                                             "evidence": v["evidence"], "confidence": v.get("confidence"), "tiers": trail}
                        dropped.append(f)
        # a carried finding can be fixed by a change elsewhere (a test added in another file): re-check it cheaply
        if carried and len(tiers) > 1:
            def recheck(f):
                try:
                    v, trail = verify_tiered(f, region(repo, sha, f["file"], f["line"]), repo, budget, tiers[:1], fresh)
                    return f, v
                except Failed:
                    return f, None
            with cf.ThreadPoolExecutor(max_workers=4) as ex:
                for f, v in ex.map(recheck, list(carried)):
                    if v and not v["keep"] and v.get("confidence") == "high":
                        kept.remove(f)
                        f["verification"] = {"status": "dropped", "method": v["method"], "actions": v["actions"],
                                             "evidence": "re-checked after a later commit: " + v["evidence"],
                                             "confidence": "high", "tiers": [{"model": tiers[0]}]}
                        dropped.append(f)
                    elif v:
                        f["rechecked"] = tiers[0]
        kept.sort(key=lambda f: (SEV.index(f["severity"]), (f.get("verification") or {}).get("method") != "executed"))
        record.update(status="done", summary=" ".join(summaries)[:3000], findings=kept, dropped=dropped,
                      cost_usd=round(budget.spent, 4), cost_review_usd=round(review_cost, 4),
                      cost_verify_usd=round(budget.spent - review_cost, 4), finished=dt.datetime.now().isoformat(timespec="seconds"),
                      budget_exhausted=budget.exhausted())
        carry_forward(repo, project, sha, record)
    except Failed as e:
        record.update(status="failed", reason=str(e), cost_usd=round(budget.spent, 4))
    except Exception as e:  # noqa: BLE001 - never leave a half-written review
        record.update(status="failed", reason=f"{type(e).__name__}: {e}", cost_usd=round(budget.spent, 4))
    write_json(os.path.join(d, "review.json"), record)
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    idx_p = os.path.join(project_dir(project), "branches.json")
    idx = read_json(idx_p, {}) or {}
    hist = idx.setdefault(branch, [])
    if sha not in hist:
        hist.append(sha)
    write_json(idx_p, idx)
    return d


def carry_forward(repo, project, sha, record):
    """Carry answers from the previous reviewed commit of this branch when the finding is the same and its code region
    was not touched since then."""
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    hist = (read_json(os.path.join(project_dir(project), "branches.json"), {}) or {}).get(branch, [])
    prev = next((s for s in reversed(hist) if s != sha), None)
    if not prev:
        return
    prev_d = os.path.join(HOME, "reviews", project, prev)
    prev_rev, prev_ans = read_json(os.path.join(prev_d, "review.json")), read_json(os.path.join(prev_d, "answers.json"), {})
    if not prev_rev or not prev_ans:
        return
    try:
        dtext = git(repo, "diff", "-U0", "--no-color", f"{prev}..{sha}")
    except Failed:
        return
    ranges, hunks = diff_mod.changed_old_ranges(dtext), diff_mod.hunks_old_new(dtext)
    answered = [f for f in prev_rev.get("findings", []) if f["id"] in prev_ans]
    carried, used = {}, set()
    for f in record["findings"]:
        for old in answered:
            if old["id"] in used or old["file"] != f["file"]:
                continue
            if diff_mod.region_touched(ranges.get(old["file"], []), old["line"]):
                continue                           # the cited code changed: it must be re-answered
            moved = diff_mod.map_line(hunks.get(old["file"], []), old["line"])
            same = old["id"] == f["id"] or (moved is not None and abs(moved - f["line"]) <= 3 and similar_loose(f["title"], old["title"]))
            if same:
                carried[f["id"]] = dict(prev_ans[old["id"]], carried_from=prev[:10], carried_finding=old["id"])
                used.add(old["id"])
                break
    if carried:
        d = review_dir(project, sha)
        ans = read_json(os.path.join(d, "answers.json"), {}) or {}
        for k, v in carried.items():
            ans.setdefault(k, v)
        write_json(os.path.join(d, "answers.json"), ans)
        record["carried_answers"] = sorted(carried)


# ---------- verdict / report ----------
def load(repo):
    repo = os.path.abspath(repo)
    project, sha = project_key(repo), git(repo, "rev-parse", "HEAD")
    d = os.path.join(HOME, "reviews", project, sha)
    rev = read_json(os.path.join(d, "review.json"))
    ans = read_json(os.path.join(d, "answers.json"), {}) or {}
    if rev and rev.get("status") == "done":
        ids = {f["id"] for f in rev["findings"]}
        stale = [k for k in ans if k not in ids]
        if stale:                                  # answers to findings that no longer exist are dropped
            for k in stale:
                ans.pop(k)
            write_json(os.path.join(d, "answers.json"), ans)
    return project, sha, d, rev, ans


def verdict(rev, ans):
    if not rev or rev.get("status") != "done":
        return "FAILED" if rev else "NO_REVIEW", [], []
    blocking = [f for f in rev["findings"] if f["severity"] in BLOCKING and ans.get(f["id"], {}).get("disposition") not in ("fixed", "refuted")]
    unanswered = [f for f in rev["findings"] if f["id"] not in ans]
    complete = rev["coverage"]["complete"] and not rev.get("budget_exhausted")
    failing = [c for c in rev["checks"].get("results", []) if c["status"] in ("fail", "timeout") and c.get("on_base") != "fail"]
    ok = not blocking and not unanswered and complete and not failing
    return ("GREEN" if ok else "NOT_GREEN"), blocking, unanswered


def ready_after_waivers(ready, waivers):
    return not any(i["status"] == "fail" and i["item"] not in waivers for i in ready["items"])


def waivers_path(project):
    return os.path.join(project_dir(project), "waivers.json")


def load_waivers(project, branch):
    return (read_json(waivers_path(project), {}) or {}).get(branch, {})


def report(rev, ans, waivers=None):
    """waivers: {readiness item name: reason} for this branch. A waived failing item no longer blocks readiness."""
    waivers = waivers or {}
    v, blocking, unanswered = verdict(rev, ans)
    proj = rev["repo"].replace("__", "/")
    if rev.get("status") != "done":
        return f"# crucible · {proj} @ {rev['sha'][:10]}\n\n**Review FAILED:** {rev.get('reason')}\n"
    ready = rev["readiness"]
    cov = rev["coverage"]
    L = [f"# crucible · {proj} @ {rev['sha'][:10]}", "",
         f"**Verdict: {v}** · **Ready to submit: {'yes' if v == 'GREEN' and ready_after_waivers(ready, waivers) else 'no'}**", "",
         f"- {len(rev['findings'])} findings kept · {len(rev['dropped'])} dropped by verification · "
         f"{len(blocking)} blocking open · {len(unanswered)} unanswered",
         f"- coverage: {cov['reviewed']}/{cov['files']} files" + (f" · MISSING {cov['missing']}" if cov["missing"] else ""),
         f"- models: review `{rev['review_model']}`, verify `{' → '.join(rev.get('verify_tiers') or [rev['verify_model']])}`"
         f" · author {rev.get('author_models') or 'unknown'}",
         f"- base `{rev['base_ref']}` (merge-base {rev['base'][:10]}) · cost ${rev['cost_usd']}"
         + (" · BUDGET EXHAUSTED" if rev.get("budget_exhausted") else ""),
         *([f"- incremental since `{rev['incremental']['from'][:10]}`: {len(rev['incremental']['files'])} file(s) re-reviewed, "
            f"{rev['incremental']['carried']} finding(s) carried, {rev['incremental']['reverified']} re-verified"]
           if rev.get("incremental") else []), "",
         "## Project checks", ""]
    res = rev["checks"].get("results", [])
    L += [f"- {'✅' if c['status'] == 'pass' else '⏭️' if c['status'] == 'skipped' else '❌'} `{c['cmd']}`: {c['status']}"
          + (f" (on base: {c['on_base']})" if c.get("on_base") else "") for c in res] or [f"- {rev['checks'].get('note', 'none')}"]
    L += ["", "## Readiness", ""]
    icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "na": "·"}
    L += [f"- ⏭️ {i['item']}: waived ({waivers[i['item']]})" if i["status"] == "fail" and i["item"] in waivers
          else f"- {icon[i['status']]} {i['item']}: {i['evidence']}" for i in ready["items"]]
    L += ["", "## Summary", "", rev.get("summary", ""), "", "## Findings", ""]
    if not rev["findings"]:
        L.append("None. 🎉")
    for f in rev["findings"]:
        a = ans.get(f["id"])
        tag = f"**{a['disposition']}**: {a['note']}" + (f" (carried from {a['carried_from']})" if a.get("carried_from") else "") if a else "*unanswered*"
        vf = f.get("verification") or {}
        L += [f"### {f['id']} · {f['severity']} · `{f['file']}:{f['line']}`", f"**{f['title']}** → {tag}", "", f["problem"], "",
              f"- wrong if: {f['wrong_if']}", f"- fix: {f['fix']}"]
        if f.get("non_blocking"):
            L.append(f"- capped to low: {f['non_blocking']} (was {f.get('capped_from', f['severity'])})")
        if vf:
            L.append(f"- verification: **{vf.get('status')}**" + (f" by {vf['method']}" if vf.get("method") else "")
                     + (f": {vf.get('evidence')}" if vf.get("evidence") else f" ({vf.get('reason')})"))
            if vf.get("actions"):
                L.append(f"- verifier actions: {vf['actions']}")
        L.append("")
    if rev["dropped"]:
        L += ["<details><summary>Dropped by verification</summary>", ""]
        L += [f"- **{f['title']}** (`{f['file']}:{f['line']}`): {f['verification']['evidence']}" for f in rev["dropped"]]
        L += ["", "</details>"]
    return "\n".join(L) + "\n"
