"""Deterministic 'ready to submit?' checklist. Each item: {item, status: pass|fail|warn|na, evidence}."""
import glob, os, re, subprocess, time
from . import util
from .diff import formatting_only_hunks, parse as parse_diff
from .util import CODE_EXT_RX, ISSUE_KW, TEST_PATH_RX, gh_json, git, project_dir, read_json, upstream_slug, write_json

# Where GitHub looks for a PR template, in this order; the file name is matched case-insensitively, as GitHub does.
TEMPLATE_DIRS = (".github", "", "docs")
TEMPLATE_NAME = "pull_request_template.md"
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
    title, start, preamble, title_line = "", 0, [], None
    if title_at is not None:
        stop = body_at if body_at is not None else end
        val = next((i for i in range(title_at + 1, stop) if lines[i].strip()), None)
        if val is not None and not lines[val].startswith("#"):
            title = lines[val].strip().strip("`").strip()
            start, title_line = val + 1, val + 1
        else:
            start = title_at + 1
        preamble = lines[:title_at]
    elif body_at is None and lines and re.match(r"^#\s+\S", lines[0]):
        title, start, title_line = lines[0][1:].strip(), 1, 1
    if body_at is not None:
        preamble, start = lines[:body_at], body_at + 1
    body = "\n".join(lines[start:end])
    lead = next((k for k, t in enumerate(lines[start:end]) if t), end - start)   # blank lines the strip below drops
    # a trailing horizontal rule usually separated the body from the notes
    body = re.sub(r"(\n\s*(-{3,}|\*{3,}|_{3,})\s*)+\s*$", "", "\n" + body).strip("\n")
    rest = lines[end + 1:] if end < len(lines) and NOTES_MARKER_RX.match(lines[end]) else lines[end:]
    notes = "\n\n".join(x for x in ("\n".join(preamble).strip("\n"), "\n".join(rest).strip("\n")) if x)
    return {"title": title, "body": body, "notes": notes, "notes_line": end + 1 if end < len(lines) else None,
            "title_line": title_line, "body_line": start + lead + 1}


def draft_file_line(text, n):
    """The file line of line n of submitted_text(text): findings are written against the submitted text, but cite
    the draft file, where a `## Title` / `## Body` layout puts the same line further down."""
    d = split_draft(text)
    if d["title"]:
        if n <= 2:                                     # the title, or the blank line submitted_text puts after it
            return d["title_line"]
        n -= 2
    return d["body_line"] + max(n, 1) - 1


def submitted_text(text):
    """The title (as a plain line, so it doesn't count as a body heading) and body as they would be submitted."""
    d = split_draft(text)
    return (d["title"] + "\n\n" if d["title"] else "") + d["body"]


def _dir_entries(repo, d):
    """Names in directory `d` (relative, "" = root): on disk plus tracked in HEAD. A sparse checkout leaves tracked
    files off disk (supabase/supabase's clone had no .github/ at all), and GitHub still uses them."""
    names = set()
    try:
        names.update(os.listdir(os.path.join(repo, d) if d else repo))
    except OSError:
        pass
    out = git(repo, "ls-tree", "--name-only", "-z", "HEAD", "--", d + "/" if d else ".", check=False)
    names.update(n.rsplit("/", 1)[-1] for n in out.split("\0") if n)
    return names


def _read_tracked(repo, rel):
    p = os.path.join(repo, rel)
    if os.path.isfile(p):
        return open(p, errors="replace").read()
    # "./" makes the path relative to `repo`, like ls-tree above, when `repo` is below the work-tree root
    r = subprocess.run(["git", "-C", repo, "show", "HEAD:./" + rel], capture_output=True)
    return r.stdout.decode(errors="replace") if r.returncode == 0 else None


def template_text(repo):
    """-> (relative path, raw text) of the repo's PR template, or (None, "")."""
    tried = []
    for d in TEMPLATE_DIRS:
        tried += [(d, n) for n in sorted(_dir_entries(repo, d)) if n.lower() == TEMPLATE_NAME]
    # Multiple-template form: .github/PULL_REQUEST_TEMPLATE/*.md (only used via ?template=, so it comes last).
    for sub in sorted(n for n in _dir_entries(repo, ".github") if n.lower() == "pull_request_template"):
        tried += [(".github/" + sub, n) for n in sorted(_dir_entries(repo, ".github/" + sub))
                  if n.lower() == TEMPLATE_NAME]
    for d, n in tried:
        rel = f"{d}/{n}" if d else n
        raw = _read_tracked(repo, rel)
        if raw is not None:
            return rel, raw
    return None, ""


def template_headings(repo):
    t, raw = template_text(repo)
    if not t:
        return None, []
    txt = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    return t, [h.strip("# ").strip() for h in txt.split("\n") if re.match(r"^#{1,4}\s+\S", h)]


def check_draft(repo, draft_text):
    tpl, heads = template_headings(repo)
    if not draft_text:
        return _item("PR description drafted", "fail", "no PR_DRAFT.md found next to the change")
    if not tpl:
        ok = len(draft_text) > 200
        return _item("PR description drafted", "pass" if ok else "warn",
                     f"no PR template in repo; draft is {len(draft_text)} chars")
    if not heads:                                  # e.g. itsdangerous's checklist-only template: "all 0 sections present"
        ok = len(draft_text) > 200
        return _item("PR description drafted", "pass" if ok else "warn",
                     f"{tpl} has no section headings to check; draft is {len(draft_text)} chars")
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


# CI matrix values that track the newest release; the local install is usually that one too.
FLOATING_VERSIONS = {"latest", "stable", "current", "lts", "*", "x"}


def _matrix_scalars(raw):
    vals = []
    for v in raw:
        v = v.strip().strip("'\"").strip()
        if v and "${{" not in v:
            vals.append(v)
    return vals


def matrix_axes(text):
    """{axis: [values]} from every `matrix:` block of a workflow file. Reads flow lists (`k: [a, b]`) and block lists
    (`k:` then `- a`, indented or not), including a flow list split over lines; `include`/`exclude` entries and `${{ }}` expressions are skipped. No YAML dependency."""
    axes, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        m = re.match(r"^(\s*)matrix:\s*(#.*)?$", lines[i])
        i += 1
        if not m:
            continue
        ind, key_ind, cur = len(m.group(1)), None, None
        while i < len(lines):
            ln = lines[i]
            s = ln.strip()
            if not s or s.startswith("#"):
                i += 1
                continue
            li = len(ln) - len(ln.lstrip())
            if li <= ind:
                break
            if s.startswith("- "):
                # a block-list item, indented under its key or at the key's own indent (indentless YAML)
                if cur and li >= key_ind:
                    axes.setdefault(cur, []).extend(_matrix_scalars([re.sub(r"\s+#.*$", "", s[2:])]))
                i += 1
                continue
            key_ind = li if key_ind is None else key_ind
            if li == key_ind:
                cur = None
                km = re.match(r"^([\w.-]+)\s*:\s*(.*?)\s*(?:#.*)?$", s)
                if km and km.group(1) not in ("include", "exclude"):
                    k, v = km.groups()
                    while v.startswith("[") and "]" not in v and i + 1 < len(lines):  # flow list over several lines
                        nxt = lines[i + 1]
                        if nxt.strip() and not nxt.lstrip().startswith("#") and len(nxt) - len(nxt.lstrip()) <= ind:
                            break  # unterminated: never read past the matrix block
                        i += 1
                        v += " " + re.sub(r"(^|\s+)#.*$", "", lines[i].strip())  # also a comment-only line
                    if v.startswith("[") and v.endswith("]"):
                        axes.setdefault(k, []).extend(_matrix_scalars(v[1:-1].split(",")))
                    elif not v:
                        cur = k
            i += 1
    return axes


def _norm_dep(name):
    return re.sub(r"[-_.]+", "-", name.lower())


def declared_deps(repo):
    """{normalized name: (ecosystem, declared name)} from package.json and Python requirement files."""
    deps = {}
    pkg = read_json(os.path.join(repo, "package.json"), {}) or {}
    for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name in (pkg.get(k) or {}) if isinstance(pkg.get(k), dict) else ():
            deps[_norm_dep(name)] = ("npm", name)
    reqs = []
    for p in glob.glob(os.path.join(repo, "requirements*.txt")):
        with open(p, errors="replace") as fh:
            reqs += fh.read().splitlines()
    pyproject = os.path.join(repo, "pyproject.toml")
    if os.path.exists(pyproject):
        try:
            import tomllib
            with open(pyproject, "rb") as fh:
                proj = (tomllib.load(fh).get("project") or {})
            reqs += list(proj.get("dependencies") or [])
            for group in (proj.get("optional-dependencies") or {}).values():
                reqs += list(group or [])
        except Exception:  # Python 3.10 has no tomllib; a malformed file is not this check's business
            pass
    for r in reqs:
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", r)
        if m and not r.lstrip().startswith(("#", "-")):
            deps.setdefault(_norm_dep(m.group(1)), ("pypi", m.group(1)))
    return deps


# Axes that vary the runtime or the platform, never a package, even when a package shares the name.
RUNTIME_AXES = {"node", "nodejs", "python", "py", "ruby", "go", "golang", "java", "jdk", "rust", "toolchain", "php",
                "dotnet", "deno", "bun", "os", "platform", "arch", "compiler", "cc"}


def _axis_dep(axis, deps):
    """The declared dependency a matrix axis varies ("three-version" → three, "django" → Django), or None. Exact
    names only: a suffix match would read `node-version` as @sentry/node."""
    a = _norm_dep(re.sub(r"[-_]versions?$", "", axis, flags=re.I))
    return None if a in RUNTIME_AXES else deps.get(a)


def installed_version(repo, eco, name):
    if eco == "npm":
        return (read_json(os.path.join(repo, "node_modules", name, "package.json"), {}) or {}).get("version")
    want = _norm_dep(name)
    for venv in (".venv", "venv", "env"):
        for d in glob.glob(os.path.join(repo, venv, "lib", "python*", "site-packages", "*.dist-info")):
            stem = os.path.basename(d)[:-len(".dist-info")]
            dist, _, ver = stem.rpartition("-")
            if dist and _norm_dep(dist) == want:
                return ver
    return None


def _version_covered(value, installed):
    v = value.lower().lstrip("^~=v").rstrip(".x*").rstrip(".")
    if value.lower() in FLOATING_VERSIONS:
        return True
    return bool(installed) and (installed == v or installed.startswith(v + "."))


def ci_matrix(repo, paths):
    """CI that runs the tests against several versions of a dependency (three-mesh-bvh: three 0.159.0, 0.168.0,
    latest) catches what local checks miss, since those only ran the one installed version. three-mesh-bvh #959 was
    GREEN locally on three 0.185 and failed CI on 0.159. Names the untested versions and how to try one."""
    name = "CI dependency matrix tried locally"
    if not any(CODE_EXT_RX.search(p) for p in paths):
        return _item(name, "na", "no code files changed")
    deps, untested, seen, matched = declared_deps(repo), [], set(), set()
    for wf in sorted(glob.glob(os.path.join(repo, ".github", "workflows", "*.y*ml"))):
        try:
            with open(wf, errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for axis, values in matrix_axes(text).items():
            dep = _axis_dep(axis, deps)
            if not dep or len(values) < 2:
                continue
            eco, dname = dep
            matched.add(dname)
            have = installed_version(repo, eco, dname)
            for v in values:
                if (dname, v) not in seen and not _version_covered(v, have):
                    seen.add((dname, v))
                    untested.append((os.path.relpath(wf, repo), eco, dname, v, have))
    if not matched:
        return _item(name, "na", "no CI matrix over a declared dependency")
    if not untested:
        return _item(name, "pass", f"every CI matrix version of {', '.join(sorted(matched))} matches the installed one")
    vers = ", ".join(f"{d} {ver}" for _, _, d, ver, _ in untested[:6])
    oldest = {}  # per dependency, the lowest untested version (matrices are often listed newest first)
    for wf, eco, dname, v, have in untested:
        if dname not in oldest or _version_key(v) < _version_key(oldest[dname][2]):
            oldest[dname] = (wf, eco, v, have)
    wf, _, dname, _, have = untested[0]
    ran = (f"local checks used {dname} {have}" if have else
           f"there's no local install of {dname} here, so check which version the tests ran on")
    cmds = "; ".join(f"`npm install --no-save {d}@{v}`" if eco == "npm" else f"`pip install '{d}=={v}'`"
                     for d, (_, eco, v, _) in list(oldest.items())[:3])
    return _item(name, "warn", f"{wf} tests {vers}; {ran}. Try the oldest before submitting ({cmds}), re-run the "
                 f"tests, then restore the lockfile install. Advisory: this never blocks, and it stays until the "
                 f"installed version matches")


def _version_key(v):
    return tuple(int(n) for n in re.findall(r"\d+", v)) or (float("inf"),)


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
    """Judged by the lines outside test files, against the same count over merged PRs: tests a fix ships with are
    not what makes it big to review (umu's 61-line drafts were 57 lines of tests). Replayed on the 90 stored upstream
    rounds that warned or failed, on the same PR sample: 24 eased, 7 tightened (colyseus's merged PRs are test-heavy
    too), 59 unchanged."""
    meta = read_json(os.path.join(project_dir(project), "meta.json"), {}) or {}
    count = lambda fs: sum(1 for f in fs for h in f["hunks"] for k, *_ in h["lines"] if k in "+-")
    n = count(files)
    in_tests = count(f for f in files if TEST_PATH_RX.search(f["path"]))
    med, med_src = meta.get("median_merged_pr_lines"), meta.get("median_merged_pr_nontest_lines")
    if med_src:
        st = "fail" if n - in_tests > 3 * med_src else "warn" if n - in_tests > 1.5 * med_src else "pass"
        return _item("size vs project norm", st, f"{n - in_tests} changed lines outside tests vs median merged PR "
                                                  f"{med_src}" + (f" ({in_tests} more in tests)" if in_tests else ""))
    if not med:
        return _item("size vs project norm", "na", f"{n} changed lines; run `crucible learn` for the project median")
    st = "fail" if n > 3 * med else "warn" if n > 1.5 * med else "pass"
    note = f" ({in_tests} of them in tests; re-run `crucible learn` to judge the lines outside tests)" if in_tests else ""
    return _item("size vs project norm", st, f"{n} changed lines vs median merged PR {med}{note}")


def learned_data(project):
    """Readiness reads the size norm from meta.json and the style checks read style.json. Both keep whatever the
    `crucible learn` of their day computed, so a fixed `learn` bug lives on in old files until `learn` re-runs."""
    name = "learned project data is current"
    paths = {f: os.path.join(project_dir(project), f) for f in ("meta.json", "style.json")}
    found = {f: read_json(p, {}) for f, p in paths.items() if os.path.exists(p)}
    if not found:
        return _item(name, "na", "not learned yet; run `crucible learn` for the project's size and style norms")
    stale = []
    for f, d in found.items():
        d = d if isinstance(d, dict) else {}           # unreadable: re-learning is the fix either way
        missed = [what for v, (what, affects) in sorted(util.LEARN_CHANGES.items())
                  if v > util.learn_version(d) and f in affects]
        if not missed:
            continue
        when = f", learned {d['learned']}" if d.get("learned") else ""
        if type(d.get("learn_version")) is int:
            stale.append(f"{f} (v{d['learn_version']}{when}) is missing: " + "; ".join(missed))
        else:  # written before the stamp, by v1 or v2, so it may already have the v2 fix
            stale.append(f"{f} (unstamped{when}) may be missing: " + "; ".join(missed))
    if not stale:
        return _item(name, "pass", f"{' and '.join(found)} up to date with `crucible learn` v{util.LEARN_VERSION}")
    return _item(name, "warn", " · ".join(stale) + ". Re-run `crucible learn` so these checks use the corrected numbers")


def is_me(login, me):
    """GitHub logins are case-insensitive: CRUCIBLE_GH_USER=Alice is the assignee `alice`."""
    return bool(me and login) and login.lower() == me.lower()


UNKNOWN_ME = " (crucible couldn't tell which GitHub account is yours; if that's you, set CRUCIBLE_GH_USER)"


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
    who = [a["login"] for a in data.get("assignees") or [] if not is_me(a.get("login"), me)]
    if who:
        probs.append(f"assigned to {who}")
    tl = gh_json(f"repos/{slug}/issues/{issue}/timeline?per_page=100") or []
    prs = []
    for ev in tl if isinstance(tl, list) else []:
        src = (ev.get("source") or {}).get("issue") or {}
        if ev.get("event") == "cross-referenced" and src.get("pull_request") and src.get("state") == "open" \
                and not is_me((src.get("user") or {}).get("login"), me):
            prs.append(src.get("html_url"))
    if prs:
        probs.append(f"open PRs already reference it: {prs[:3]}")
    if probs and not me and (who or prs):
        probs[-1] += UNKNOWN_ME
    return _item("issue still unclaimed", "fail" if probs else "pass",
                 "; ".join(probs) or f"{slug}#{issue} open, unassigned, no competing open PR")


# Files almost every PR touches; sharing one of them says nothing about two PRs changing the same code.
SHARED_FILE_RX = re.compile(r"(^|/)(CHANGELOG[^/]*|CHANGES[^/]*|HISTORY[^/]*|NEWS[^/]*|package(-lock)?\.json|"
                            r"npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|Cargo\.lock|poetry\.lock|"
                            r"uv\.lock|Pipfile\.lock|go\.sum|Gemfile\.lock|composer\.lock)$|^\.changeset/", re.I)
OPEN_PRS_QUERY = """query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){
 pullRequests(states:OPEN,first:100,after:$after,orderBy:{field:UPDATED_AT,direction:DESC}){
  totalCount pageInfo{hasNextPage endCursor}
  nodes{number url isDraft headRefOid author{login __typename} files(first:100){nodes{path}}}}}}"""
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
                        "head": n.get("headRefOid"),
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


FETCH_FAILED = "fetch failed"  # _pr_hunks: the API call itself failed (rate limit, network), unlike "no patch"
HUNK_CACHE_TTL = 7 * 86400  # a PR's diff is fixed by its head SHA; the TTL only bounds a retargeted base branch


def _hunk_cache_path(slug, number):
    return os.path.join(util.HOME, "cache", "pr-hunks", slug.replace("/", "__"), f"{int(number)}.json")


def _valid_hunks(hunks):
    """A cached {path: None | [[start, end], ...]} as _pr_hunks writes it; anything else (a hand edit) is a miss."""
    return isinstance(hunks, dict) and all(
        r is None or (isinstance(r, list) and all(isinstance(x, list) and len(x) == 2 and
                                                  all(type(v) is int for v in x) for x in r))
        for r in hunks.values())


def _pr_hunks(slug, number, head=None):
    """{path: [(start, end)] on the base side, 3 context lines included} for one PR, or FETCH_FAILED if the API call
    failed. A pure rename maps to []. Any other file GitHub sends without a patch (binary, mode-only, or a diff too
    large to show) maps to None: it can't be compared.

    With the PR's head SHA the result is cached (one file per PR, overwritten when the head moves), so later review
    rounds on a busy repo don't refetch up to OVERLAP_CANDIDATES patches over REST each time."""
    path = _hunk_cache_path(slug, number) if head else None
    if path:
        hit = read_json(path)
        hit = hit if isinstance(hit, dict) else {}
        at, hunks = hit.get("at"), hit.get("hunks")
        if hit.get("head") == head and isinstance(at, (int, float)) and time.time() - at < HUNK_CACHE_TTL \
                and _valid_hunks(hunks):
            return {f: (None if r is None else [tuple(x) for x in r]) for f, r in hunks.items()}
    data = gh_json(f"repos/{slug}/pulls/{number}/files?per_page=100")
    if not isinstance(data, list):
        return FETCH_FAILED
    out = {}
    for f in data:
        found = HUNK_RX.findall(f.get("patch") or "")
        # A pure rename has no lines to compare. A binary file also arrives with changes 0 and no patch, and a
        # mode-only change looks the same, so neither is assumed to be distant.
        if found or (f.get("status") == "renamed" and f.get("changes") == 0):
            out[f.get("filename")] = [(int(a), int(a) + max(int(n) if n else 1, 1) - 1) for a, n in found]
        else:
            out[f.get("filename")] = None
    if path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write_json(path, {"head": head, "at": time.time(), "hunks": out})
        except OSError:
            pass  # an unwritable cache only costs the refetch next round
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
        if pr["bot"] or is_me(pr["author"], me):
            continue
        same = sorted(set(ours).intersection(pr["paths"]))
        if same:
            cands.append((pr, same))
    # Most focused first: a 5-file PR sharing 2 of our files is likelier the same fix than a 100-file rewrite sharing 3.
    # The sort is stable, so ties keep the most recently updated first.
    cands.sort(key=lambda c: -len(c[1]) / max(len(c[0]["paths"]), 1))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        patches = list(ex.map(lambda c: _pr_hunks(slug, c[0]["number"], c[0].get("head")), cands[:OVERLAP_CANDIDATES]))
    hits, distant, unread, failed = [], [], [], []
    for (pr, same), hunks in zip(cands, patches):
        if hunks is FETCH_FAILED:
            failed.append(pr["number"])
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
    if failed:
        notes.append(f"{len(failed)} couldn't be fetched, the GitHub API call failed (rate limit or network; "
                     f"re-run later) ({nums(failed)})")
    if not hits:
        uncompared = unread or failed or len(cands) > OVERLAP_CANDIDATES
        return _item(name, "warn" if uncompared else "pass", "; ".join(notes))
    shown = "; ".join(f"#{pr['number']}{' (draft)' if pr['draft'] else ''} by {pr['author']} "
                      f"({len(meet)} of its {len(pr['paths'])} files): "
                      f"{', '.join(meet[:3])}{f' +{len(meet) - 3} more' if len(meet) > 3 else ''}" for pr, meet in hits[:5])
    more = f"; +{len(hits) - 5} more" if len(hits) > 5 else ""
    return _item(name, "warn", f"{shown}{more}. Read them before submitting: same code, possibly the same fix "
                               f"({'; '.join(notes)})" + ("" if me else UNKNOWN_ME))


def commit_attribution(repo, base):
    """AI co-author trailers / "Generated with ..." lines in the branch's commits. A warning, not a failure: some
    projects ask for AI disclosure, and then the trailer may be exactly what they want (check their policy)."""
    from .style import attribution_lines
    name = "no AI tool attribution in commits"
    hits = []
    for b in git(repo, "log", "--format=%H%x00%B%x01", f"{base}..HEAD").split("\x01"):
        sha, _, msg = b.strip().partition("\x00")
        found = attribution_lines(msg)
        if sha and found:
            hits.append(f"{sha[:8]}: {found[0][:70]}")
    if not hits:
        return _item(name, "pass", "none")
    return _item(name, "warn", f"{len(hits)} commit(s): {hits[:3]}. Drop the line(s) (`git commit --amend` / rebase) "
                 "unless the project's contribution policy asks for AI disclosure")


# Files an author keeps a PR body in. polish's output (*.polished.md, *.polish-notes.md) is newer by design: not a rival.
# The keyword may be followed by any separator or digit (PR_BODY.v2, PR_BODY_v2, PR_DRAFT2), not by more letters.
BODY_FILE_RX = re.compile(r"^(pr|pull[_-]?request)[_-]?(draft|body|description|desc)(?![a-z]).*\.md$", re.I)


def newer_draft(repo, draft_path):
    """Is the judged draft the newest PR body here? On Lutris #7004 the review judged a PR_DRAFT.md from Nov 4 while
    the body about to be submitted was PR_BODY.v2.md from Nov 7, so the description findings were about the wrong
    text. Looks next to the draft and in the repo root for untracked PR_DRAFT*/PR_BODY*/PR_DESCRIPTION*.md files
    edited later than it whose text differs from what it submits (the body copied out of it is fine). Advisory: the
    author may keep old versions on purpose."""
    name = "judged draft is the newest PR body"
    if not draft_path:
        return _item(name, "na", "no draft")
    try:
        mine = os.path.getmtime(draft_path)
    except OSError:
        return _item(name, "na", "draft not readable")
    tracked = set(git(repo, "ls-files", check=False).split("\n"))
    norm = lambda t: " ".join(t.split())
    raw = open(draft_path, errors="replace").read()
    # the draft itself (a plain `cp`), what it submits (title + body), or the body alone (the title goes in
    # `gh pr create --title`)
    copies = {norm(raw), norm(submitted_text(raw)), norm(split_draft(raw)["body"])}
    seen, newer = set(), []
    for d in {os.path.dirname(os.path.abspath(draft_path)), os.path.abspath(repo)}:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if not BODY_FILE_RX.match(n) or "polish" in n.lower() or p in seen or not os.path.isfile(p):
                continue
            seen.add(p)
            if os.path.samefile(p, draft_path) or os.path.relpath(p, repo) in tracked:
                continue
            t = os.path.getmtime(p)
            if t <= mine + 60:                         # a minute's slack: files written together by one edit
                continue
            if norm(open(p, errors="replace").read()) in copies:   # the reviewed body copied out (open-pr.sh
                continue                                              # submits PR_BODY.md): not a rival
            newer.append((t, p))
    if not newer:
        return _item(name, "pass", f"no other PR body file here is newer than {os.path.basename(draft_path)} "
                     "with different text")
    newer.sort(reverse=True)
    stamp = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t))
    rel = lambda p: os.path.relpath(p, repo) if os.path.abspath(p).startswith(os.path.abspath(repo) + os.sep) else p
    t, p = newer[0]
    more = f" (and {len(newer) - 1} more)" if len(newer) > 1 else ""
    return _item(name, "warn", f"{rel(p)} ({stamp(t)}){more} is newer than the judged {rel(draft_path)} "
                 f"({stamp(mine)}) and says something else. If that's the body you'll submit, re-run with "
                 f"`--draft {rel(p)}` or copy it over {os.path.basename(draft_path)}: the description findings are "
                 "about the judged file only")


REMOTE_TIMEOUT = 30


def _remote_git(repo, *args):
    """A git call that talks to a remote: no credential or host-key prompt, and it gives up after REMOTE_TIMEOUT s.
    Returns stdout, or None on any failure (unreachable, auth, timeout). ssh ignores GIT_TERMINAL_PROMPT and asks for
    a passphrase or an unknown host key on /dev/tty, so the child gets its own session with no controlling terminal;
    ssh then falls back to SSH_ASKPASS (`true`) and fails at once (self-review CR-3f1c7fbd)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true", SSH_ASKPASS="true")
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=env, timeout=REMOTE_TIMEOUT,
                           stdin=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def base_moved(repo, base_ref, base):
    """Has the base branch moved on the remote since the merge-base, in files this change touches? crucible diffs
    against the local remote-tracking ref and never fetches, so commits that landed upstream after the last fetch
    were invisible: the change is judged against code that no longer exists (BLAZE's 11-08 "stale base" class: 0 of
    4 caught). Reads the remote tip with `git ls-remote`; if that commit isn't local, fetches it by URL, which updates
    no ref (FETCH_HEAD included), so the checkout and its tracking refs stay as they were. No model call, no
    execution. Only a remote-tracking base (`<remote>/<branch>`) can be checked; a local branch or a SHA is "na".
    The fetch does add the tip's objects to the clone (no ref points at them; gc prunes them) and skips submodules.

    Both sides are listed with `-z --no-renames`: a quoted path (space, non-ASCII) would match nothing, and a file the
    change renamed must still meet an upstream edit to its old name (self-review CR-8dec074c)."""
    name = "base branch hasn't moved under the change"
    remotes = git(repo, "remote", check=False).split()
    remote = next((r for r in sorted(remotes, key=len, reverse=True) if (base_ref or "").startswith(r + "/")), None)
    if not remote:
        return _item(name, "na", f"base {base_ref or base[:10]} is not a remote-tracking branch")
    branch = base_ref[len(remote) + 1:]
    out = _remote_git(repo, "ls-remote", "--heads", remote, f"refs/heads/{branch}")
    if out is None:
        return _item(name, "warn", f"could not reach {remote} to read {branch}'s tip (offline, auth or timeout); "
                     f"the review is against the last fetch of {base_ref}")
    tip = next((ln.split()[0] for ln in out.splitlines() if ln.endswith(f"\trefs/heads/{branch}")), None)
    if not tip:
        return _item(name, "warn", f"{remote} has no branch {branch!r} any more; the base may have been renamed")
    if tip == base:
        return _item(name, "pass", f"{remote}'s {branch} is still at the merge-base {base[:10]}")
    if not util.ref_exists(repo, tip):
        url = git(repo, "remote", "get-url", remote, check=False)
        # by URL, not by remote name: a named fetch also moves refs/remotes/<remote>/<branch> as a side effect
        if not url or _remote_git(repo, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head",
                                  "--no-recurse-submodules", url,
                                  f"refs/heads/{branch}") is None or not util.ref_exists(repo, tip):
            return _item(name, "warn", f"{remote}'s {branch} is at {tip[:10]}, not the merge-base {base[:10]}, and "
                         "that commit couldn't be fetched to compare. `git fetch` and re-run")
    if subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", base, tip],
                      capture_output=True).returncode != 0:
        return _item(name, "warn", f"{remote}'s {branch} was rewritten: the merge-base {base[:10]} is no longer on it "
                     f"(tip {tip[:10]}). Rebase onto the new {base_ref} and re-run")
    n = git(repo, "rev-list", "--count", f"{base}..{tip}", check=False) or "?"
    names = lambda a, b: set(git(repo, "diff", "--name-only", "-z", "--no-renames", a, b, check=False).split("\0")) - {""}
    both = sorted(names(base, tip) & names(base, "HEAD"))
    where = f"{n} commit(s) landed on {remote}'s {branch} since the merge-base {base[:10]} (tip {tip[:10]})"
    if not both:
        return _item(name, "pass", f"{where}, none in the files this change touches")
    shown = ", ".join(both[:5]) + (f" +{len(both) - 5} more" if len(both) > 5 else "")
    return _item(name, "warn", f"{where}; {len(both)} of them change files this change touches too: {shown}. The review "
                 f"judged the old base: `git fetch {remote} && git rebase {base_ref}`, then re-run (and re-measure "
                 "any numbers quoted in the draft)")


MIGRATION_DIR_RX = re.compile(r"(?:^|/)(?:migrations?|migrate|schema_migrations)(?:/|$)", re.I)
# a version is every leading digit group: Rails/Supabase 20261103000000_, Django 0001_, golang-migrate 000001_,
# Laravel/Phinx 2026_11_05_000000_ (four groups, not the year alone), Flyway V1_1__ (1.1)
MIGRATION_VER_RX = re.compile(r"^V?(\d+(?:[._]\d+)*)(?=__|[_.\-][^\d_.\-]|\.)")
MIGRATION_EXT = (".sql", ".py", ".rb", ".js", ".ts", ".mjs", ".cjs", ".php", ".go", ".java", ".kt", ".exs", ".cql")


def _migration_version(name, source=True):
    """('2026_11_05_000000_x.php') -> (timestamp?, (2026, 11, 5, 0), '2026_11_05_000000'). Versions compare as dotted
    numbers padded with zeros (Flyway 1.2 < 1.10 < 2), but a timestamp (first group of 8+ digits) never compares with a
    short sequence. None for anything that isn't a numbered migration (source=True: a source file; False: a folder
    name, as in Prisma's migrations/<version>_<name>/migration.sql)."""
    m = MIGRATION_VER_RX.match(name)
    if not m or (source and not name.lower().endswith(MIGRATION_EXT)):
        return None
    groups = re.split(r"[._]", m.group(1))
    return len(groups[0]) >= 8, tuple(int(g) for g in groups), m.group(1)


def _pad(v, n):
    return v + (0,) * (n - len(v))


def _migration_entry(path):
    """(directory to list, name in it, version, source) for a new migration file, or None. source is False for
    Prisma, which keeps the version in the folder: prisma/migrations/20261101_x/migration.sql is compared with its
    sibling folders only, never with plain files next to them."""
    d, n = os.path.split(path)
    v = _migration_version(n)
    if v and MIGRATION_DIR_RX.search(path):
        return d, n, v, True
    up, folder = os.path.split(d)
    v = _migration_version(folder, source=False)
    if v and n == "migration.sql" and MIGRATION_DIR_RX.search(up + "/"):
        return up, folder, v, False
    return None


def migration_order(repo, base, files, base_ref=None):
    """Does a new migration sort AFTER every migration the base already has? A version lower than one already applied
    runs out of order on a fresh replay (BLAZE escape 2026-11-10: GREEN on the diff, failed on replay). Covers the
    timestamp/sequence-prefixed layouts (Rails db/migrate, Supabase/golang-migrate migrations/, Flyway V1_2__,
    Django 0001_, Laravel 2026_11_05_000000_, Prisma migrations/<version>_x/migration.sql). Source files only, so
    numbered docs in a migrations folder don't count. Compares with the same directory on the merge-base and the
    local tracking ref (which can be ahead of it after a fetch). No model call, no execution."""
    name = "new migrations sort after the existing ones"
    new = [(f["path"], e) for f in files if f.get("added") and not f.get("deleted")
           for e in [_migration_entry(f["path"])] if e]
    if not new:
        return _item(name, "na", "no new migration file")
    refs = [r for r in dict.fromkeys([base, base_ref]) if r and util.ref_exists(repo, r)]
    lower, same, ok = [], [], []
    for path, (d, own, (stamp, mine, label), source) in new:
        existing = {}                            # version ints -> (name, ref); the merge-base wins a tie with base_ref
        for r in refs:
            out = git(repo, "ls-tree", "--name-only", "-z", *([] if source else ["-d"]), f"{r}:{d}" if d else r,
                      check=False) or ""
            for n in out.split("\0"):
                v = _migration_version(n, source)
                if v and v[0] == stamp and n != own:          # base_ref may already hold this very file
                    existing.setdefault(v[1], (n, r))
        if not existing:
            ok.append(path); continue
        w = max(len(mine), *(len(k) for k in existing))
        top = max(existing, key=lambda k: _pad(k, w))
        if _pad(mine, w) < _pad(top, w):
            lower.append(f"{path} ({label}) < {existing[top][0]} on {existing[top][1][:12]}")
        elif any(_pad(k, w) == _pad(mine, w) for k in existing):
            k = next(k for k in existing if _pad(k, w) == _pad(mine, w))
            same.append(f"{path} reuses version {label} ({existing[k][0]})")
        else:
            ok.append(path)
    if lower:
        return _item(name, "fail", "lower than a migration the base already has, so a fresh replay runs it out of "
                     "order: " + "; ".join(lower[:3]) + ". Renumber it after the newest one (and re-run the migrations)")
    if same:
        return _item(name, "warn", "; ".join(same[:3]) + ". Two migrations with one version: the runner may skip or "
                     "reject one; renumber")
    return _item(name, "pass", f"{len(ok)} new migration(s), each after the newest one on the base")



# Definitions a change adds, by language. Only the line that defines the name counts: a call site, a comment or a
# string that mentions CREATE FUNCTION does not. SQL functions, procedures and views live in one namespace per
# database schema, so two definitions collide wherever the files are; a trigger is named per table (Postgres), and a
# function or procedure by its name and argument types, so overloads don't collide. Go collides per package
# (directory); Python, JS/TS and Ruby per file, top-level definitions only (a method name is per class, and the class
# isn't on the line).
SQL_DEF_RX = re.compile(r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:TEMP|TEMPORARY|RECURSIVE|CONSTRAINT|MATERIALIZED)\s+)*"
                        r"(FUNCTION|PROCEDURE|VIEW|TRIGGER)\s+(?:IF\s+NOT\s+EXISTS\s+)?((?:\"[^\"]+\"|[\w$]+)"
                        r"(?:\.(?:\"[^\"]+\"|[\w$]+))?)", re.I)
CODE_DEF_RX = {
    ".py": re.compile(r"^(?:async\s+def|def|class)\s+(\w+)"),                      # top level only (column 0)
    ".rb": re.compile(r"^def\s+(?:self\.)?([\w?!=]+)"),                              # top level only (column 0)
    ".go": re.compile(r"^func\s+(?:\(\s*\w*\s*\*?\s*(\w+)(?:\[[^\]]*\])?\s*\)\s*)?(\w+)"),
    ".js": re.compile(r"^(?:export\s+(?:default\s+)?)?(?:(?:async\s+)?function\s*\*?\s*|(?:abstract\s+)?class\s+)(\w+)"
                      r"|^export\s+(?:const|let|var)\s+(\w+)"),
}
for _e in (".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"):
    CODE_DEF_RX[_e] = CODE_DEF_RX[".js"]
# files whose added lines can hold executable DDL: .sql itself, and the languages migrations are written in
SQL_HOST_EXT = MIGRATION_EXT + (".psql", ".pgsql", ".plpgsql", ".ddl")
# constructors and test fixtures are defined everywhere under the same name; dunder names are protocol, not symbols
GENERIC_DEFS = {"initialize", "constructor", "setup", "teardown", "setUp", "tearDown", "init", "main", "default"}


SQL_ON_RX = re.compile(r"\bON\s+((?:\"[^\"]+\"|[\w$]+)(?:\.(?:\"[^\"]+\"|[\w$]+))?)", re.I)


def _sql_name(raw):
    name = raw.replace('"', "").lower()
    return name[len("public."):] if name.startswith("public.") else name           # Postgres' default schema


def _sql_signature(rest):
    """'(n text, OUT x int, y varchar(10) DEFAULT 1) RETURNS ...' -> 'text,varchar'. The type of each IN argument is
    taken as its last word (so a parameter name or none gives the same type; a multi-word type compares by its last
    word). None when the argument list doesn't close on this line: then the signature is unknown and matches any."""
    rest = rest.lstrip()
    if not rest.startswith("("):
        return None
    depth, args, cur = 0, [], ""
    for ch in rest:
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append(cur)
                break
        if ch == "," and depth == 1:
            args.append(cur); cur = ""
        elif depth >= 1:
            cur += ch
    else:
        return None
    out = []
    for a in args:
        a = re.split(r"\s+default\s+|\s*=", a.strip().lower(), maxsplit=1)[0]
        a = re.sub(r"\([^)]*\)", "", a).split()
        if not a or a[0] in ("out",):
            continue
        out.append(a[-1])
    return ",".join(out)


def _definitions(path, text):
    """[(key, label)] for the symbols one added line defines. key = (lang, scope, name, signature), signature None
    unless it is a SQL function or procedure whose argument list closes on the line; see _collides."""
    out = []
    ext = os.path.splitext(path)[1].lower()
    m = SQL_DEF_RX.match(text) if ext in SQL_HOST_EXT else None    # docs and READMEs quote DDL; they define nothing
    if m:
        kind, name, sig = m.group(1).lower(), _sql_name(m.group(2)), None
        if len(name.rsplit(".", 1)[-1]) < 4:
            return out
        if kind == "trigger":
            on = SQL_ON_RX.search(text, m.end())
            if not on:
                return out                                  # the table is on a later line: can't tell which trigger
            name = f"{name} on {_sql_name(on.group(1))}"
        elif kind in ("function", "procedure"):
            sig = _sql_signature(text[m.end():])
        shown = f"SQL {kind} {name}" + (f"({sig})" if sig is not None else "")
        out.append((("sql", kind, name, sig), shown))
        return out
    rx = CODE_DEF_RX.get(ext)
    m = rx.match(text) if rx else None
    if not m:
        return out
    if ext == ".go":
        recv, name = m.group(1), m.group(2)
        scope, shown = os.path.dirname(path) or ".", (f"{recv}.{name}" if recv else name)
    else:
        recv, name = None, next(g for g in m.groups() if g)
        scope, shown = path, name
    if len(name) < 4 or name in GENERIC_DEFS or (name.startswith("__") and name.endswith("__")):
        return out
    where = f"package {scope}" if ext == ".go" else scope
    out.append(((ext if ext == ".go" else "file", scope, shown, None), f"{shown} in {where}"))
    return out


def _collides(a, b):
    """Same symbol: same language, scope and name, and for SQL functions the same argument types when both are
    known (an overload is a different function)."""
    return tuple(a[:3]) == tuple(b[:3]) and (a[3] is None or b[3] is None or a[3] == b[3])


def _added_defs(files):
    """{key: label} for every definition on an added line of a parsed diff (crucible.diff.parse)."""
    out = {}
    for f in files:
        if not f.get("path") or f.get("deleted"):
            continue
        for h in f.get("hunks") or []:
            for kind, text, *_ in h["lines"]:
                if kind == "+":
                    for k, label in _definitions(f["path"], text):
                        out.setdefault(k, label)
    return out


def _patch_defs(path, patch):
    """Definitions on the added lines of one GitHub file patch."""
    return [k for ln in (patch or "").splitlines() if ln.startswith("+") and not ln.startswith("+++")
            for k, _ in _definitions(path, ln[1:])]


PR_FILES_PAGE = 100   # one REST page; a full page means the PR may have more files than were read


def _defs_cache_path(slug, number):
    return os.path.join(util.HOME, "cache", "pr-defs", slug.replace("/", "__"), f"{int(number)}.json")


def _valid_defs(got):
    return isinstance(got, dict) and isinstance(got.get("defs"), list) and isinstance(got.get("unread"), list) \
        and isinstance(got.get("cut"), bool) and all(isinstance(p, str) for p in got["unread"]) \
        and all(isinstance(k, list) and len(k) == 4 and all(isinstance(x, str) for x in k[:3])
                and (k[3] is None or isinstance(k[3], str)) for k in got["defs"])


def _pr_defs(slug, number, head=None):
    """{"defs": [key], "unread": [paths sent without a patch], "cut": the file list may go on past one page} for a
    PR, or FETCH_FAILED. Cached per head SHA like _pr_hunks."""
    path = _defs_cache_path(slug, number) if head else None
    if path:
        hit = read_json(path)
        hit = hit if isinstance(hit, dict) else {}
        at, got = hit.get("at"), hit.get("got")
        if hit.get("head") == head and isinstance(at, (int, float)) and time.time() - at < HUNK_CACHE_TTL \
                and _valid_defs(got):
            return {**got, "defs": [tuple(k) for k in got["defs"]]}
    data = gh_json(f"repos/{slug}/pulls/{number}/files?per_page={PR_FILES_PAGE}")
    if not isinstance(data, list):
        return FETCH_FAILED
    got = {"defs": [k for f in data for k in _patch_defs(f.get("filename") or "", f.get("patch"))],
           "unread": [f.get("filename") or "" for f in data if not f.get("patch") and f.get("changes")],
           "cut": len(data) >= PR_FILES_PAGE}
    if path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write_json(path, {"head": head, "at": time.time(), "got": {**got, "defs": [list(k) for k in got["defs"]]}})
        except OSError:
            pass
    return got


def _could_define(pr_paths, key):
    """Can a PR touching these paths define this key? SQL: a PR touching a .sql file or a migrations folder (SQL in
    other files elsewhere isn't looked for). Code: the same file, or for Go a .go file in the same package directory."""
    lang, scope = key[0], key[1]
    if lang == "sql":
        return any(p.lower().endswith(".sql") or MIGRATION_DIR_RX.search(p) for p in pr_paths)
    if lang == ".go":
        return any(p.endswith(".go") and (os.path.dirname(p) or ".") == scope for p in pr_paths)
    return scope in pr_paths


def symbol_collisions(repo, base, files, me=None, offline=False, base_ref=None):
    """Does anything else define the same function, view, trigger or class as this change? Two changes that each
    look fine can still collide: two migrations that CREATE OR REPLACE one SQL function (the last one applied wins,
    silently), or two PRs adding the same top-level def to one module (BLAZE escape #1: each PR GREEN on its own).

    Reads the definitions on this change's added lines (SQL CREATE [OR REPLACE] FUNCTION/PROCEDURE/VIEW/TRIGGER;
    top-level Python def/class; JS/TS function/class/export const; Go func per package; Ruby def), then looks for
    the same definition (a) added on the tracking ref since the merge-base, which fails, since the merge will
    redefine it; and (b) added by another open PR that could define it, which warns. Names under 4 characters,
    dunder names and constructors are skipped. No model call, no execution."""
    name = "no other change redefines the same symbols"
    ours = _added_defs(files)
    if not ours:
        return _item(name, "na", "the change defines no function, view, trigger or class")
    notes, landed = [], []
    if base_ref and base_ref != base and util.ref_exists(repo, base_ref):
        exts = sorted(set(SQL_HOST_EXT) | set(CODE_DEF_RX))      # only files that can hold a definition, any case
        theirs = _added_defs(parse_diff(git(repo, "diff", "--no-renames", "--unified=0", base, base_ref, "--",
                                            *[f":(icase)*{e}" for e in exts], check=False)))
        for k in ours:
            if any(_collides(k, t) for t in theirs):
                bare = k[2].split(" on ", 1)[0].rsplit(".", 1)[-1]   # a trigger key is "<name> on <table>"
                sha = git(repo, "log", "-n1", "-i", "--format=%h %s", f"{base}..{base_ref}", "-S", bare,
                          check=False) or "?"
                landed.append(f"{ours[k]} (in {sha.strip()[:80]})")
        notes.append(f"{base_ref} since the merge-base: {len(theirs)} definition(s) added, "
                     f"{len(landed)} the same as ours")
    else:
        notes.append(f"no tracking ref ahead of the merge-base to compare ({base_ref or 'none given'})")
    hits, failed, unread, unlisted = [], [], [], False
    slug = None if offline else upstream_slug(repo)
    if offline:
        notes.append("open PRs not checked (offline)")
    elif not slug:
        notes.append("open PRs not checked (no GitHub remote)")
    else:
        prs, total = open_prs(slug)
        if prs is None:
            unlisted = True
            notes.append(f"could not list open PRs on {slug}")
        else:
            cands = [pr for pr in prs if not pr["bot"] and not is_me(pr["author"], me)
                     and any(_could_define(pr["paths"], k) for k in ours)]
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(8) as ex:
                got = list(ex.map(lambda pr: _pr_defs(slug, pr["number"], pr.get("head")), cands[:OVERLAP_CANDIDATES]))
            for pr, res in zip(cands, got):
                if res is FETCH_FAILED:
                    failed.append(pr["number"])
                    continue
                same = [ours[k] for k in ours if any(_collides(k, t) for t in res["defs"])]
                if same:
                    hits.append(f"#{pr['number']} by {pr['author']} ({pr['url']}): {', '.join(same[:3])}")
                elif res["cut"] or any(_could_define([p], k) for p in res["unread"] for k in ours):
                    unread.append(pr["number"])
            notes.append(f"checked {min(len(cands), OVERLAP_CANDIDATES)} open PR(s) that could define them, "
                         f"of {total}")
            if len(cands) > OVERLAP_CANDIDATES:
                notes.append(f"{len(cands) - OVERLAP_CANDIDATES} more not read")
            if failed:
                notes.append(f"{len(failed)} couldn't be fetched (rate limit or network; re-run later)")
            if unread:
                notes.append(f"{len(unread)} couldn't be read in full, a file without a patch or more than "
                             f"{PR_FILES_PAGE} files (" + ", ".join(f"#{n}" for n in unread[:5]) + ")")
    defs = f"{len(ours)} definition(s): " + ", ".join(list(ours.values())[:4]) + (" …" if len(ours) > 4 else "")
    if landed:
        return _item(name, "fail", f"already redefined on {base_ref} since the merge-base: " + "; ".join(landed[:3])
                     + ". The merge will silently keep one of the two; rebase and reconcile them"
                     + (f". Open PRs too: {'; '.join(hits[:3])}" if hits else "") + f" ({'; '.join(notes)})")
    if hits:
        return _item(name, "warn", "another open PR defines the same: " + "; ".join(hits[:5]) + ". Whichever merges "
                     f"second replaces the first; read it before submitting ({defs}; {'; '.join(notes)})"
                     + ("" if me else UNKNOWN_ME))
    status = "warn" if failed or unread or unlisted else "pass"
    return _item(name, status, f"{defs}; {'; '.join(notes)}")




# Whole-table counts. A test that asserts a bare number against count(*) of a shared table (a lookup/catalog table
# seeded by migrations) passes on its own, and breaks the moment another change adds or removes rows of that table:
# each PR is green alone, main goes red after both merge. The link between the two changes is the table, not a file:
# the rows usually come from a separate migration. Idea from a reviewer exchange; no code shared.
SQL_TABLE = r"((?:\"[^\"]+\"|[\w$]+)(?:\.(?:\"[^\"]+\"|[\w$]+))?)"
COUNT_RX = re.compile(r"\bcount\s*\(\s*(?:\*|1)\s*\)\s+from\s+" + SQL_TABLE, re.I)
COUNT_FILTER_RX = re.compile(r"\b(?:where|join|group\s+by|having|limit|tablesample|offset)\b|^\s*(?:\w+\s*)?,", re.I)
COUNT_END_RX = re.compile(r"[;\"'`)]|\$\$")
COUNT_ASSERT_RX = re.compile(r"\bassert\w*|\bexpect\b|\.to(?:Be|Equal|StrictEqual|HaveLength)\b|\bassert_?equals?\b|"
                             r"(?:^|\s)-(?:eq|ne)\s|[!=]=|\bshould\b|\bmust\b|\bfail\b|\bdie\b|\bexit\s+1\b|"
                             r"\braise\b|\berror\b|\bunless\b", re.I)
COUNT_NUM_RX = re.compile(r"(?<![\w.$-])\d+(?![\w.])")
COUNT_LOCAL_RX = re.compile(r"\bcreate\s+(?:(?:temp|temporary|unlogged)\s+)*table\s+(?:if\s+not\s+exists\s+)?"
                            + SQL_TABLE + r"|\bwith\s+(?:recursive\s+)?" + SQL_TABLE + r"\s+as\s*\(|"
                            r",\s*" + SQL_TABLE + r"\s+as\s*\(", re.I)
WRITE_RX = re.compile(r"\b(?:insert\s+into|delete\s+from|truncate(?:\s+table)?(?:\s+only)?)\s+" + SQL_TABLE + r"|"
                      r"\bcopy\s+" + SQL_TABLE + r"(?:\s*\([^)]*\))?\s+from\b", re.I)
COUNT_TEST_RX = re.compile(r"(?:^|/)[^/]*(?:test|check|gate|verify|assert)[^/]*$|(?:^|/)(?:ci|checks?|gates?)/", re.I)
COUNT_TEST_EXT = (".sh", ".bash", ".sql", ".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".rb", ".go", ".exs", ".ex")
SEED_RX = re.compile(r"(?:^|/)(?:seeds?|seeders|fixtures/db|data/seed)(?:/|\.|_|$)")
SYSTEM_TABLE_RX = re.compile(r"(?:pg_catalog\.|information_schema\.|pg_|sqlite_|mysql\.|sys\.)")
COUNT_WINDOW = 4    # added lines after the count where the asserted number may sit (and 2 before)


def _count_test_file(path):
    low = path.lower()
    return low.endswith(COUNT_TEST_EXT) and (bool(TEST_PATH_RX.search(path)) or bool(COUNT_TEST_RX.search(path)))


def _sql_writer_file(path):
    """Files whose added SQL changes a database's rows for everyone: SQL/migration hosts, migrations and seeds,
    but not tests (a test's own fixture inserts run in its own database or transaction)."""
    low = path.lower()
    if TEST_PATH_RX.search(path) or _count_test_file(path):
        return False
    if low.endswith((".sql", ".psql", ".pgsql", ".plpgsql", ".ddl")):
        return True
    return low.endswith(SQL_HOST_EXT) and (bool(MIGRATION_DIR_RX.search(path)) or bool(SEED_RX.search(low)))


def _table_key(raw):
    return _sql_name(raw)


def _same_table(a, b):
    """schema.name keys (public. dropped): equal, or equal names where one side gives no schema (it resolves through
    search_path, so it may be the same table)."""
    if a == b:
        return True
    (sa, _, na), (sb, _, nb) = a.rpartition("."), b.rpartition(".")
    return na == nb and (not sa or not sb)


def _fixed_counts(files, repo=None):
    """{table: [(path, line_no, snippet)]} for unfiltered count(*) of a named table in an added test line, with a
    numeric literal asserted within a few added lines of it. Skipped: counts with WHERE/JOIN/GROUP BY/LIMIT (scoped to
    known keys), counts of a table the same test creates or names as a CTE (local), and lines with no number to
    compare against."""
    out = {}
    for f in files:
        path = f.get("path")
        if not path or f.get("deleted") or not _count_test_file(path):
            continue
        added = [(text, new) for h in f.get("hunks") or [] for kind, text, _old, new in h["lines"] if kind == "+"]
        body = "\n".join(t for t, _ in added)
        if repo:        # a table the test file creates elsewhere (not on the changed lines) is still its own
            body += "\n" + (git(repo, "show", f"HEAD:{path}", check=False) or "")
        local = {_table_key(next(g for g in m.groups() if g)) for m in COUNT_LOCAL_RX.finditer(body)}
        for i, (text, line_no) in enumerate(added):
            for m in COUNT_RX.finditer(text):
                table = _table_key(m.group(1))
                if any(_same_table(table, x) for x in local) or SYSTEM_TABLE_RX.match(table):
                    continue
                tail = text[m.end():] + "\n" + "\n".join(t for t, _ in added[i + 1:i + 3])
                end = COUNT_END_RX.search(tail)
                if COUNT_FILTER_RX.search(tail[:end.start()] if end else tail):
                    continue
                window = [t for t, _ in added[max(0, i - 2):i + 1 + COUNT_WINDOW]]
                joined = "\n".join(window).replace(m.group(0), " ")
                if not COUNT_ASSERT_RX.search(joined) or not COUNT_NUM_RX.search(joined):
                    continue
                out.setdefault(table, []).append((path, line_no, text.strip()[:80]))
    return out


def _writes(path, lines):
    """Tables whose rows these added lines of one file insert, delete, truncate or COPY into."""
    if not _sql_writer_file(path):
        return set()
    return {_table_key(next(g for g in m.groups() if g)) for ln in lines for m in WRITE_RX.finditer(ln)}


def _pr_writes(slug, number, head=None):
    """{"tables": [...], "unread": [...], "cut": bool} for a PR, or FETCH_FAILED. Cached per head SHA."""
    path = os.path.join(util.HOME, "cache", "pr-writes", slug.replace("/", "__"), f"{int(number)}.json") if head else None
    if path:
        hit = read_json(path)
        hit = hit if isinstance(hit, dict) else {}
        got = hit.get("got")
        if hit.get("head") == head and isinstance(hit.get("at"), (int, float)) and \
                time.time() - hit["at"] < HUNK_CACHE_TTL and isinstance(got, dict) and \
                isinstance(got.get("tables"), list) and isinstance(got.get("unread"), list) and \
                isinstance(got.get("cut"), bool):
            return got
    data = gh_json(f"repos/{slug}/pulls/{number}/files?per_page={PR_FILES_PAGE}")
    if not isinstance(data, list):
        return FETCH_FAILED
    tables = set()
    for f in data:
        name = f.get("filename") or ""
        plus = [ln[1:] for ln in (f.get("patch") or "").splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        tables |= _writes(name, plus)
    got = {"tables": sorted(tables), "cut": len(data) >= PR_FILES_PAGE,
           "unread": [f.get("filename") or "" for f in data if not f.get("patch") and f.get("changes")
                      and _sql_writer_file(f.get("filename") or "")]}
    if path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write_json(path, {"head": head, "at": time.time(), "got": got})
        except OSError:
            pass
    return got


def count_collisions(repo, base, files, me=None, offline=False, base_ref=None):
    """Does a test in this change assert a fixed row count of a table another change writes rows to? A test that
    checks `count(*) from t` against a bare number (36, or "0/0/36" in a combined string) is green alone, and red as
    soon as another migration inserts or deletes rows of t, wherever that migration lives: the link is the table.

    Reads unfiltered count(*) of a named table on added lines of test-like files (tests, gate/check scripts) with an
    asserted number nearby, then looks for INSERT/DELETE/TRUNCATE/COPY ... FROM on the same table (schema.name,
    public. dropped) in (a) the tracking ref since the merge-base, which fails, and (b) other open PRs' migrations,
    seeds and SQL files, which warns. Counts filtered to known keys, and tables the test makes itself, are left out.
    No model call, no execution."""
    name = "no other change moves a table a test counts"
    ours = _fixed_counts(files, repo)
    if not ours:
        return _item(name, "na", "no test asserts a fixed count(*) of a whole table")
    where = "; ".join(f"{t} ({v[0][0]}:{v[0][1]})" for t, v in list(ours.items())[:3])
    fix = ("measure the count on the base first (or count only this change's own rows, WHERE key IN (...)) "
           "instead of asserting a bare number")
    notes, landed = [], []
    if base_ref and base_ref != base and util.ref_exists(repo, base_ref):
        exts = sorted(set(SQL_HOST_EXT))
        theirs = {}
        for f in parse_diff(git(repo, "diff", "--no-renames", "--unified=0", base, base_ref, "--",
                                *[f":(icase)*{e}" for e in exts], check=False)):
            plus = [t for h in f.get("hunks") or [] for kind, t, *_ in h["lines"] if kind == "+"]
            for t in _writes(f.get("path") or "", plus):
                theirs.setdefault(t, f["path"])
        for t in ours:
            hit = next((w for w in theirs if _same_table(t, w)), None)
            if hit:
                bare = t.rsplit(".", 1)[-1]
                sha = git(repo, "log", "-n1", "-i", "--format=%h %s", f"{base}..{base_ref}", "-S", bare, "--",
                          theirs[hit], check=False) or "?"
                landed.append(f"{t} gets rows from {theirs[hit]} ({sha.strip()[:80]})")
        notes.append(f"{base_ref} since the merge-base writes rows to {len(theirs)} table(s)")
    else:
        notes.append(f"no tracking ref ahead of the merge-base to compare ({base_ref or 'none given'})")
    hits, failed, unread, unlisted = [], [], [], False
    slug = None if offline else upstream_slug(repo)
    if offline:
        notes.append("open PRs not checked (offline)")
    elif not slug:
        notes.append("open PRs not checked (no GitHub remote)")
    else:
        prs, total = open_prs(slug)
        if prs is None:
            unlisted = True
            notes.append(f"could not list open PRs on {slug}")
        else:
            cands = [pr for pr in prs if not pr["bot"] and not is_me(pr["author"], me)
                     and any(_sql_writer_file(p) for p in pr["paths"])]
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(8) as ex:
                got = list(ex.map(lambda pr: _pr_writes(slug, pr["number"], pr.get("head")), cands[:OVERLAP_CANDIDATES]))
            for pr, res in zip(cands, got):
                if res is FETCH_FAILED:
                    failed.append(pr["number"])
                    continue
                same = [t for t in ours if any(_same_table(t, w) for w in res["tables"])]
                if same:
                    hits.append(f"#{pr['number']} by {pr['author']} ({pr['url']}) writes rows to {', '.join(same[:3])}")
                elif res["cut"] or res["unread"]:
                    unread.append(pr["number"])
            notes.append(f"checked {min(len(cands), OVERLAP_CANDIDATES)} open PR(s) with migrations, seeds or SQL, "
                         f"of {total}")
            if len(cands) > OVERLAP_CANDIDATES:
                notes.append(f"{len(cands) - OVERLAP_CANDIDATES} more not read")
            if failed:
                notes.append(f"{len(failed)} couldn't be fetched (rate limit or network; re-run later)")
            if unread:
                notes.append(f"{len(unread)} couldn't be read in full (" + ", ".join(f"#{n}" for n in unread[:5]) + ")")
    if landed:
        return _item(name, "fail", f"a test asserts a fixed row count of a table {base_ref} has changed since the "
                     f"merge-base: " + "; ".join(landed[:3]) + f". The count will be off after the merge; {fix} "
                     f"(counts: {where}; {'; '.join(notes)})")
    if hits:
        return _item(name, "warn", "a test asserts a fixed row count of a table another open PR writes to: "
                     + "; ".join(hits[:5]) + f". Whichever merges second turns the count red; {fix} "
                     f"(counts: {where}; {'; '.join(notes)})" + ("" if me else UNKNOWN_ME))
    status = "warn" if failed or unread or unlisted else "pass"
    return _item(name, status, f"fixed count(s) of {where}; {'; '.join(notes)}")

# Generated files. A file is generated when .gitattributes marks it linguist-generated, when a comment in its first
# lines carries a generator's marker (Go's "Code generated ... DO NOT EDIT.", "@generated", or "generated" next to
# "do not edit"), or when its name is a code generator's (protobuf/gRPC stubs, *.generated.*, a generated/ directory).
# Lockfiles are written by package managers and vendored code is someone else's source, so both are left out.
# An input is what a generated file is built from: the "source:" its header names (protoc, sqlc), the OpenAPI/Swagger
# spec for a client whose header says so, or a schema file with the same stem (.proto, .graphql, ...). This is a
# heuristic: transitive inputs (an imported .proto, the schema behind sqlc queries) are not traced, so the hand-edit
# warning is skipped when a nearby schema, a migration (sqlc outputs), a generator config or a generator version
# bump changed too.
GEN_HEADER_RX = re.compile(r"^\W*Code generated\b.*\bDO NOT EDIT\b|@generated\b|"
                           r"\b(?:auto-?generated|generated\s+(?:by|from|with|automatically))\b.*\b(?:do not|don'?t)\s+edit\b|"
                           r"\b(?:do not|don'?t)\s+edit\b.*\b(?:auto-?generated|generated\s+(?:by|from|with))\b", re.I)
COMMENT_LINE_RX = re.compile(r"""^\s*(?://|#|/\*|\*|--|<!--|;|%|\(\*|\{-|"{3}|'{3})""")  # a marker counts only in a comment
GEN_NAME_RX = re.compile(r"(?:\.pb\.(?:go|gw\.go|cc|h|swift|dart)|_pb2(?:_grpc)?\.pyi?|_grpc\.pb\.go|_pb\.(?:js|d\.ts|ts)|"
                         r"_grpc_pb\.(?:js|d\.ts)|\.g\.dart|\.freezed\.dart|\.generated\.\w+|_generated\.\w+|\.gen\.\w+)$")
GEN_DIR_RX = re.compile(r"(?:^|/)(?:__generated__|generated|gen-src|autogen)/")
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock",
             "Cargo.lock", "poetry.lock", "uv.lock", "Pipfile.lock", "go.sum", "Gemfile.lock", "composer.lock",
             "mix.lock", "pubspec.lock", "Podfile.lock", "flake.lock"}
VENDOR_RX = re.compile(r"(?:^|/)(?:vendor|third_party|third-party|node_modules|external)/")
SCHEMA_EXT = (".proto", ".thrift", ".fbs", ".graphql", ".gql", ".avsc", ".capnp", ".xsd", ".wsdl", ".prisma")
OPENAPI_RX = re.compile(r"(?:^|[/._-])(?:openapi|swagger)[^/]*\.(?:ya?ml|json)$", re.I)
OPENAPI_HEAD_RX = re.compile(r"\b(?:openapi|swagger)\b", re.I)
# generator configs: when one changes, regenerated output legitimately changes with no input change. A package
# manifest (package.json, go.mod, tools.go, pyproject.toml) counts only when its changed lines name a generator (a
# version bump of protoc-gen-go / google.golang.org/protobuf, grpcio-tools, openapi-generator, ...; a gRPC runtime
# bump alone doesn't count, it doesn't change generated code); most PRs touch manifests for other reasons.
GEN_CONFIG_RX = re.compile(r"(?:^|/)(?:buf(?:\.gen)?\.ya?ml|sqlc\.(?:ya?ml|json)|codegen\.(?:ya?ml|ts|js|json)|"
                           r"openapitools\.json|\.graphqlrc(?:\.\w+)?|orval\.config\.\w+|gqlgen\.ya?ml)$")
GEN_MANIFEST_RX = re.compile(r"(?:^|/)(?:package\.json|go\.mod|tools\.go|pyproject\.toml|requirements[\w.-]*\.txt)$")
GEN_TOOL_RX = re.compile(r"\bprotoc\b|protoc[-_]gen[-_]|google\.golang\.org/protobuf\b|"
                         r"@bufbuild/|\bbuf\b|openapi-generator|openapi-typescript|swagger-codegen|graphql-codegen|"
                         r"\bsqlc\b|\borval\b|gqlgen|grpc-tools|ts-proto|grpcio-tools|betterproto", re.I)
GEN_SOURCE_RX = re.compile(r"\bsources?:\s*([\w./@+-]+\.\w+)", re.I)
GEN_STEM_RX = re.compile(r"(?:_pb2_grpc|_pb2|_grpc_pb|_grpc|_pb|_generated)$")
GEN_HEAD_LINES = 12
GEN_HEAD_BYTES = 8192
GEN_SCAN_MAX = 400      # repo files whose header is read when looking for the outputs of a changed input


def _skip_gen(path):
    return os.path.basename(path) in LOCKFILES or bool(VENDOR_RX.search(path))


def _head(repo, path, heads):
    """The first lines of a file in the working tree (what is being reviewed), read once per path into `heads` and
    bounded in bytes, so a minified bundle or a binary isn't read whole."""
    if path not in heads:
        try:
            with open(os.path.join(repo, path), "rb") as fh:
                raw = fh.read(GEN_HEAD_BYTES)
            heads[path] = "\n".join(raw.decode("utf-8", "replace").split("\n")[:GEN_HEAD_LINES])
        except OSError:
            heads[path] = ""
    return heads[path]


def _linguist_generated(repo, paths):
    if not paths:
        return set()
    out = git(repo, "check-attr", "-z", "linguist-generated", "--", *paths, check=False) or ""
    f = out.split("\0")
    return {f[i] for i in range(0, len(f) - 2, 3) if f[i + 2] in ("set", "true")}


def _generated(repo, paths, heads):
    """{path: why} for the paths that look generated. heads: {path: first lines}, filled as files are read."""
    attr = _linguist_generated(repo, paths)
    out = {}
    for p in paths:
        if _skip_gen(p):
            continue
        if p in attr:
            out[p] = "linguist-generated in .gitattributes"
        elif GEN_NAME_RX.search(p):
            out[p] = "a code generator's file name"
        elif any(COMMENT_LINE_RX.match(ln) and GEN_HEADER_RX.search(ln)
                 for ln in _head(repo, p, heads).split("\n")):
            out[p] = "a generated-file header"
        elif GEN_DIR_RX.search(p):
            out[p] = "a generated/ directory"
    return out


def _gen_stem(path):
    """foo.pb.go, foo_pb2.py, foo_pb2_grpc.py, foo.generated.ts, queries.sql.go -> foo / queries."""
    return GEN_STEM_RX.sub("", os.path.basename(path).split(".")[0])


def _near(a, b):
    """Same directory, one directory inside the other, or sibling directories under a common non-root parent. A file at
    the repo root is near only other root files (the root contains everything, so it would excuse anything)."""
    da, db = os.path.dirname(a), os.path.dirname(b)
    if da == db:
        return True
    if not da or not db:
        return False
    if da.startswith(db + "/") or db.startswith(da + "/"):
        return True
    pa, pb = os.path.dirname(da), os.path.dirname(db)
    return bool(pa) and pa == pb


class _Tracked:
    """The repo's tracked files, indexed by base name, stem and directory, so lookups don't rescan the whole list."""

    def __init__(self, paths):
        self.paths, self.by_base, self.by_stem, self.by_dir = paths, {}, {}, {}
        for t in paths:
            b = os.path.basename(t)
            self.by_base.setdefault(b, []).append(t)
            for k in {os.path.splitext(b)[0], _gen_stem(t)}:
                self.by_stem.setdefault(k, []).append(t)
            self.by_dir.setdefault(os.path.dirname(t), []).append(t)
        self.specs = [t for t in paths if OPENAPI_RX.search(t) and not _skip_gen(t)]


def _gen_inputs(path, head, tracked):
    """Files the generated `path` is likely built from: the "source:" its header names, else the OpenAPI spec for a
    client whose header names OpenAPI/Swagger, else schema files with the same stem."""
    named = []
    for m in GEN_SOURCE_RX.finditer(head):
        src = m.group(1)
        named += [t for t in tracked.by_base.get(os.path.basename(src), []) if t == src or t.endswith("/" + src)]
    if named:
        return sorted(set(named))
    if OPENAPI_HEAD_RX.search(head) and tracked.specs:
        return sorted(tracked.specs)
    stem = _gen_stem(path)
    if len(stem) < 3:
        return []
    return sorted({t for t in tracked.by_stem.get(stem, []) if t != path and t.endswith(SCHEMA_EXT)
                   and os.path.splitext(os.path.basename(t))[0] == stem and not _skip_gen(t)})


def _codegen_command(repo):
    """The project's own way to regenerate, if it declares one: an npm script, a Makefile target, go:generate."""
    pkg = util.read_json(os.path.join(repo, "package.json"), {})
    scripts = pkg.get("scripts") if isinstance(pkg, dict) else None
    for k in (scripts if isinstance(scripts, dict) else {}):
        if re.fullmatch(r"(?:gen|generate|codegen|proto|protos|build:types|generate:\w+|gen:\w+|types)", k):
            return f"npm run {k}"
    for mk in ("Makefile", "makefile", "GNUmakefile"):
        try:
            with open(os.path.join(repo, mk), errors="replace") as fh:
                for line in fh:
                    m = re.match(r"^(generate|gen|codegen|proto|protos|protobuf)\s*:(?!=)", line)
                    if m:
                        return f"make {m.group(1)}"
        except OSError:
            continue
    if git(repo, "grep", "-l", "-m1", "--untracked", "^//go:generate", "--", "*.go", check=False):
        return "go generate ./..."
    return None


def _ci_writers(repo, gen_paths):
    """{generated path: [workflow:job, ...]} for paths that more than one CI job writes with a shell redirect or an
    -o/--output flag. Artifact uploads and downloads move a file between jobs; they are not competing writers."""
    writers = {}
    for wf in sorted(glob.glob(os.path.join(repo, ".github", "workflows", "*.y*ml"))):
        try:
            with open(wf, errors="replace") as fh:
                lines = fh.read().split("\n")
        except OSError:
            continue
        job, in_jobs = None, False
        for line in lines:
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if in_jobs and re.match(r"^\S", line):
                in_jobs = False
            m = re.match(r"^  ([\w-]+):\s*$", line) if in_jobs else None
            if m:
                job = m.group(1)
                continue
            if not job:
                continue
            for p in gen_paths:
                pat = re.escape(p)
                if re.search(r"(?:>{1,2}\s*['\"]?" + pat + r"|(?:-o|--output|--out)[ =]['\"]?" + pat + r")(?:['\"\s]|$)",
                             line):
                    key = f"{os.path.basename(wf)}:{job}"
                    if key not in writers.setdefault(p, []):
                        writers[p].append(key)
    return {p: w for p, w in writers.items() if len(w) > 1}


# Falsifiers (tests/test_core.py TestGeneratedOutputs). Must flag: a .pb.go edited with its .proto unchanged; a .proto,
# sqlc query or OpenAPI spec changed without its output; an output named by its "source:" header under another stem;
# two CI jobs redirecting into one generated file. Must let through: an output regenerated with its input, or after a
# nearby imported schema / sibling sqlc schema / generator config changed; a new generated file; prose that says
# "generated"; lockfiles, vendor/, plain config YAML/JSON; artifact upload + download; a package.json, Makefile or
# far-away .sql change (these don't excuse a hand edit). Hand check, 2026-11-11, last 60 non-merge commits of 7 real
# repos (three-mesh-bvh, supabase-js, freeswitch, gamescope, heroic, janus-gateway, dragon-front): 0 warns; 13 passes,
# each a real generated file (bvh's API.md/WEBGPU_API.md docs, supabase-js types.generated.ts and generated types).
def generated_outputs(repo, base, files):
    """Generated files must be regenerated, not hand-edited, and must move with their inputs (BLAZE escape #3, idea
    only: a hand edit to a generated file passed review and was overwritten by the next codegen run; an input change
    shipped without its output). Warns when (a) a generated file changed while none of its inputs, and no other
    generator input or config, did; (b) an input changed but a generated file built from it didn't; (c) two CI jobs
    write the same generated file. Names the project's own regenerate command when it declares one. `base` is unused
    (the item reads HEAD only) and kept for the same signature as the other diff items. No model call, no execution."""
    name = "generated files regenerated with their inputs"
    live = [f["path"] for f in files if f.get("path") and not f.get("deleted")]
    changed = {f["path"] for f in files if f.get("path")}
    heads = {}
    gen = _generated(repo, live, heads)
    tracked = _Tracked([t for t in (git(repo, "ls-files", "-z", check=False) or "").split("\0") if t])
    # (b) a changed file is an input when a tracked generated file is built from it: its "source:" header names it
    # (sqlc's queries.sql, protoc), or it is the schema with the same stem, or the OpenAPI spec of a client. Candidate
    # outputs are read from the input's directory, its stem, and (for a spec) generated/api/client/sdk directories.
    cand_inputs = [p for p in live if p not in gen and not _skip_gen(p)]
    near = set()
    for i in cand_inputs:
        near.update(tracked.by_dir.get(os.path.dirname(i), []))
        near.update(tracked.by_stem.get(os.path.splitext(os.path.basename(i))[0], []))
    if any(OPENAPI_RX.search(i) for i in cand_inputs):
        near.update(t for t in tracked.paths
                    if GEN_DIR_RX.search(t) or re.search(r"(?:^|/)(?:api|client|clients|sdk)/", t))
    scan = sorted(t for t in near if t not in changed and not _skip_gen(t) and CODE_EXT_RX.search(t))[:GEN_SCAN_MAX]
    outs = _generated(repo, scan, heads)
    built = {o: _gen_inputs(o, _head(repo, o, heads), tracked) for o in outs}
    stale = []
    for i in cand_inputs:
        mine = sorted(o for o, ins in built.items() if i in ins)
        if mine:
            stale.append(f"{i} changed but {', '.join(mine[:3])} did not")
    # (a) generated files changed without their inputs; skipped (noted) when another generator input or config
    # changed, since that can legitimately change the output (an imported .proto, the schema behind sqlc queries)
    # A generator config counts wherever it is (and a manifest whose changed lines name a generator); another schema,
    # .sql or spec file only when it sits near the output or its inputs (same directory, parent/child, or sibling
    # directories), so an unrelated change elsewhere doesn't excuse the edit; a migration anywhere, but only for a sqlc
    # output, whose schema comes from the migrations. Plain manifest and Makefile changes don't count.
    deps = sorted(p for p in changed if p not in gen and (p.endswith(SCHEMA_EXT + (".sql",)) or OPENAPI_RX.search(p))
                  and not MIGRATION_DIR_RX.search(p))
    migrations = sorted(p for p in changed if MIGRATION_DIR_RX.search(p))
    configs = sorted(p for p in changed if GEN_CONFIG_RX.search(p)) + sorted(
        f["path"] for f in files if f.get("path") and GEN_MANIFEST_RX.search(f["path"])
        and any(k in "+-" and GEN_TOOL_RX.search(t) for h in f.get("hunks") or [] for k, t, *_ in h["lines"]))
    hand, notes = [], []
    for p in sorted(gen):
        if any(f["path"] == p and f.get("added") for f in files):
            continue                                           # a new generated file arrives with its generator run
        ins = _gen_inputs(p, _head(repo, p, heads), tracked)
        if not ins:
            notes.append(f"{p}: generated ({gen[p]}), input not identified")
        elif not any(i in changed for i in ins):
            # a migration changes the database schema sqlc reads, wherever the migrations directory is
            sqlc = any(i.endswith(".sql") for i in ins) or "sqlc" in _head(repo, p, heads).lower()
            why = configs + [d for d in deps if any(_near(d, x) for x in [p] + ins)] + (migrations if sqlc else [])
            if why:
                notes.append(f"{p}: its input is unchanged, but {why[0]} changed, which may be why")
            else:
                hand.append(f"{p} ({gen[p]}; built from {', '.join(ins[:2])}, unchanged)")
    ci = [f"{p} is written by {', '.join(w[:3])}" for p, w in (_ci_writers(repo, sorted(gen)) if gen else {}).items()]
    if not gen and not stale:
        return _item(name, "na", "no generated file or generator input in the change")
    probs, fixes = [], []
    cmd = _codegen_command(repo)
    run = (f"run `{cmd}` and commit what it writes" if cmd else
           "regenerate with the project's generator and commit its output")
    if hand:
        probs.append("generated file(s) changed while their inputs did not, so they may be hand edits the next "
                     "codegen run undoes: " + "; ".join(hand[:3]) + (" …" if len(hand) > 3 else ""))
    if stale:
        probs.append("input(s) changed without their generated output: " + "; ".join(stale[:3]))
    if hand or stale:
        fixes.append(f"move any hand edit into the input, then {run}" if hand else run)
    if ci:
        probs.append("two CI jobs write the same generated file, so the last one wins: " + "; ".join(ci[:3]))
        fixes.append("keep one job writing it")
    if probs:
        fix = "; ".join(dict.fromkeys(fixes))
        return _item(name, "warn", ". ".join(probs) + f". {fix[0].upper() + fix[1:]}"
                     + (f" ({'; '.join(notes[:2])})" if notes else ""))
    ok = f"{len(gen)} generated file(s) changed along with their inputs or with no identifiable input"
    return _item(name, "pass", ok + (f" ({'; '.join(notes[:3])})" if notes else ""))


def current_login():
    """The GitHub login of whoever runs crucible: CRUCIBLE_GH_USER, else the account `gh` is logged in as, else None.
    The claim checks skip this person's own assignment and PRs; the default used to be the maintainer's own handle,
    so anyone else was told their own assignment was a competing claim."""
    env = os.environ.get("CRUCIBLE_GH_USER", "").strip()
    if env:
        return env
    d = gh_json("user")                   # None when gh is missing, hung or logged out: unknown, the review goes on
    return d.get("login") if isinstance(d, dict) else None


def evaluate(repo, project, base, files, draft=None, me=None, offline=False, base_ref=None):
    if me is None and not offline and upstream_slug(repo):    # both claim checks are "na" without a GitHub remote
        me = current_login()
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
        newer_draft(repo, draft_path),
        _item("issue linked", "pass" if issue else "fail", f"#{issue}" if issue else
              (f"template placeholder still in the draft: {issue_placeholder(draft_text)!r}" if issue_placeholder(draft_text)
               else f"the linked number(s) {['#' + str(n) for n in prs]} are pull requests, not issues" if prs
               else "no 'Fixes #N' / 'Related issue: #N' / issue URL in the draft (a bare #N doesn't count)")),
        tests_touched(paths),
        ci_matrix(repo, paths),
        api_docs_touched(files),
        changelog(repo, paths),
        commit_style(repo, base, subjects),
        dco(repo, base),
        commit_attribution(repo, base),
        _item("no formatting-only churn", "fail" if fmt else "pass", f"whitespace-only hunks: {fmt[:5]}" if fmt else "none"),
        size(project, files),
        learned_data(project),
        _item("issue still unclaimed", "na", "offline") if offline else unclaimed(repo, issue, me),
        _item("no open PR changes the same lines", "na", "offline") if offline else overlapping_prs(repo, files, me),
        _item("base branch hasn't moved under the change", "na", "offline") if offline else
        base_moved(repo, base_ref, base),
        migration_order(repo, base, files, base_ref),
        symbol_collisions(repo, base, files, me, offline, base_ref),
        count_collisions(repo, base, files, me, offline, base_ref),
        generated_outputs(repo, base, files),
    ]
    return {"draft": draft_path, "issue": issue, "items": items,
            "ready": not any(i["status"] == "fail" for i in items)}
