"""Map crucible's stored review.json (kept, verified findings) to ReviewBench's findings format."""
import glob, json, os, sys

SEV = ["critical", "important", "medium", "low"]
# No cap by default: every finding here is verified, and the first run's 60-per-PR cap cut PR 1 from 122 to 60.
# RB_CONFIG_MAX_FINDINGS=N caps it again; findings are ordered by severity, so a cap drops the lowest first.
MAX_FINDINGS = int(os.environ.get("RB_CONFIG_MAX_FINDINGS") or 0)


def find_review(home, head):
    paths = glob.glob(os.path.join(home, "reviews", "*", head, "review.json")) or \
        sorted(glob.glob(os.path.join(home, "reviews", "*", "*", "review.json")), key=os.path.getmtime)[-1:]
    return json.load(open(paths[0])) if paths else None


def to_findings(review, agent="crucible", cap=MAX_FINDINGS):
    """Line-anchored findings, most severe first (a stable sort: review.json's own order within a severity). Verified
    nits (the --nits tier) follow the findings of the same severity, so a cap drops nits before findings."""
    rows = [(f, 0) for f in review.get("findings") or []] + [(f, 1) for f in review.get("nits") or []]
    rows.sort(key=lambda r: (SEV.index(r[0]["severity"]) if r[0].get("severity") in SEV else len(SEV), r[1]))
    out = []
    for f, _ in rows:
        path, line = f.get("file"), f.get("line")
        if not path or path == "PR_DRAFT.md" or not isinstance(line, int) or line < 1:
            continue  # PR-text findings and file-level notes have no place in a line-anchored benchmark
        msg = (f.get("title") or "").strip()
        if f.get("problem"):
            msg = f"{msg}: {f['problem'].strip()}" if msg else f["problem"].strip()
        end = f.get("end_line") if isinstance(f.get("end_line"), int) and f.get("end_line") >= line else line
        out.append({"file": path.removeprefix("./"), "start_line": line, "end_line": end,
                    "message": f"[{f.get('severity', 'medium')}] {msg}"[:4000], "producer": agent})
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
    pr = json.load(open(os.environ["RB_PR_JSON"]))
    print(json.dumps({"pr": {"repo": pr.get("repo") or f"https://github.com/{os.environ['RB_NWO']}",
                             "pr_number": int(os.environ["RB_PR_NUMBER"]), "base": os.environ["RB_BASE"], "head": head},
                      "agent": agent, "findings": findings}))


if __name__ == "__main__":
    main(sys.argv[1])
