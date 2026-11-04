#!/usr/bin/env python3
"""crucible: an independent, evidence-first AI code reviewer for your own branches.

Design (all general review-automation ideas, implemented from scratch):
  * deterministic scanners run first (cheap, certain)
  * a reviewer on a DIFFERENT model than the author finds candidate issues
  * every finding carries severity, file:line and a "wrong if" falsification test
  * a verification pass tries to disprove each finding and drops what fails
  * verdicts belong to one commit SHA; a new commit needs a new review
  * the author answers every finding (fixed / refuted / deferred)
  * GREEN = nothing critical/important open and every finding answered
  * votes and a per-project "repeat mistakes" list feed every future review
  * a human always submits; crucible never pushes, comments or approves

Usage:
  crucible review [REPO] --base origin/HEAD      review HEAD vs base
  crucible status [REPO]                         verdict for the current HEAD
  crucible answer ID fixed|refuted|deferred "note" [--repo REPO]
  crucible vote ID up|down "reason" [--repo REPO]
  crucible remember PROJECT "lesson"             add to the repeat-mistakes list

Env:
  CRUCIBLE_HOME          state dir (default ~/.crucible)
  CRUCIBLE_CLAUDE_DIR    CLAUDE_CONFIG_DIR of the account to bill (your personal one)
  CRUCIBLE_REVIEW_MODEL  default claude-sonnet-5-5   (pick one that did NOT write the code)
  CRUCIBLE_VERIFY_MODEL  default claude-opus-5-5
"""
import argparse, datetime as dt, fcntl, json, os, re, subprocess, sys, textwrap

HOME = os.path.expanduser(os.environ.get("CRUCIBLE_HOME", "~/.crucible"))
REVIEW_MODEL = os.environ.get("CRUCIBLE_REVIEW_MODEL", "claude-sonnet-5-5")
VERIFY_MODEL = os.environ.get("CRUCIBLE_VERIFY_MODEL", "claude-opus-5-5")
SEV = ["critical", "important", "medium", "low"]
BLOCKING = {"critical", "important"}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": SEV},
                "file": {"type": "string"}, "line": {"type": "integer"},
                "title": {"type": "string"},
                "problem": {"type": "string"},
                "caused_by_this_change": {"type": "boolean"},
                "reachable_in_real_use": {"type": "boolean"},
                "wrong_if": {"type": "string"},
                "fix": {"type": "string"},
            },
            "required": ["severity", "file", "line", "title", "problem", "caused_by_this_change",
                         "reachable_in_real_use", "wrong_if", "fix"]}},
    },
    "required": ["summary", "findings"],
}
VERIFY_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "keep": {"type": "boolean"},
                       "severity": {"type": "string", "enum": SEV}, "evidence": {"type": "string"}},
        "required": ["id", "keep", "severity", "evidence"]}}},
    "required": ["verdicts"],
}

SECRET_RX = re.compile(r"(sk-ant-[\w-]{10,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
                       r"-----BEGIN [A-Z ]*PRIVATE KEY|xox[abpr]-[\w-]{10,}|eyJ[\w-]{20,}\.[\w-]{20,}\.[\w-]{10,})")
DEBUG_RX = re.compile(r"^\+(?!\+).*\b(debugger;|console\.log\(|print\(['\"]DEBUG|pdb\.set_trace\(\))")
CONFLICT_RX = re.compile(r"^\+(<<<<<<<|>>>>>>>|=======$)")


def git(repo, *a, check=True):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=check).stdout.strip()


def project_of(repo):
    url = git(repo, "remote", "get-url", "origin", check=False)
    m = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return (m.group(1) if m else os.path.basename(os.path.abspath(repo))).replace("/", "__")


def state_dir(repo, sha=None):
    d = os.path.join(HOME, "reviews", project_of(repo), sha or git(repo, "rev-parse", "HEAD"))
    os.makedirs(d, exist_ok=True)
    return d


def memory_path(project):
    os.makedirs(os.path.join(HOME, "memory"), exist_ok=True)
    return os.path.join(HOME, "memory", f"{project}.md")


def claude(prompt, model, schema, cwd, effort="high"):
    env = dict(os.environ)
    if os.environ.get("CRUCIBLE_CLAUDE_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(os.environ["CRUCIBLE_CLAUDE_DIR"])
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--output-format", "json",
           "--json-schema", json.dumps(schema),
           "--allowedTools", "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(git grep:*)",
           "--permission-mode", "default", prompt]
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=1800)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"model call failed: {r.stderr[-800:] or r.stdout[-800:]}")
    if d.get("is_error") or "structured_output" not in d:
        sys.exit(f"model call failed: {str(d.get('result'))[:800]}")
    return d["structured_output"], d.get("total_cost_usd", 0)


def scanners(diff):
    out = []
    file, line = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            file = raw[6:] if raw.startswith("+++ b/") else raw[4:]
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw); line = int(m.group(1)) - 1 if m else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            line += 1
            for rx, sev, title in ((SECRET_RX, "critical", "Possible secret in added line"),
                                   (CONFLICT_RX, "critical", "Merge conflict marker"),
                                   (DEBUG_RX, "low", "Debug statement left in")):
                if rx.search(raw):
                    out.append({"severity": sev, "file": file, "line": line, "title": title,
                                "problem": raw[1:].strip()[:200], "caused_by_this_change": True,
                                "reachable_in_real_use": True, "source": "scanner",
                                "wrong_if": "the matched text is a test fixture or placeholder, not a real value",
                                "fix": "remove it or move it to configuration"})
        elif not raw.startswith("-"):
            line += 1
    return out


def project_rules(repo):
    texts = []
    for name in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md"):
        p = os.path.join(repo, name)
        if os.path.exists(p):
            texts.append(f"--- {name} ---\n" + open(p, errors="replace").read()[:6000])
    return "\n".join(texts) or "(no contribution guide found)"


def cmd_review(a):
    repo = os.path.abspath(a.repo)
    sha = git(repo, "rev-parse", "HEAD")
    base = git(repo, "merge-base", a.base, "HEAD")
    d = state_dir(repo, sha)
    lock = open(os.path.join(d, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("a review of this commit is already running")
    if os.path.exists(os.path.join(d, "review.json")) and not a.force:
        print(f"already reviewed {sha[:10]} (use --force to redo)"); return cmd_status(a)
    diff = git(repo, "diff", "--unified=5", f"{base}..HEAD")
    if not diff:
        sys.exit("empty diff")
    project = project_of(repo)
    mem = open(memory_path(project)).read() if os.path.exists(memory_path(project)) else "(none yet)"
    found = scanners(diff)
    stat = git(repo, "diff", "--stat", f"{base}..HEAD")
    log = git(repo, "log", "--format=%h %s", f"{base}..HEAD")
    prompt = textwrap.dedent(f"""\
        You are a strict senior maintainer of {project.replace('__', '/')} reviewing an outside contributor's change
        before it is submitted upstream. You are in a checkout of the change (HEAD {sha[:10]}). Read the full files
        around each hunk, not just the diff, and check callers with grep where it matters.

        Report only real problems: correctness bugs, regressions, missing or wrong tests, API/backward-compat breaks,
        performance traps, security issues, and violations of the project's own contribution rules. No style nits
        unless the project's rules require them. Every finding needs a concrete file and line, and a "wrong_if": the
        specific observation that would prove the finding false. Set caused_by_this_change and
        reachable_in_real_use honestly. An empty findings list is a valid, good answer.

        Project contribution rules:
        {project_rules(repo)}

        Repeat mistakes to watch for in this project (learned from past reviews):
        {mem}

        Commits:
        {log}

        Diffstat:
        {stat}

        Diff (base {base[:10]}..HEAD):
        {diff[:120000]}
        """)
    review, cost1 = claude(prompt, REVIEW_MODEL, FINDINGS_SCHEMA, repo)
    cands = found + [dict(f, source="review") for f in review["findings"]]
    for i, f in enumerate(cands, 1):
        f["id"] = f"CR-{sha[:6]}-{i:02d}"
    kept, cost2 = cands, 0
    model_cands = [f for f in cands if f["source"] == "review"]
    if model_cands:
        vprompt = textwrap.dedent(f"""\
            You are verifying another reviewer's findings on this checkout (HEAD {sha[:10]}). Your job is to DISPROVE
            each one. For every finding, read the code it cites and actually perform its "wrong_if" check where you can
            (grep, read callers, read tests). Keep a finding only if it survives, is caused by this change, and is
            reachable in real use. You may lower or raise its severity. Give one or two sentences of evidence each.

            Findings:
            {json.dumps(model_cands, indent=1)}
            """)
        ver, cost2 = claude(vprompt, VERIFY_MODEL, VERIFY_SCHEMA, repo)
        vmap = {v["id"]: v for v in ver["verdicts"]}
        kept = []
        for f in cands:
            v = vmap.get(f["id"])
            if f["source"] == "scanner" or (v and v["keep"]):
                if v:
                    f["severity"], f["verification"] = v["severity"], v["evidence"]
                kept.append(f)
            elif v:
                f["dropped_by_verification"] = v["evidence"]
        dropped = [f for f in cands if "dropped_by_verification" in f]
        # a scanner hit that a verified model finding already covers (same file, within 1 line) is a duplicate
        model_spots = {(f["file"], f["line"]) for f in kept if f["source"] == "review"}
        kept = [f for f in kept if f["source"] != "scanner" or not any(
            (f["file"], f["line"] + d) in model_spots for d in (-1, 0, 1))]
    else:
        dropped = []
    out = {"repo": project, "sha": sha, "base": base, "at": dt.datetime.now().isoformat(timespec="seconds"),
           "review_model": REVIEW_MODEL, "verify_model": VERIFY_MODEL, "summary": review["summary"],
           "findings": kept, "dropped": dropped, "cost_usd": round(cost1 + cost2, 4)}
    json.dump(out, open(os.path.join(d, "review.json"), "w"), indent=1)
    cmd_status(a)


def load(repo):
    d = state_dir(repo)
    p = os.path.join(d, "review.json")
    if not os.path.exists(p):
        return d, None, {}
    ans_p = os.path.join(d, "answers.json")
    return d, json.load(open(p)), (json.load(open(ans_p)) if os.path.exists(ans_p) else {})


def verdict(rev, ans):
    open_block = [f for f in rev["findings"] if f["severity"] in BLOCKING and ans.get(f["id"], {}).get("disposition") not in ("fixed", "refuted")]
    unanswered = [f for f in rev["findings"] if f["id"] not in ans]
    return ("GREEN" if not open_block and not unanswered else "NOT_GREEN"), open_block, unanswered


def cmd_status(a):
    repo = os.path.abspath(a.repo)
    d, rev, ans = load(repo)
    sha = git(repo, "rev-parse", "HEAD")
    if not rev:
        print(f"NO REVIEW for HEAD {sha[:10]}. Run: crucible review {a.repo} --base <upstream-branch>")
        sys.exit(2)
    v, blocking, unanswered = verdict(rev, ans)
    lines = [f"# crucible · {rev['repo'].replace('__', '/')} @ {sha[:10]}", "",
             f"**Verdict: {v}** · {len(rev['findings'])} findings kept, {len(rev['dropped'])} dropped by verification · "
             f"review {rev['review_model']}, verify {rev['verify_model']} · ${rev['cost_usd']}", "", rev["summary"], ""]
    for f in sorted(rev["findings"], key=lambda f: SEV.index(f["severity"])):
        a_ = ans.get(f["id"])
        tag = f" → **{a_['disposition']}**: {a_['note']}" if a_ else " → *unanswered*"
        lines += [f"### {f['id']} · {f['severity']} · {f['file']}:{f['line']}", f"**{f['title']}**{tag}", "",
                  f["problem"], "", f"- wrong if: {f['wrong_if']}", f"- fix: {f['fix']}"]
        if f.get("verification"):
            lines.append(f"- verified: {f['verification']}")
        lines.append("")
    if rev["dropped"]:
        lines += ["<details><summary>Dropped by verification</summary>", ""]
        lines += [f"- {f['title']} ({f['file']}:{f['line']}): {f['dropped_by_verification']}" for f in rev["dropped"]]
        lines += ["", "</details>"]
    report = "\n".join(lines)
    open(os.path.join(d, "report.md"), "w").write(report)
    print(report)
    print(f"\n(report: {os.path.join(d, 'report.md')})")
    sys.exit(0 if v == "GREEN" else 1)


def cmd_answer(a):
    repo = os.path.abspath(a.repo)
    d, rev, ans = load(repo)
    if not rev:
        sys.exit("no review for this HEAD. A new commit needs a new review")
    if a.id not in {f["id"] for f in rev["findings"]}:
        sys.exit(f"unknown finding {a.id}")
    ans[a.id] = {"disposition": a.disposition, "note": a.note, "at": dt.datetime.now().isoformat(timespec="seconds")}
    json.dump(ans, open(os.path.join(d, "answers.json"), "w"), indent=1)
    v, _, _ = verdict(rev, ans)
    print(f"{a.id} → {a.disposition}. Verdict now {v}")


def cmd_vote(a):
    repo = os.path.abspath(a.repo)
    project = project_of(repo)
    with open(os.path.join(HOME, "votes.jsonl"), "a") as fh:
        fh.write(json.dumps({"project": project, "id": a.id, "vote": a.vote, "reason": a.reason,
                             "at": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
    if a.vote == "down":
        with open(memory_path(project), "a") as fh:
            fh.write(f"- Do NOT flag: {a.reason}\n")
    print("recorded")


def cmd_remember(a):
    with open(memory_path(a.project.replace("/", "__")), "a") as fh:
        fh.write(f"- {a.lesson}\n")
    print("remembered")


def main():
    p = argparse.ArgumentParser(prog="crucible", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("review"); r.add_argument("repo", nargs="?", default="."); r.add_argument("--base", default="origin/HEAD"); r.add_argument("--force", action="store_true")
    st = s.add_parser("status"); st.add_argument("repo", nargs="?", default=".")
    an = s.add_parser("answer"); an.add_argument("id"); an.add_argument("disposition", choices=["fixed", "refuted", "deferred"]); an.add_argument("note"); an.add_argument("--repo", default=".")
    vo = s.add_parser("vote"); vo.add_argument("id"); vo.add_argument("vote", choices=["up", "down"]); vo.add_argument("reason"); vo.add_argument("--repo", default=".")
    re_ = s.add_parser("remember"); re_.add_argument("project"); re_.add_argument("lesson")
    a = p.parse_args()
    {"review": cmd_review, "status": cmd_status, "answer": cmd_answer, "vote": cmd_vote, "remember": cmd_remember}[a.cmd](a)


if __name__ == "__main__":
    main()
