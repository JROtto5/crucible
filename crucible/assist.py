"""`crucible prep` (likely maintainer questions) and `crucible reply` (draft answers to real review comments).
Drafts only: nothing is ever posted."""
import json, os, re, textwrap
from .readiness import find_draft, split_draft, submitted_text
from .review import load, project_rules_text
from .util import Budget, Failed, claude, gh_json, git, project_key

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "answering-maintainers.md")

PREP_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "maxItems": 12, "items": {
    "type": "object", "properties": {"question": {"type": "string"}, "answer": {"type": "string"},
                                     "evidence": {"type": "string"}, "risk": {"type": "string", "enum": ["high", "medium", "low"]}},
    "required": ["question", "answer", "evidence", "risk"]}}, "explain": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions", "explain"]}

REPLY_SCHEMA = {"type": "object", "properties": {"replies": {"type": "array", "items": {"type": "object", "properties": {
    "comment_url": {"type": "string"}, "reviewer": {"type": "string"}, "they_asked": {"type": "string"},
    "action": {"type": "string", "enum": ["accept_and_change", "answer_only", "push_back_with_evidence", "offer_follow_up"]},
    "code_change": {"type": "string"}, "draft_reply": {"type": "string"}},
    "required": ["comment_url", "reviewer", "they_asked", "action", "code_change", "draft_reply"]}}},
    "required": ["replies"]}


def checklist():
    return open(DOCS).read() if os.path.exists(DOCS) else ""


def run_prep(repo, model=os.environ.get("CRUCIBLE_ASSIST_MODEL", "claude-opus-5-5"), budget_usd=2.0, log=print):
    repo = os.path.abspath(repo)
    project, sha, d, rev, ans = load(repo)
    _, full = find_draft(repo)
    draft, notes = submitted_text(full), split_draft(full)["notes"]
    base = rev["base"] if rev else git(repo, "merge-base", "HEAD", "HEAD")
    diff = git(repo, "diff", "--no-color", f"{base}..HEAD")[:80000]
    findings = json.dumps([{k: f[k] for k in ("id", "severity", "title", "problem")} | {"answer": ans.get(f["id"])}
                           for f in (rev or {}).get("findings", [])], indent=1)
    prompt = textwrap.dedent(f"""\
        A contributor is about to submit this change to {project.replace('__', '/')}. Predict the questions the project's
        maintainers are most likely to ask in review (why this approach, alternatives, perf, back-compat, tests, scope,
        naming, docs), using the project's rules. For each, write the answer the contributor should give, grounded in
        evidence from the checkout (file:line, test names, commands and their results). Read code as needed.
        Also give 5-8 "explain it like you wrote it" bullets: the root cause, why the fix is correct, what was rejected.

        Project rules:
        {project_rules_text(repo, project)[:8000]}

        PR description draft, as it will be submitted:
        {draft[:6000] or '(none)'}

        The contributor's private notes (not submitted; use them as background, don't repeat them as questions):
        {notes[:4000] or '(none)'}

        Reviewer findings and the contributor's answers:
        {findings}

        Diff:
        {diff}
        """)
    out, cost = claude(prompt, model, PREP_SCHEMA, repo, Budget(budget_usd))
    L = [f"# Review prep · {project.replace('__', '/')} @ {sha[:10]}", "", "## Explain it like you wrote it", ""]
    L += [f"- {b}" for b in out["explain"]]
    L += ["", "## Likely maintainer questions", ""]
    for q in sorted(out["questions"], key=lambda q: ["high", "medium", "low"].index(q["risk"])):
        L += [f"### ({q['risk']}) {q['question']}", "", q["answer"], "", f"*Evidence:* {q['evidence']}", ""]
    path = os.path.join(repo, "PREP.md")
    open(path, "w").write("\n".join(L))
    open(os.path.join(d, "PREP.md"), "w").write("\n".join(L))
    log(f"wrote {path} (git-excluded) · ${round(cost, 4)}")
    return path


def parse_pr_url(url):
    m = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not m:
        raise Failed("expected a PR URL like https://github.com/owner/repo/pull/123")
    return m.group(1), int(m.group(2))


def run_reply(url, repo=None, model=os.environ.get("CRUCIBLE_ASSIST_MODEL", "claude-opus-5-5"), budget_usd=2.0, log=print):
    slug, num = parse_pr_url(url)
    pr = gh_json(f"repos/{slug}/pulls/{num}", check=True)
    me = (pr.get("user") or {}).get("login")
    comments = []
    for ep in (f"repos/{slug}/pulls/{num}/comments?per_page=100", f"repos/{slug}/issues/{num}/comments?per_page=100",
               f"repos/{slug}/pulls/{num}/reviews?per_page=100"):
        for c in gh_json(ep) or []:
            if (c.get("user") or {}).get("login") != me and (c.get("body") or "").strip():
                comments.append({"url": c.get("html_url"), "reviewer": (c.get("user") or {}).get("login"),
                                 "role": c.get("author_association"), "path": c.get("path"), "line": c.get("line"),
                                 "hunk": (c.get("diff_hunk") or "")[-800:], "body": c["body"][:2000],
                                 "at": c.get("created_at") or c.get("submitted_at")})
    if not comments:
        log("no reviewer comments yet")
        return None
    cwd = os.path.abspath(repo) if repo else os.getcwd()
    prompt = textwrap.dedent(f"""\
        You are helping the author of {url} ("{pr.get('title')}") answer the reviewers. Follow this checklist exactly:
        {checklist()}

        For each reviewer comment, decide the action, describe any code change needed precisely (file, what to change),
        and draft a short reply: lead with the answer, then evidence (commit, test, link). Never claim CI passed or a change
        was pushed unless it is true. If a checkout of the branch is the working directory, read it to ground answers.

        PR description:
        {(pr.get('body') or '')[:4000]}

        Reviewer comments:
        {json.dumps(comments, indent=1)[:50000]}
        """)
    out, cost = claude(prompt, model, REPLY_SCHEMA, cwd, Budget(budget_usd))
    L = [f"# Draft replies · {slug}#{num}", "", "_Drafts only. Review, edit, and post them yourself._", ""]
    for r in out["replies"]:
        L += [f"### {r['reviewer']}: {r['they_asked'][:120]}", f"<{r['comment_url']}> · action: **{r['action']}**", ""]
        if r["code_change"].strip():
            L += [f"**Code change:** {r['code_change']}", ""]
        L += ["```markdown", r["draft_reply"], "```", ""]
    path = os.path.join(cwd if repo else os.getcwd(), "REPLIES.md")
    open(path, "w").write("\n".join(L))
    log(f"wrote {path} · ${round(cost, 4)}")
    return path
