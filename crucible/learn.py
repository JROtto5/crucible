"""`crucible learn`: extract what this project's maintainers actually ask for, from merged PR reviews."""
import datetime as dt, os, statistics, textwrap
from .util import (LEARN_VERSION, Budget, Failed, claude, gh_json, is_bot, project_dir, project_key, upstream_slug,
                   write_json)

MAINTAINERS = {"OWNER", "MEMBER", "COLLABORATOR"}
RULES_SCHEMA = {"type": "object", "properties": {"rules": {"type": "array", "maxItems": 25, "items": {
    "type": "object", "properties": {"rule": {"type": "string"}, "why": {"type": "string"},
                                     "sources": {"type": "array", "items": {"type": "string"}}},
    "required": ["rule", "why", "sources"]}}}, "required": ["rules"]}


def collect(slug, n=25, log=print):
    pulls = gh_json(f"repos/{slug}/pulls?state=closed&sort=updated&direction=desc&per_page=60", check=True) or []
    # bot PRs (Dependabot bumps) and bot comments say nothing about what maintainers ask of people
    merged = [p for p in pulls if p.get("merged_at") and not is_bot(p.get("user"))][:n]
    comments, sizes = [], []
    for p in merged:
        num = p["number"]
        log(f"  #{num} {p['title'][:70]}")
        det = gh_json(f"repos/{slug}/pulls/{num}") or {}
        if det:
            sizes.append((det.get("additions") or 0) + (det.get("deletions") or 0))
        for ep in (f"repos/{slug}/pulls/{num}/comments?per_page=100", f"repos/{slug}/issues/{num}/comments?per_page=100",
                   f"repos/{slug}/pulls/{num}/reviews?per_page=100"):
            for c in gh_json(ep) or []:
                if c.get("author_association") in MAINTAINERS and (c.get("body") or "").strip() \
                        and not is_bot(c.get("user")) \
                        and (c.get("user") or {}).get("login") != (p.get("user") or {}).get("login"):
                    comments.append({"pr": num, "url": c.get("html_url") or p["html_url"], "path": c.get("path"),
                                     "body": c["body"].strip()[:600]})
    return merged, comments, sizes


def docs_text(slug):
    out = []
    for path in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "AGENTS.md", ".github/PULL_REQUEST_TEMPLATE.md",
                 ".github/pull_request_template.md"):
        d = gh_json(f"repos/{slug}/contents/{path}")
        if isinstance(d, dict) and d.get("content"):
            import base64
            out.append(f"--- {path} ---\n" + base64.b64decode(d["content"]).decode(errors="replace")[:6000])
    return "\n".join(out)


def run_learn(repo, n=25, model="claude-sonnet-5-5", budget_usd=2.0, style=True, log=print):
    slug = upstream_slug(os.path.abspath(repo))
    if not slug:
        raise Failed("no GitHub remote (upstream/origin) found")
    project = project_key(repo)
    log(f"learning {slug} from the last {n} merged PRs")
    merged, comments, sizes = collect(slug, n, log)
    docs = docs_text(slug)
    meta = {"slug": slug, "learned": dt.date.today().isoformat(), "learn_version": LEARN_VERSION, "prs_sampled": len(merged),
            "maintainer_comments": len(comments), "median_merged_pr_lines": int(statistics.median(sizes)) if sizes else None,
            "p75_merged_pr_lines": int(statistics.quantiles(sizes, n=4)[2]) if len(sizes) >= 4 else None}
    write_json(os.path.join(project_dir(project), "meta.json"), meta)
    if not comments and not docs:
        log("no maintainer comments or docs found; wrote size stats only")
        return _with_style(meta, repo, slug, project, style, log)
    prompt = textwrap.dedent(f"""\
        From these real maintainer review comments on merged pull requests to {slug}, and the project's contribution
        docs, extract the RECURRING things maintainers ask contributors for or push back on: tests, examples, docs/types,
        API stability, bundle size, dependencies, naming, scope ("one change per PR"), formatting tools, commit style, etc.
        Only include a rule if it is supported by the docs or by at least two comments; cite source URLs (comment links
        or doc paths). Be specific to this project, not generic advice. Return up to 25 rules, most important first.

        Contribution docs:
        {docs[:15000]}

        Maintainer comments (pr, url, path, body):
        {chr(10).join(f"- #{c['pr']} {c['url']} {c['path'] or ''}: {c['body']}" for c in comments)[:60000]}
        """)
    budget = Budget(budget_usd)
    try:
        out, _ = claude(prompt, model, RULES_SCHEMA, repo, budget, tools=None, effort="medium")
    except Failed as e:     # a call that fails after the model ran was still paid for; say how much
        raise Failed(f"{e} (learn cost ${round(budget.spent, 4)} spent on the rules call)") from e
    md = [f"# Maintainer preferences: {slug}", "",
          f"Learned {meta['learned']} from {len(merged)} merged PRs ({len(comments)} maintainer comments). "
          f"Median merged PR: {meta['median_merged_pr_lines']} changed lines.", ""]
    for r in out["rules"]:
        md.append(f"- **{r['rule']}**: {r['why']} ({', '.join(r['sources'][:3])})")
    open(os.path.join(project_dir(project), "rules.md"), "w").write("\n".join(md) + "\n")
    meta["rules"] = len(out["rules"]); meta["cost_usd"] = round(budget.spent, 4)
    write_json(os.path.join(project_dir(project), "meta.json"), meta)
    log(f"wrote {len(out['rules'])} rules → {os.path.join(project_dir(project), 'rules.md')}")
    return _with_style(meta, repo, slug, project, style, log)


def _with_style(meta, repo, slug, project, style, log):
    """Run the style pass and report the whole learn's spend. Each call's cost stays in the file it produced
    (meta.json: rules, style.json: conventions); the total is returned and logged, not stored twice."""
    rules = meta.get("cost_usd", 0)
    style_cost = 0
    if style:
        from .style import learn_style
        style_cost = learn_style(os.path.abspath(repo), slug, project, log=log).get("cost_usd", 0)
    total = round(rules + style_cost, 4)
    log(f"learn cost ${total} (rules ${rules}, style ${style_cost})")
    return {**meta, "total_cost_usd": total}
