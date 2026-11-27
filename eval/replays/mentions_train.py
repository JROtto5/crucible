"""mentions_train.py <run> : $0 replay of crucible.mentions on a ReviewBench run's stored diffs (eval/NOTES 2026-11-27).
TRAIN only: refuses any key of the sealed held-out 50 or FINAL 84. Each PR's diff.patch is parsed, a shared clone is
checked out at the PR head, and every listed line is tagged against the golden items at its file within the item's
span +-3 (HIGH-MISSED / high-covered / tp-missed / tp-covered / golden-fp / none). RB: the ReviewBench checkout
(default ~/rb-work/ReviewBench); the run's try-agent work dir must hold repos/ and pr/<key>/diff.patch."""
import json, os, re, subprocess, sys, collections, shutil, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from crucible import diff as D, mentions as M  # noqa: E402 (after the sys.path line)
B = os.path.expanduser(os.environ.get("RB", "~/rb-work/ReviewBench")); run = sys.argv[1]; work = f"{B}/.try-agent-{run}"
sealed = set(json.load(open(f"{B}/corpus/heldout50/SEAL.json"))["keys"]) | set(json.load(open(f"{B}/corpus/final84/SEAL.json"))["keys"])
man = {f"{m['nwo'].replace('/', '_')}_{m['pr_number']}-{m['head'][:8]}": m for m in json.load(open(f"{B}/corpus/manifest.json"))}
c = collections.Counter(); per_pr = []; show = sys.argv[2:]
for e in json.load(open(f"{B}/runs/{run}/scoring/results.details.json")):
    k = e["pr_key"]; assert k not in sealed
    m = man[k]; src = f"{work}/repos/{m['nwo'].replace('/', '_')}"
    files = D.parse(open(f"{work}/pr/{k}/diff.patch", errors="replace").read())
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", src, tmp], check=True)
        subprocess.run(["git", "-C", tmp, "checkout", "-q", "--detach", m["head"]], check=True)
        read = lambda p: open(os.path.join(tmp, p), errors="replace").read() if os.path.isfile(os.path.join(tmp, p)) else ""
        added = {f["path"]: {n for h in f["hunks"] for kk, _, _, n in h["lines"] if kk == "+"} for f in files}
        vals = M.changed_values(files, files)
        rl, picked = M.readers(tmp, vals, added) if vals else ([], {})
        ms = M.missing_paths(tmp, files, read)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    g = json.load(open(f"{B}/golden/{k}.json"))["findings"]
    cov = set()
    for x in e["candidate_findings"]:
        if x["status"].startswith("matched"): cov |= set(x.get("covered_golden_indices") or [])
    n = 0
    for kind, ls in (("reader", rl), ("missing", ms)):
        for ln in ls:
            mm = re.match(r"(.+?):(\d+): ", ln)
            if not mm: c[f"{kind}:summary"] += 1; continue
            n += 1
            p, no = mm[1], int(mm[2])
            hit = [(i, h) for i, h in enumerate(g) if h["file"] == p and int(h["start_line"]) - 3 <= no <= int(h["end_line"]) + 3]
            tag = ("HIGH-MISSED" if any(h["severity"] == "high" and h["tp_fp"] == "tp" and i not in cov for i, h in hit) else
                   "high-covered" if any(h["severity"] == "high" and h["tp_fp"] == "tp" for i, h in hit) else
                   "tp-missed" if any(h["tp_fp"] == "tp" and i not in cov for i, h in hit) else
                   "tp-covered" if any(h["tp_fp"] == "tp" for i, h in hit) else "golden-fp" if hit else "none")
            c[f"{kind}:{tag}"] += 1
            if True:   # every line, for the hand read
                print(f"{k[:34]} {kind} [{tag}] {ln[:230]}")
    per_pr.append(n)
    if True:
        print("== values", k, list(picked)[:12])
for k_, v in sorted(c.items()): print(f"{k_:28} {v}")
print("PRs", len(per_pr), "firing", sum(1 for x in per_pr if x), "lines total", sum(per_pr), "max/PR", max(per_pr),
      "dist", sorted(x for x in per_pr if x))
