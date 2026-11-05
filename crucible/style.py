"""House style: measure how a project's regulars write PRs, commits and comments, then hold a change to it.

`learn_style` measures (deterministic) + extracts conventions (one model call) into projects/<p>/STYLE.md + style.json.
`check` returns deterministic medium/low findings for the diff's comments and the PR draft.
`polish` rewrites PR_DRAFT.md into PR_DRAFT.polished.md in the project's voice, without inventing claims."""
import collections, os, re, statistics, textwrap
from .util import (CODE_EXT_RX, ISSUE_KW, TEST_PATH_RX, Budget, claude, gh_json, git, project_dir, read_json, write_json)

EMOJI_RX = re.compile("[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F2FF☀-⛿⭐✅❌]")
BOILERPLATE_RX = re.compile(r"^[^\w\n]*(this (pr|pull request|change|commit) (introduces|adds|aims|implements|fixes|addresses)|"
                            r"in this (pr|pull request))", re.I | re.M)
HEDGE_RX = re.compile(r"\b(it'?s worth noting|it is worth noting|seamless(ly)?|robust(ly)?|leverag(e|es|ing)|comprehensive|"
                      r"delve|streamlin(e|ed|es)|ensure[sd]? that|enhance[sd]?|elevat(e|es)|in summary|overall,|"
                      r"potentially|essentially|basically|meticulous|holistic|game.?changer|best practices)\b", re.I)
OBVIOUS_COMMENT_RX = re.compile(r"^\s*(//|#|/?\*)\s*(increment|decrement|loop (over|through)|return(s)? the|set(s)? the|"
                                r"get(s)? the|call(s)? the|create(s)? (a|an|the) (new )?|initiali[sz]e (the )?|check if|"
                                r"import |define(s)? (a|the) )", re.I)
COMMENT_LINE_RX = re.compile(r"^\s*(//|#(?!include|define|if|endif|pragma|!)|/\*|\*(?!/)|\*/|<!--|--\s)")
ISSUE_REF_RX = re.compile(r"(?im)^\s*((?:fix(?:es|ed)?|close[sd]?|resolve[sd]?|related(?: issue)?s?|refs?)\b[^\n#]{0,20}#\d+)")
HEADING_RX = re.compile(r"(?m)^#{1,4}\s+(.+?)\s*$")


# ---------- measurements ----------
def words(t):
    return len(re.findall(r"\w+", t or ""))


CHECKBOX_RX = re.compile(r"^([-*+]\s+)\[[ xX]\]")
# How it was tested: a phrase (prefixes match, as before: "Screenshots", "afterwards"), or a code span that *is* a
# build/test command with arguments ("Checked with `npm run build-docs`"). A bare tool or file name (`python`,
# `yarn.lock`, `Cargo.toml`) is not a command, so it doesn't count.
TESTED_RX = re.compile(r"(?i)\b(tested|test plan|how to test|repro|verified|checked|confirmed|measured|benchmark|ran\b|"
                       r"npm test|pytest|unittest|screenshot|before|after|tests? pass|passing)|"
                       r"`\s*(\$\s*)?(npm|pnpm|yarn|npx|bun|deno|make|cargo|go|pytest|python3?|tox|nox|meson|ninja|ctest|"
                       r"gradle|mvn|dotnet|rake|mix)\s+[^`\n]+`")


def _tpl_norm(line):
    """A line as the template would have it: checkbox state, emphasis and spacing don't matter."""
    return " ".join(CHECKBOX_RX.sub(r"\1[ ]", line.strip()).replace("*", "").split()).lower()


def body_words(text, template="", title=""):
    """Words the author wrote in the body: HTML comments (as the learned median strips them), the title and lines
    copied verbatim from the repo's PR template (its checklist and headings, ticked or not) don't count.
    Merged bodies keep their template lines in the learned median, so this errs toward not flagging length."""
    t = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    if title and t.lstrip().startswith(title):
        t = t.lstrip()[len(title):]
    tpl = {_tpl_norm(l) for l in re.sub(r"<!--.*?-->", "", template or "", flags=re.S).split("\n")} - {""}
    return sum(words(l) for l in t.split("\n") if _tpl_norm(l) not in tpl)


def median_int(xs):
    xs = [x for x in xs if x is not None]
    return int(statistics.median(xs)) if xs else None


def comment_density(text):
    """Comment lines per 100 non-blank code lines."""
    lines = [l for l in (text or "").split("\n") if l.strip()]
    if not lines:
        return 0.0
    c = sum(1 for l in lines if COMMENT_LINE_RX.match(l))
    return round(100.0 * c / len(lines), 1)


def body_stats(bodies):
    bodies = [re.sub(r"<!--.*?-->", "", b or "", flags=re.S) for b in bodies]
    heads = collections.Counter(h.strip().lower() for b in bodies for h in HEADING_RX.findall(b))
    refs = collections.Counter()
    for b in bodies:
        for m in ISSUE_REF_RX.findall(b):
            refs[re.sub(r"\d+", "N", m.strip().lower())] += 1
    n = max(1, len(bodies))
    return {"median_words": median_int([words(b) for b in bodies]),
            "p75_words": int(statistics.quantiles([words(b) for b in bodies], n=4)[2]) if len(bodies) >= 4 else None,
            "pct_with_tables": round(100 * sum(1 for b in bodies if re.search(r"(?m)^\|.+\|\s*$", b)) / n),
            "pct_with_images": round(100 * sum(1 for b in bodies if re.search(r"!\[|<img|user-attachments", b)) / n),
            "pct_with_emoji": round(100 * sum(1 for b in bodies if EMOJI_RX.search(b)) / n),
            "pct_with_headings": round(100 * sum(1 for b in bodies if HEADING_RX.search(b)) / n),
            "common_headings": [h for h, c in heads.most_common(8) if c >= 2],
            "issue_ref_forms": [f for f, _ in refs.most_common(4)]}


def title_stats(titles):
    pats = collections.Counter()
    for t in titles:
        if re.match(r"^[a-z]+(\([^)]+\))?!?: ", t):
            pats["conventional `type(scope): subject`"] += 1
        elif re.match(r"^[A-Z][\w.]+: ", t):
            pats["`Component: Subject` (e.g. `WebGLRenderer: Fix ...`)"] += 1
        elif re.match(r"^\[[^\]]+\]", t):
            pats["`[area] subject`"] += 1
        else:
            pats["plain sentence"] += 1
    return {"median_chars": median_int([len(t) for t in titles]), "formats": pats.most_common(3),
            "ends_with_period_pct": round(100 * sum(t.endswith(".") for t in titles) / max(1, len(titles)))}


def learn_style(repo, slug, project, n=20, model="claude-sonnet-5-5", budget_usd=1.5, log=print):
    pulls = gh_json(f"repos/{slug}/pulls?state=closed&sort=updated&direction=desc&per_page=80") or []
    merged = [p for p in pulls if p.get("merged_at") and p.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR")]
    # prefer repeat authors
    counts = collections.Counter((p.get("user") or {}).get("login") for p in merged)
    merged.sort(key=lambda p: -counts[(p.get("user") or {}).get("login")])
    sample = merged[:n]
    titles, bodies, commits = [p["title"] for p in sample], [p.get("body") or "" for p in sample], []
    for p in sample[:12]:
        for c in gh_json(f"repos/{slug}/pulls/{p['number']}/commits?per_page=20") or []:
            commits.append(((c.get("commit") or {}).get("message") or "").strip())
    subj = [c.split("\n", 1)[0] for c in commits if c]
    m = {"slug": slug, "prs_sampled": len(sample), "title": title_stats(titles), "body": body_stats(bodies),
         "commit": {"median_subject_chars": median_int([len(s) for s in subj]),
                    "pct_with_body": round(100 * sum(1 for c in commits if "\n\n" in c) / max(1, len(commits))),
                    "formats": title_stats(subj)["formats"]},
         "examples": [{"url": p["html_url"], "title": p["title"], "body": (p.get("body") or "")[:900]}
                      for p in sorted(sample, key=lambda p: abs(words(p.get("body")) - (body_stats(bodies)["median_words"] or 0)))[:3]]}
    # repo-wide comment density over a sample of source files at HEAD
    files = [f for f in git(repo, "ls-files", check=False).split("\n") if CODE_EXT_RX.search(f) and not TEST_PATH_RX.search(f)
             and not re.search(r"(^|/)(vendor|dist|build|node_modules|libs?/)", f)][:400]
    dens = []
    for f in files[:: max(1, len(files) // 60)][:60]:
        try:
            dens.append(comment_density(open(os.path.join(repo, f), errors="replace").read()))
        except OSError:
            pass
    m["comment_density_median"] = statistics.median(dens) if dens else None
    write_json(os.path.join(project_dir(project), "style.json"), m)
    conv = {"tone": "", "comment_conventions": "", "callouts": "", "avoid": ""}
    try:
        samp = "\n\n".join(f"### {e['title']} ({e['url']})\n{e['body']}" for e in m["examples"])
        code = "\n\n".join(f"--- {f} ---\n" + open(os.path.join(repo, f), errors="replace").read()[:3000]
                           for f in files[:: max(1, len(files) // 4)][:4])
        out, _ = claude(textwrap.dedent(f"""\
            Describe how regular contributors to {slug} write, so a newcomer's PR can match them. Be concrete and short.
            1. tone: PR/commit voice (terse? first person? imperative?), typical length.
            2. comment_conventions: from the code sample, how they comment (JSDoc vs inline, density, what they explain,
               how they reference issues/links in code).
            3. callouts: how they flag things for reviewers (e.g. "Note:", before/after numbers, screenshots, live examples).
            4. avoid: things these regulars never do in PRs or comments.

            Recent merged PR bodies:
            {samp[:8000]}

            Code sample:
            {code[:9000]}
            """), model, {"type": "object", "properties": {k: {"type": "string"} for k in conv}, "required": list(conv)},
            repo, Budget(budget_usd), tools=None, effort="medium")
        conv = out
    except Exception as e:  # noqa: BLE001 - measurements are still useful
        conv["tone"] = f"(convention extraction failed: {e})"
    m["conventions"] = conv
    write_json(os.path.join(project_dir(project), "style.json"), m)
    b, t, c = m["body"], m["title"], m["commit"]
    L = [f"# House style: {slug}", "", f"Measured from {len(sample)} recently merged PRs (repeat contributors first).", "",
         "## PR title", f"- median length {t['median_chars']} chars; formats: " + ", ".join(f"{k} ({v})" for k, v in t["formats"]),
         f"- ends with a period: {t['ends_with_period_pct']}%", "", "## PR body",
         f"- median {b['median_words']} words (p75 {b['p75_words']}); headings in {b['pct_with_headings']}% "
         f"(common: {b['common_headings'] or 'none'}); tables {b['pct_with_tables']}%; screenshots {b['pct_with_images']}%; "
         f"emoji {b['pct_with_emoji']}%",
         f"- issue references: {b['issue_ref_forms'] or 'none observed'}", "", "## Commits",
         f"- median subject {c['median_subject_chars']} chars; with body {c['pct_with_body']}%; formats: "
         + ", ".join(f"{k} ({v})" for k, v in c["formats"]), "",
         "## Code comments", f"- median comment density: {m['comment_density_median']} comment lines / 100 lines",
         f"- {conv['comment_conventions']}", "", "## Voice", f"- {conv['tone']}", f"- call-outs: {conv['callouts']}",
         f"- avoid: {conv['avoid']}", "", "## Example PR bodies", ""]
    for e in m["examples"]:
        L += [f"### [{e['title']}]({e['url']})", "", "> " + e["body"][:700].replace("\n", "\n> "), ""]
    open(os.path.join(project_dir(project), "STYLE.md"), "w").write("\n".join(L) + "\n")
    log(f"wrote STYLE.md ({len(sample)} PRs, body median {b['median_words']} words)")
    return m


# ---------- deterministic house-style findings ----------
def _f(sev, file, line, title, problem, fix, wrong_if):
    return {"severity": sev, "file": file, "line": line, "title": title, "problem": problem, "fix": fix,
            "wrong_if": wrong_if, "caused_by_this_change": True, "reachable_in_real_use": True, "source": "style"}


def norm_heading(h):
    """'🔄 Breaking changes:' -> 'breaking changes', so emoji-prefixed template headings match learned ones."""
    return re.sub(r"[\s:]+$", "", re.sub(r"^[^\w]+", "", h.strip())).lower()


def ai_tells(text, style=None, allowed_headings=(), template="", title=""):
    """-> list of (kind, detail) for a PR description. `allowed_headings` (the repo's PR template) never count;
    length counts only what the author wrote (see body_words)."""
    style = style or {}
    allowed = {norm_heading(h) for h in allowed_headings}
    out = []
    em = EMOJI_RX.findall(text)
    if em and (style.get("body", {}).get("pct_with_emoji", 0) < 10):
        out.append(("emoji", f"{len(em)} emoji ({''.join(em[:5])})"))
    if BOILERPLATE_RX.search(text):
        out.append(("boilerplate", BOILERPLATE_RX.search(text).group(0).strip()))
    hedges = sorted(set(m.group(0).lower() for m in HEDGE_RX.finditer(text)))
    if len(hedges) >= 2:
        out.append(("filler", ", ".join(hedges[:6])))
    bullets = len(re.findall(r"(?m)^\s*[-*] ", text))
    if bullets > 12:
        out.append(("bullet bloat", f"{bullets} bullets"))
    med = (style.get("body") or {}).get("median_words")
    w = body_words(text, template, title)
    if med and w > max(2.5 * med, med + 150):
        out.append(("length", f"{w} words vs project median {med}"))
    # only learned measurements can call a heading unusual; the template just exempts its own headings
    common = {norm_heading(h) for h in (style.get("body") or {}).get("common_headings") or []}
    own = [h for h in HEADING_RX.findall(text) if norm_heading(h) not in allowed]
    if style and (style.get("body") or {}).get("pct_with_headings", 100) < 30:
        if len(own) >= 2:
            out.append(("headings", f"{len(own)} headings; only {style['body']['pct_with_headings']}% of merged PRs use any"))
    elif common:
        odd = [h for h in own if norm_heading(h) not in common]
        if len(odd) >= 3:
            out.append(("headings", f"headings this project rarely uses: {odd[:4]}"))
    if text.count("—") >= 4:
        out.append(("em-dashes", f"{text.count(chr(0x2014))} em dashes"))
    return out


def check(repo, base, files, draft_path, draft_text, style, title=""):
    from .readiness import template_headings, template_text
    out = []
    if draft_text:
        for kind, detail in ai_tells(draft_text, style, template_headings(repo)[1], template_text(repo)[1], title):
            out.append(_f("medium" if kind in ("length", "boilerplate") else "low", os.path.basename(draft_path or "PR_DRAFT.md"), 1,
                          f"PR description: {kind} reads as generated", detail,
                          "Rewrite in the project's own voice (run `crucible polish`).",
                          "this project's merged PRs commonly do the same (see STYLE.md measurements)"))
        if not TESTED_RX.search(draft_text):
            out.append(_f("medium", os.path.basename(draft_path or "PR_DRAFT.md"), 1, "PR description: no testing evidence",
                          "Reviewers can't see how this was tested.", "Add a short 'Tested:' line with the exact commands/results.",
                          "the description already states how it was tested"))
    for f in files:
        if f["deleted"] or f["binary"] or not CODE_EXT_RX.search(f["path"]) or TEST_PATH_RX.search(f["path"]):
            continue
        added = [(n, t) for h in f["hunks"] for k, t, _o, n in h["lines"] if k == "+"]
        if len(added) < 8:
            continue
        try:
            base_text = git(repo, "show", f"{base}:{f['path']}")
        except Exception:  # noqa: BLE001 - new file
            base_text = ""
        file_d = comment_density(base_text) if base_text else (style or {}).get("comment_density_median") or 0
        add_d = comment_density("\n".join(t for _, t in added))
        if add_d > max(2.5 * file_d, file_d + 15) and add_d >= 20:
            out.append(_f("low", f["path"], added[0][0], "Over-commented compared with this file",
                          f"added code has {add_d} comment lines/100 vs the file's {file_d}",
                          "Keep only comments that explain why (invariants, ordering, gotchas); drop narration.",
                          "the extra comments document non-obvious invariants the file previously lacked"))
        for n, t in added:
            if OBVIOUS_COMMENT_RX.match(t):
                out.append(_f("low", f["path"], n, "Comment narrates the obvious", t.strip()[:120],
                              "Delete it or say why instead of what.", "the comment explains a non-obvious reason"))
                break
        if len(added) >= 40 and add_d == 0 and file_d >= 5:
            out.append(_f("low", f["path"], added[0][0], "Large new logic with no comments",
                          f"{len(added)} added lines, no comments, in a file that averages {file_d}/100",
                          "Add a brief why-comment where ordering, invariants or perf subtleties matter.",
                          "the added logic is self-explanatory"))
    return out


# ---------- polish ----------
POLISH_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"},
                                                  "removed": {"type": "array", "items": {"type": "string"}},
                                                  "kept_facts": {"type": "array", "items": {"type": "string"}}},
                 "required": ["title", "body", "removed", "kept_facts"]}


REQUIRED_LINE_RX = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?" + ISSUE_KW + r"\b(?:\*\*)?\s*:?\s*(?:\*\*)?\s*(?:#|https?://)"
                              r"|github\.com/[^/\s]+/[^/\s]+/issues/\d+", re.I)


def keep_required_lines(original, rewritten):
    """Issue-link lines ("Closes #12", "Related issue: #34697") are required by many PR templates and must survive a
    rewrite verbatim. Returns (body, restored lines). A line that was first in the original goes back on top, else at the end."""
    def required(line):
        """A line that IS an issue link: it starts with a linking keyword, or the whole line is an issue URL/link."""
        t = line.strip()
        return bool(REQUIRED_LINE_RX.match(t)) or (t.startswith(("http", "<http", "[")) and bool(REQUIRED_LINE_RX.search(t)))
    req = [l.strip() for l in original.split("\n") if required(l)]
    have = {re.sub(r"\s+", " ", l.strip()).lower() for l in rewritten.split("\n")}
    missing = [l for l in req if re.sub(r"\s+", " ", l).lower() not in have]
    if not missing:
        return rewritten, []
    first = next((l.strip() for l in original.split("\n") if l.strip()), "")
    top = [l for l in missing if l == first]
    rest = [l for l in missing if l != first]
    body = rewritten.strip("\n")
    if top:
        body = "\n".join(top) + "\n\n" + body
    if rest:
        body = body + "\n\n" + "\n".join(rest)
    return body, missing


def polish(repo, project, model=os.environ.get("CRUCIBLE_ASSIST_MODEL", "claude-opus-5-5"), budget_usd=1.0, log=print):
    from .readiness import NOTES_MARKER, find_draft, split_draft, template_headings, template_text
    path, full = find_draft(repo)
    parts = split_draft(full)
    draft = (f"Title: {parts['title']}\n\n" if parts["title"] else "") + parts["body"]
    if not draft.strip():
        raise SystemExit("no PR_DRAFT.md to polish")
    style_md = open(os.path.join(project_dir(project), "STYLE.md")).read() if os.path.exists(os.path.join(project_dir(project), "STYLE.md")) \
        else "(no STYLE.md: run `crucible learn` first; fall back to terse, factual, maintainer-like prose)"
    tpl, heads = template_headings(repo)
    out, cost = claude(textwrap.dedent(f"""\
        Rewrite this pull-request description so it reads like a long-time regular of this project wrote it.
        Match the house style below (title format, length near the median, the project's headings or none, how issues
        are referenced). Keep EVERY factual statement, number, command and test result from the original; do not add any
        claim that isn't in the original or provable from the checkout (you may read the code). Add a short
        "Note for reviewers" style call-out only if the original or the code shows a real trade-off or risky spot.
        No emoji, no "This PR ..." openers, no filler words, no marketing tone. {'Required template sections: ' + str(heads) if heads else ''}
        Return the new title and body, a list of anything you removed (so the author can check), and the facts you kept.

        House style:
        {style_md[:7000]}

        Original description:
        {draft}
        """), model, POLISH_SCHEMA, repo, Budget(budget_usd))
    newp = os.path.join(repo, "PR_DRAFT.polished.md")
    body, restored = keep_required_lines(parts["body"], out["body"])
    if restored:
        log(f"  restored required line(s) the rewrite dropped: {restored}")
    txt = f"# {out['title']}\n\n{body.strip()}\n"
    # carry the author's notes over, so the polished draft still has them, marked off
    open(newp, "w").write(txt + (f"\n{NOTES_MARKER}\n\n{parts['notes']}\n" if parts["notes"] else ""))
    notes = "\n".join(f"- removed: {r}" for r in out["removed"]) or "- nothing removed"
    open(os.path.join(repo, "PR_DRAFT.polish-notes.md"), "w").write(f"# Polish notes\n\n{notes}\n\n## Facts kept\n\n"
                                                                    + "\n".join(f"- {k}" for k in out["kept_facts"]) + "\n")
    leftover = ai_tells(out["body"], read_json(os.path.join(project_dir(project), "style.json"), {}), heads,
                        template_text(repo)[1])
    log(f"wrote {newp} (original kept) · {len(out['removed'])} removals listed in PR_DRAFT.polish-notes.md · "
        f"remaining tells: {leftover or 'none'} · ${round(cost, 4)}")
    return newp
