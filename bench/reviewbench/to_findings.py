"""Map crucible's stored review.json (kept, verified findings) to ReviewBench's findings format."""
import glob, json, os, re, sys

SEV = ["critical", "important", "medium", "low"]
# No cap by default: every finding here is verified, and the first run's 60-per-PR cap cut PR 1 from 122 to 60.
# RB_CONFIG_MAX_FINDINGS=N caps it again; findings are ordered by severity, so a cap drops the lowest first.
MAX_FINDINGS = int(os.environ.get("RB_CONFIG_MAX_FINDINGS") or 0)


# Same wording as crucible.util.LIMIT_RX (a test checks they match; this file runs without crucible on the path).
LIMIT_RX = re.compile(r"hit your [\w -]*limit|spend limit|usage limit", re.I)
# A model call's own failure as crucible records it ("model call failed (success): You've hit your monthly spend limit").
# Only those count: a salvaged verdict's reason carries the verifier's prose, which can say "usage limit" about the code.
FAILED_CALL = "model call failed"
LIMIT_EXIT = 3


def limit_reasons(node, key=None):
    """Every model-call failure in a review.json that names an account spend/usage limit. model_fallbacks is skipped:
    a call that moved to another model after a limit did run. ReviewBench run 3 scored PR 13 (every pass refused) and
    PR 1 (some passes refused) as finished reviews with 0.00 recall; a reason found here makes the PR fail instead."""
    if key == "model_fallbacks":
        return []
    if isinstance(node, dict):
        return [r for k, v in node.items() for r in limit_reasons(v, k)]
    if isinstance(node, list):
        return [r for v in node for r in limit_reasons(v, key)]
    if key == "reason" and isinstance(node, str) and FAILED_CALL in node and LIMIT_RX.search(node):
        return [node]
    return []


def not_run(review):
    """Why the review didn't run at all, or None. R4's first launch had an empty credential: every pass failed with
    $0 spent, crucible exited 1, and all 25 PRs still reported "passed" with whatever the cheap tier left."""
    if not review:
        return "no review.json"
    if review.get("status") != "done":
        return f"review {review.get('status')}: {str(review.get('reason'))[:160]}"
    chunks = (review.get("coverage") or {}).get("chunks") or []
    if chunks and not any(c.get("status") == "reviewed" for c in chunks):
        return f"no pass was reviewed ({str(chunks[0].get('reason'))[:160]})"
    return None


def find_review(home, head):
    paths = glob.glob(os.path.join(home, "reviews", "*", head, "review.json")) or \
        sorted(glob.glob(os.path.join(home, "reviews", "*", "*", "review.json")), key=os.path.getmtime)[-1:]
    return json.load(open(paths[0])) if paths else None


def same_flaw(f, g, path, line):
    """g (a kept item, or one whose site row was already written) reports f's flaw: it is f, it has f's title, or it
    lists f's own place among its sites."""
    t = lambda x: " ".join((x.get("title") or "").lower().split())
    return g is f or t(g) == t(f) or f"{path}:{line}" in (g.get("also_at") or [])


def to_findings(review, agent="crucible", cap=MAX_FINDINGS):
    """Line-anchored findings, most severe first (a stable sort: review.json's own order within a severity). Verified
    nits (the --nits tier) follow the findings of the same severity, so a cap drops nits before findings."""
    rows = [(f, 0) for f in review.get("findings") or []] + [(f, 1) for f in review.get("nits") or []]
    rows.sort(key=lambda r: (SEV.index(r[0]["severity"]) if r[0].get("severity") in SEV else len(SEV), r[1]))
    out = []
    own = {}                                    # (path, line) -> what the kept items there say (see same_flaw)
    for f, _ in rows:
        own.setdefault((str(f.get("file") or "").removeprefix("./"), f.get("line")), []).append(f)
    for f, _ in rows:
        path, line = f.get("file"), f.get("line")
        if not path or path == "PR_DRAFT.md" or not isinstance(line, int) or line < 1:
            continue  # PR-text findings and file-level notes have no place in a line-anchored benchmark
        path = path.removeprefix("./")
        msg = (f.get("title") or "").strip()
        if f.get("problem"):
            msg = f"{msg}: {f['problem'].strip()}" if msg else f["problem"].strip()
        end = f.get("end_line") if isinstance(f.get("end_line"), int) and f.get("end_line") >= line else line
        out.append({"file": path, "start_line": line, "end_line": end,
                    "message": f"[{f.get('severity', 'medium')}] {msg}"[:4000], "producer": agent})
        # the verified other sites of the same flaw (crucible's also_at), each at its own line, unless a kept item
        # there already reports this flaw. Another flaw on the same line is a second comment: run 6 had "a switch drops
        # unsaved tabs" at the call site where "a switch cancels the pending save" also held, and they are two issues.
        for site in f.get("also_at") or []:
            p, _, n = site.rpartition(":")
            if p and n.isdigit() and int(n) >= 1 and not any(same_flaw(f, g, path, line) for g in own.get((p, int(n)), ())):
                own.setdefault((p, int(n)), []).append(f)
                out.append({"file": p, "start_line": int(n), "end_line": int(n), "producer": agent,
                            "message": f"[{f.get('severity', 'medium')}] {f.get('title', '').strip()} (same flaw as "
                                       f"{path}:{line}): {(f.get('problem') or '').strip()}"[:4000]})
    return out[:cap] if cap > 0 else out


def main(home):
    head, agent = os.environ["RB_HEAD"], os.environ.get("RB_AGENT", "crucible")
    review = find_review(home, head)
    findings = []
    if review:
        findings = to_findings(review, agent)
        n, nits = len(review.get("findings") or []), len(review.get("nits") or [])
        print(f"kept {len(findings)} of {n} findings + {nits} nits; cost ${review.get('cost_usd', 0):.2f} "
              f"(nits ${review.get('cost_nits_usd', 0):.2f})", file=sys.stderr)
    hit = limit_reasons(review) if review else []
    if hit:
        print(f"FAILED: {len(hit)} step(s) ended on an account limit ({hit[0][:160]}); rerun this PR", file=sys.stderr)
    why = not_run(review)
    if why:
        print(f"FAILED: {why}; rerun this PR", file=sys.stderr)
    pr = json.load(open(os.environ["RB_PR_JSON"]))
    print(json.dumps({"pr": {"repo": pr.get("repo") or f"https://github.com/{os.environ['RB_NWO']}",
                             "pr_number": int(os.environ["RB_PR_NUMBER"]), "base": os.environ["RB_BASE"], "head": head},
                      "agent": agent, "findings": findings}))
    return LIMIT_EXIT if hit or why else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
