"""Deterministic 'ready to submit?' checklist. Each item: {item, status: pass|fail|warn|na, evidence}."""
import glob, os, re
from .diff import formatting_only_hunks
from .util import CODE_EXT_RX, ISSUE_KW, TEST_PATH_RX, gh_json, git, project_dir, read_json, upstream_slug

TEMPLATES = [".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md", "PULL_REQUEST_TEMPLATE.md",
             "docs/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE/pull_request_template.md"]
CONVENTIONAL_RX = re.compile(r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+")
# An issue link needs a linking keyword or an /issues/ URL. A bare "#123" is often a PR reference ("overlaps #2693"),
# so it does not count.
ISSUE_RX = re.compile(r"(?:\b" + ISSUE_KW + r"\b(?:\*\*)?\s*:?\s*(?:\*\*)?\s*#(\d+)\b)|(?:github\.com/[^/\s]+/[^/\s]+/issues/(\d+))", re.I)
# Template placeholders that look like a link but aren't: "Closes #(issue_number)", "Fixes #ISSUE", "#N", "#<n>", "#XXXX".
PLACEHOLDER_RX = re.compile(r"\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?|related(?:\s+issues?)?|issues?)\b\s*:?\s*"
                            r"#\s*(?:\(|<|\{|\[|ISSUE\b|N\b|X{2,}|_+|issue[_ ]?(?:number|no|id)\b)", re.I)


def _item(item, status, evidence):
    return {"item": item, "status": status, "evidence": evidence}


def find_draft(repo, draft=None):
    """The draft to judge: --draft if given, else PR_DRAFT.md. PR_DRAFT.polished.md is a proposal from `polish`
    that the author hasn't accepted yet (copy it over PR_DRAFT.md to accept), so it is never picked up implicitly."""
    for p in [draft] if draft else [os.path.join(repo, "PR_DRAFT.md")]:
        if p and os.path.exists(p):
            return p, open(p, errors="replace").read()
    return None, ""


FENCE_RX = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
BODY_HEAD_RX = re.compile(r"^#{1,4}\s+(pr\s+)?body\s*:?\s*$", re.I)
TITLE_HEAD_RX = re.compile(r"^#{1,4}\s+(pr\s+)?title\s*:?\s*$", re.I)
# Headings that open the author's own notes. Everything from the first one on is never submitted.
# The phrase must open the heading (emoji/punctuation aside), so "## Handling the DO NOT SUBMIT marker" is still body.
NOTES_HEAD_RX = re.compile(r"^#{1,4}\s+[^\w\n]*(explain it to me|q&a prep|author'?s? notes|(private|internal) notes|"
                           r"notes (for|to) (me|myself|the author)|not for (submission|upstream|the pr)|do not submit|"
                           r"issue to file)\b", re.I)
NOTES_MARKER_RX = re.compile(r"^\s*<!--\s*crucible:\s*notes\s*-->\s*$", re.I)
NOTES_MARKER = "<!-- crucible: notes -->"


def _unfenced(lines):
    """Indexes of lines outside fenced code blocks (CommonMark: a fence closes on the same char, at least as long).

    Deliberately simple: fences indented 4+ spaces (e.g. inside list items) aren't recognised, and an unclosed
    fence runs to the end of the file, so markers after it are not seen and the draft is judged as all body."""
    out, fence = [], None
    for i, l in enumerate(lines):
        m = FENCE_RX.match(l)
        if fence is None:
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):  # "```x``` ..." is inline code, not a fence
                fence = m.group(1)
            else:
                out.append(i)
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
            fence = None
    return out


def split_draft(text):
    """Separate what will be pasted into the PR from the author's private notes in PR_DRAFT.md.

    -> {"title", "body", "notes"}. Lines inside code fences never act as markers.
    - Notes start at the first notes heading (e.g. "Explain it to me", "Issue to file first") or a
      `<!-- crucible: notes -->` line (the marker itself is not part of the notes).
    - Before that boundary, a `## Body` heading starts the body; whatever precedes it (a metadata preamble, a
      `## Title` section) is kept with the notes. Without `## Body`, a `## Title` section or a leading `# Title`
      line gives the title and the body follows it.
    A draft without any markers is all body, as before."""
    lines = (text or "").split("\n")
    open_lines = _unfenced(lines)
    end = next((i for i in open_lines if NOTES_HEAD_RX.match(lines[i]) or NOTES_MARKER_RX.match(lines[i])), len(lines))
    head = [i for i in open_lines if i < end]
    body_at = next((i for i in head if BODY_HEAD_RX.match(lines[i])), None)
    title_at = next((i for i in head if TITLE_HEAD_RX.match(lines[i]) and (body_at is None or i < body_at)), None)
    title, start, preamble = "", 0, []
    if title_at is not None:
        stop = body_at if body_at is not None else end
        val = next((i for i in range(title_at + 1, stop) if lines[i].strip()), None)
        if val is not None and not lines[val].startswith("#"):
            title = lines[val].strip().strip("`").strip()
            start = val + 1
        else:
            start = title_at + 1
        preamble = lines[:title_at]
    elif body_at is None and lines and re.match(r"^#\s+\S", lines[0]):
        title, start = lines[0][1:].strip(), 1
    if body_at is not None:
        preamble, start = lines[:body_at], body_at + 1
    body = "\n".join(lines[start:end])
    # a trailing horizontal rule usually separated the body from the notes
    body = re.sub(r"(\n\s*(-{3,}|\*{3,}|_{3,})\s*)+\s*$", "", "\n" + body).strip("\n")
    rest = lines[end + 1:] if end < len(lines) and NOTES_MARKER_RX.match(lines[end]) else lines[end:]
    notes = "\n\n".join(x for x in ("\n".join(preamble).strip("\n"), "\n".join(rest).strip("\n")) if x)
    return {"title": title, "body": body, "notes": notes, "notes_line": end + 1 if end < len(lines) else None}


def submitted_text(text):
    """The title (as a plain line, so it doesn't count as a body heading) and body as they would be submitted."""
    d = split_draft(text)
    return (d["title"] + "\n\n" if d["title"] else "") + d["body"]


def template_headings(repo):
    for t in TEMPLATES:
        p = os.path.join(repo, t)
        if os.path.exists(p):
            txt = re.sub(r"<!--.*?-->", "", open(p, errors="replace").read(), flags=re.S)
            return t, [h.strip("# ").strip() for h in txt.split("\n") if re.match(r"^#{1,4}\s+\S", h)]
    return None, []


def check_draft(repo, draft_text):
    tpl, heads = template_headings(repo)
    if not draft_text:
        return _item("PR description drafted", "fail", "no PR_DRAFT.md found next to the change")
    if not tpl:
        ok = len(draft_text) > 200
        return _item("PR description drafted", "pass" if ok else "warn",
                     f"no PR template in repo; draft is {len(draft_text)} chars")
    low = draft_text.lower()
    missing = [h for h in heads if h.lower() not in low]
    return _item("PR description follows template", "fail" if missing else "pass",
                 f"{tpl}: missing sections {missing}" if missing else f"{tpl}: all {len(heads)} sections present")


def linked_issues(draft_text):
    """Every number the draft links with a keyword or an issue URL, in order, without duplicates."""
    out = []
    for m in ISSUE_RX.finditer(draft_text or ""):
        n = int(m.group(1) or m.group(2))
        if n not in out:
            out.append(n)
    return out


def linked_issue(draft_text):
    found = linked_issues(draft_text)
    return found[0] if found else None


def resolve_issue(repo, numbers):
    """The first linked number that is an issue, not a PR ("Refs #2693" often names a PR). -> (issue, prs_skipped)."""
    slug = upstream_slug(repo)
    if not slug:
        return (numbers[0] if numbers else None), []
    skipped = []
    for n in numbers:
        data = gh_json(f"repos/{slug}/issues/{n}")
        if data is None:              # can't tell (rate limit, no network): trust the link
            return n, skipped
        if "pull_request" in data:
            skipped.append(n)
            continue
        return n, skipped
    return None, skipped


def issue_placeholder(draft_text):
    m = PLACEHOLDER_RX.search(draft_text or "")
    return m.group(0).strip() if m else None


def tests_touched(paths):
    src = [p for p in paths if CODE_EXT_RX.search(p) and not TEST_PATH_RX.search(p)]
    tests = [p for p in paths if TEST_PATH_RX.search(p)]
    if not src:
        return _item("tests updated for behaviour change", "na", "no source files changed")
    return _item("tests updated for behaviour change", "pass" if tests else "fail",
                 f"tests: {tests[:5]}" if tests else f"source changed ({src[:4]}) but no test file touched")


def api_docs_touched(files):
    api = []
    for f in files:
        if TEST_PATH_RX.search(f["path"]) or not CODE_EXT_RX.search(f["path"]):
            continue
        for h in f["hunks"]:
            for k, t, *_ in h["lines"]:
                if k in "+-" and re.match(r"\s*(export\s+(default\s+)?(function|class|const|let|interface|type|enum|async)|def [a-zA-Z]|public\s)", t):
                    api.append(f"{f['path']}:{h['new_start']}")
                    break
    if not api:
        return _item("docs/types updated for public API change", "na", "no exported/public signature lines changed")
    docs = [f["path"] for f in files if re.search(r"(\.d\.ts$|(^|/)docs?/|\.md$|\.mdx$|types?/)", f["path"])]
    return _item("docs/types updated for public API change", "pass" if docs else "warn",
                 f"API lines changed at {sorted(set(api))[:4]}; docs/types touched: {docs[:4] or 'none'}")


def changelog(repo, paths):
    if os.path.isdir(os.path.join(repo, ".changeset")):
        new = [p for p in paths if p.startswith(".changeset/") and p.endswith(".md")]
        return _item("changeset added", "pass" if new else "fail", new[0] if new else "repo uses changesets; none added")
    if os.path.exists(os.path.join(repo, "CHANGELOG.md")):
        return _item("changelog", "pass" if "CHANGELOG.md" in paths else "warn",
                     "CHANGELOG.md updated" if "CHANGELOG.md" in paths else "CHANGELOG.md exists but untouched (may be generated at release)")
    return _item("changelog", "na", "no changelog convention found")


def commit_style(repo, base, subjects):
    cfg = glob.glob(os.path.join(repo, "commitlint.config.*")) + glob.glob(os.path.join(repo, ".commitlintrc*"))
    pkg = read_json(os.path.join(repo, "package.json"), {}) or {}
    if not cfg and "commitlint" not in pkg:
        return _item("commit message style", "na", "no commitlint config")
    bad = [s for s in subjects if not CONVENTIONAL_RX.match(s)]
    return _item("commit message style (conventional)", "fail" if bad else "pass",
                 f"non-conventional: {bad[:3]}" if bad else f"{len(subjects)} commit(s) conventional")


def dco(repo, base):
    txt = ""
    for n in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md"):
        p = os.path.join(repo, n)
        if os.path.exists(p):
            txt += open(p, errors="replace").read()
    required = os.path.exists(os.path.join(repo, ".github", "dco.yml")) or re.search(r"\bDCO\b|Signed-off-by", txt)
    if not required:
        return _item("DCO sign-off", "na", "not required")
    bodies = git(repo, "log", "--format=%H%x00%B%x01", f"{base}..HEAD").split("\x01")
    missing = [b.split("\x00")[0][:8] for b in bodies if b.strip() and "Signed-off-by:" not in b]
    return _item("DCO sign-off", "fail" if missing else "pass", f"unsigned: {missing}" if missing else "all commits signed off")


def size(project, files):
    meta = read_json(os.path.join(project_dir(project), "meta.json"), {}) or {}
    n = sum(1 for f in files for h in f["hunks"] for k, *_ in h["lines"] if k in "+-")
    med = meta.get("median_merged_pr_lines")
    if not med:
        return _item("size vs project norm", "na", f"{n} changed lines; run `crucible learn` for the project median")
    st = "fail" if n > 3 * med else "warn" if n > 1.5 * med else "pass"
    return _item("size vs project norm", st, f"{n} changed lines vs median merged PR {med}")


def unclaimed(repo, issue, me=None):
    slug = upstream_slug(repo)
    if not issue or not slug:
        return _item("issue still unclaimed", "na", "no linked issue" if not issue else "no GitHub remote")
    data = gh_json(f"repos/{slug}/issues/{issue}")
    if not data:
        return _item("issue still unclaimed", "warn", f"could not read {slug}#{issue}")
    probs = []
    if "pull_request" in data:
        return _item("issue still unclaimed", "warn", f"{slug}#{issue} is a pull request, not an issue")
    if data.get("state") != "open":
        probs.append(f"issue is {data.get('state')}")
    who = [a["login"] for a in data.get("assignees") or [] if a.get("login") != me]
    if who:
        probs.append(f"assigned to {who}")
    tl = gh_json(f"repos/{slug}/issues/{issue}/timeline?per_page=100") or []
    prs = []
    for ev in tl if isinstance(tl, list) else []:
        src = (ev.get("source") or {}).get("issue") or {}
        if ev.get("event") == "cross-referenced" and src.get("pull_request") and src.get("state") == "open" \
                and (src.get("user") or {}).get("login") != me:
            prs.append(src.get("html_url"))
    if prs:
        probs.append(f"open PRs already reference it: {prs[:3]}")
    return _item("issue still unclaimed", "fail" if probs else "pass",
                 "; ".join(probs) or f"{slug}#{issue} open, unassigned, no competing open PR")


# Files almost every PR touches; sharing one of them says nothing about two PRs changing the same code.
SHARED_FILE_RX = re.compile(r"(^|/)(CHANGELOG[^/]*|CHANGES[^/]*|HISTORY[^/]*|NEWS[^/]*|package(-lock)?\.json|"
                            r"npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|Cargo\.lock|poetry\.lock|"
                            r"uv\.lock|Pipfile\.lock|go\.sum|Gemfile\.lock|composer\.lock)$|^\.changeset/", re.I)
OPEN_PRS_QUERY = """query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){
 pullRequests(states:OPEN,first:100,after:$after,orderBy:{field:UPDATED_AT,direction:DESC}){
  totalCount pageInfo{hasNextPage endCursor}
  nodes{number url isDraft author{login __typename} files(first:100){nodes{path}}}}}}"""
OPEN_PR_PAGES = 3  # the 300 most recently updated open PRs, at most 3 GraphQL calls


def open_prs(slug, pages=OPEN_PR_PAGES):
    """Open PRs with their changed paths, most recently updated first. -> (prs, total), or (None, None) if the
    API can't be read. Only a PR's first 100 changed paths are compared."""
    owner, name = slug.split("/", 1)
    prs, total, after = [], 0, None
    for _ in range(pages):
        # -f, not -F: -F turns a repo named "2048" or "true" into a number or a boolean, which String! rejects
        args = ["graphql", "-f", f"query={OPEN_PRS_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}"]
        if after:
            args += ["-f", f"after={after}"]
        data = gh_json(*args) or gh_json(*args)  # the files query is heavy; GitHub sometimes fails it once
        conn = ((data or {}).get("data") or {}).get("repository") or {}
        conn = conn.get("pullRequests")
        if not conn:
            return (prs, total) if prs else (None, None)
        total = conn.get("totalCount") or 0
        for n in conn.get("nodes") or []:
            author = n.get("author") or {}
            prs.append({"number": n.get("number"), "url": n.get("url"), "draft": bool(n.get("isDraft")),
                        "author": author.get("login"), "bot": author.get("__typename") == "Bot",
                        "paths": [f["path"] for f in (n.get("files") or {}).get("nodes") or []]})
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")
    return prs, total


HUNK_RX = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.M)
OVERLAP_CANDIDATES = 20  # PRs whose patches are fetched to compare lines; more file-level matches are only counted


def _changed_old_lines(hunks):
    """Base-side line numbers our change touches: each removed line, and for an insertion the base line it goes
    before. Context lines are left out, so the margin doesn't depend on the --unified width the diff was made with."""
    out = set()
    for h in hunks:
        o = h["old_start"] if h["old_len"] else h["old_start"] + 1  # "-12,0" inserts after base line 12
        for kind, *_ in h["lines"]:
            if kind in "+-":
                out.add(o)
            if kind != "+":
                o += 1
    return out


def _pr_hunks(slug, number):
    """{path: [(start, end)] on the base side, 3 context lines included} for one PR, or None if it can't be read.
    A pure rename maps to []. Any other file GitHub sends without a patch (binary, mode-only, or a diff too large to
    show) maps to None: it can't be compared."""
    data = gh_json(f"repos/{slug}/pulls/{number}/files?per_page=100")
    if not isinstance(data, list):
        return None
    out = {}
    for f in data:
        found = HUNK_RX.findall(f.get("patch") or "")
        # A pure rename has no lines to compare. A binary file also arrives with changes 0 and no patch, and a
        # mode-only change looks the same, so neither is assumed to be distant.
        if found or (f.get("status") == "renamed" and f.get("changes") == 0):
            out[f.get("filename")] = [(int(a), int(a) + max(int(n) if n else 1, 1) - 1) for a, n in found]
        else:
            out[f.get("filename")] = None
    return out


def overlapping_prs(repo, files, me=None):
    """Open PRs by someone else that change the same lines as this change. The linked-issue check only sees PRs that
    reference the issue; a PR fixing a neighbouring issue in the same code (Heroic #5776) is still a claim to respect.

    Busy files are touched by many PRs, so the same file alone is only counted; a PR is flagged when a line we change
    falls inside one of its hunks on the base side (GitHub's patches carry 3 context lines, so changes up to 3 lines
    apart meet; line drift between the two bases is not corrected). A new file shared with a PR counts as
    overlapping. A shared file that can't be compared (no patch, or past the 100 files read) is reported as not
    compared, never as distant. Lockfiles, changelogs and package.json are ignored, and bots are skipped."""
    name = "no open PR changes the same lines"
    slug = upstream_slug(repo)
    if not slug:
        return _item(name, "na", "no GitHub remote")
    ours = {f["path"]: _changed_old_lines(f["hunks"]) for f in files
            if f.get("path") and not f.get("deleted") and not SHARED_FILE_RX.search(f["path"])}
    added = {f["path"] for f in files if f.get("added")}
    if not ours:
        return _item(name, "na", "only shared files (lockfiles, changelogs, package.json) changed")
    prs, total = open_prs(slug)
    if prs is None:
        return _item(name, "warn", f"could not list open PRs on {slug}")
    cands = []
    for pr in prs:
        if pr["bot"] or (me and pr["author"] == me):
            continue
        same = sorted(set(ours).intersection(pr["paths"]))
        if same:
            cands.append((pr, same))
    # Most focused first: a 5-file PR sharing 2 of our files is likelier the same fix than a 100-file rewrite sharing 3.
    # The sort is stable, so ties keep the most recently updated first.
    cands.sort(key=lambda c: -len(c[1]) / max(len(c[0]["paths"]), 1))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        patches = list(ex.map(lambda c: _pr_hunks(slug, c[0]["number"]), cands[:OVERLAP_CANDIDATES]))
    hits, distant, unread = [], [], []
    for (pr, same), hunks in zip(cands, patches):
        if hunks is None:
            unread.append(pr["number"])
            continue
        meet = [p for p in same if p in added or any(a <= n <= b for a, b in hunks.get(p) or [] for n in ours[p])]
        if meet:
            hits.append((pr, meet))
        elif any(hunks.get(p) is None for p in same):
            unread.append(pr["number"])
        else:
            distant.append(pr["number"])
    nums = lambda ns: ", ".join(f"#{n}" for n in ns[:5]) + (" …" if len(ns) > 5 else "")
    notes = [f"checked {len(prs)} of {total} open PRs" + (", most recently updated first" if len(prs) < total else "")]
    if distant:
        notes.append(f"{len(distant)} touch the same files elsewhere ({nums(distant)})")
    if len(cands) > OVERLAP_CANDIDATES:
        notes.append(f"{len(cands) - OVERLAP_CANDIDATES} more share a file but weren't compared line by line "
                     f"({nums([c[0]['number'] for c in cands[OVERLAP_CANDIDATES:]])})")
    if unread:
        notes.append(f"{len(unread)} couldn't be compared, no readable patch ({nums(unread)})")
    if not hits:
        uncompared = unread or len(cands) > OVERLAP_CANDIDATES
        return _item(name, "warn" if uncompared else "pass", "; ".join(notes))
    shown = "; ".join(f"#{pr['number']}{' (draft)' if pr['draft'] else ''} by {pr['author']} "
                      f"({len(meet)} of its {len(pr['paths'])} files): "
                      f"{', '.join(meet[:3])}{f' +{len(meet) - 3} more' if len(meet) > 3 else ''}" for pr, meet in hits[:5])
    more = f"; +{len(hits) - 5} more" if len(hits) > 5 else ""
    return _item(name, "warn", f"{shown}{more}. Read them before submitting: same code, possibly the same fix "
                               f"({'; '.join(notes)})")


def evaluate(repo, project, base, files, draft=None, me="JROtto5", offline=False):
    paths = [f["path"] for f in files]
    draft_path, full = find_draft(repo, draft)
    draft_text = submitted_text(full)  # author notes in the draft are not part of the PR
    numbers = linked_issues(draft_text)
    issue, prs = (numbers[0] if numbers else None, []) if offline else resolve_issue(repo, numbers)
    subjects = [s for s in git(repo, "log", "--format=%s", f"{base}..HEAD").split("\n") if s]
    fmt = formatting_only_hunks(files)
    items = [
        check_draft(repo, draft_text) if draft_text.strip() or not full.strip() else
        _item("PR description drafted", "fail", f"{os.path.basename(draft_path)} exists, but nothing is left before the "
              f"author-notes boundary at line {split_draft(full)['notes_line']}; put the body above it or under `## Body`"),
        _item("issue linked", "pass" if issue else "fail", f"#{issue}" if issue else
              (f"template placeholder still in the draft: {issue_placeholder(draft_text)!r}" if issue_placeholder(draft_text)
               else f"the linked number(s) {['#' + str(n) for n in prs]} are pull requests, not issues" if prs
               else "no 'Fixes #N' / 'Related issue: #N' / issue URL in the draft (a bare #N doesn't count)")),
        tests_touched(paths),
        api_docs_touched(files),
        changelog(repo, paths),
        commit_style(repo, base, subjects),
        dco(repo, base),
        _item("no formatting-only churn", "fail" if fmt else "pass", f"whitespace-only hunks: {fmt[:5]}" if fmt else "none"),
        size(project, files),
        _item("issue still unclaimed", "na", "offline") if offline else unclaimed(repo, issue, me),
        _item("no open PR changes the same lines", "na", "offline") if offline else overlapping_prs(repo, files, me),
    ]
    return {"draft": draft_path, "issue": issue, "items": items,
            "ready": not any(i["status"] == "fail" for i in items)}
