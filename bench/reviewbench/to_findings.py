"""Map crucible's stored review.json (kept, verified findings) to ReviewBench's findings format."""
import glob, json, os, sys

home = sys.argv[1]
head = os.environ["RB_HEAD"]
paths = [p for p in glob.glob(os.path.join(home, "reviews", "*", head, "review.json"))] or \
        sorted(glob.glob(os.path.join(home, "reviews", "*", "*", "review.json")), key=os.path.getmtime)[-1:]
findings = []
if paths:
    d = json.load(open(paths[0]))
    for f in d.get("findings") or []:
        path, line = f.get("file"), f.get("line")
        if not path or path == "PR_DRAFT.md" or not isinstance(line, int) or line < 1:
            continue  # PR-text findings and file-level notes have no place in a line-anchored benchmark
        msg = (f.get("title") or "").strip()
        if f.get("problem"):
            msg = f"{msg}: {f['problem'].strip()}" if msg else f["problem"].strip()
        end = f.get("end_line") if isinstance(f.get("end_line"), int) and f.get("end_line") >= line else line
        findings.append({"file": path.removeprefix("./"), "start_line": line, "end_line": end,
                         "message": f"[{f.get('severity', 'medium')}] {msg}"[:4000], "producer": os.environ.get("RB_AGENT", "crucible")})
    print(f"kept {len(findings)} of {len(d.get('findings') or [])} findings; cost ${d.get('cost_usd', 0):.2f}", file=sys.stderr)
pr = json.load(open(os.environ["RB_PR_JSON"]))
print(json.dumps({"pr": {"repo": pr.get("repo") or f"https://github.com/{os.environ['RB_NWO']}",
                         "pr_number": int(os.environ["RB_PR_NUMBER"]), "base": os.environ["RB_BASE"], "head": head},
                  "agent": os.environ.get("RB_AGENT", "crucible"), "findings": findings[:60]}))
