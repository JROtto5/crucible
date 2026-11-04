"""Deterministic 'ready to submit?' checklist. Each item: {item, status: pass|fail|warn|na, evidence}."""
import glob, os, re
from .diff import formatting_only_hunks
from .util import CODE_EXT_RX, TEST_PATH_RX, gh_json, git, project_dir, read_json, upstream_slug

TEMPLATES = [".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md", "PULL_REQUEST_TEMPLATE.md",
             "docs/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE/pull_request_template.md"]
CONVENTIONAL_RX = re.compile(r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+")
# An issue link needs a linking keyword or an /issues/ URL. A bare "#123" is often a PR reference ("overlaps #2693"),
# so it does not count.
ISSUE_RX = re.compile(r"(?:\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?|related(?:\s+issues?|\s+to)?|refs?|issues?)\b"
                      r"\s*:?\s*#(\d+)\b)|(?:github\.com/[^/\s]+/[^/\s]+/issues/(\d+))", re.I)
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


def linked_issue(draft_text):
    m = ISSUE_RX.search(draft_text or "")
    return int(m.group(1) or m.group(2)) if m else None


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
    if data.get("pull_request"):
        return _item("issue still unclaimed", "fail", f"{slug}#{issue} is a pull request, not an issue; link the issue with 'Closes #N'")
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


def evaluate(repo, project, base, files, draft=None, me="JROtto5", offline=False):
    paths = [f["path"] for f in files]
    draft_path, full = find_draft(repo, draft)
    draft_text = submitted_text(full)  # author notes in the draft are not part of the PR
    issue = linked_issue(draft_text)
    subjects = [s for s in git(repo, "log", "--format=%s", f"{base}..HEAD").split("\n") if s]
    fmt = formatting_only_hunks(files)
    items = [
        check_draft(repo, draft_text) if draft_text.strip() or not full.strip() else
        _item("PR description drafted", "fail", f"{os.path.basename(draft_path)} exists, but nothing is left before the "
              f"author-notes boundary at line {split_draft(full)['notes_line']}; put the body above it or under `## Body`"),
        _item("issue linked", "pass" if issue else "fail", f"#{issue}" if issue else
              (f"template placeholder still in the draft: {issue_placeholder(draft_text)!r}" if issue_placeholder(draft_text)
               else "no 'Fixes #N' / 'Related issue: #N' / issue URL in the draft (a bare #N doesn't count)")),
        tests_touched(paths),
        api_docs_touched(files),
        changelog(repo, paths),
        commit_style(repo, base, subjects),
        dco(repo, base),
        _item("no formatting-only churn", "fail" if fmt else "pass", f"whitespace-only hunks: {fmt[:5]}" if fmt else "none"),
        size(project, files),
        _item("issue still unclaimed", "na", "offline") if offline else unclaimed(repo, issue, me),
    ]
    return {"draft": draft_path, "issue": issue, "items": items,
            "ready": not any(i["status"] == "fail" for i in items)}
