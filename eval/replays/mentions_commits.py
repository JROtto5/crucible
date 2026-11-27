"""mentions_commits.py N : size/noise check of crucible.mentions on ordinary commits (eval/NOTES 2026-11-27): the last
N non-merge commits of each repo under R (default: the r8base run's TRAIN clones), shuffled with a fixed seed, until
1,000 commits have checked out (the stored clones are partial, so a commit whose blobs aren't local is skipped and
counted as checkout-fail). Prints every listed line, then the totals. No golden data is read."""
import os, sys, subprocess, shutil, tempfile, random, collections
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from crucible import diff as D, mentions as M  # noqa: E402 (after the sys.path line)
N = int(sys.argv[1]); R = os.path.expanduser(os.environ.get("R", "~/rb-work/ReviewBench/.try-agent-r8base/repos"))
repos = sorted(os.listdir(R)); random.Random(20261127).shuffle(repos)
picked, c, fires = [], collections.Counter(), []
for r in repos:
    shas = subprocess.run(["git", "-C", f"{R}/{r}", "rev-list", "--no-merges", f"--max-count={N}", "HEAD"], capture_output=True, text=True).stdout.split()
    picked.append(r)
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", f"{R}/{r}", tmp], check=True)
        for s in shas:
            d = subprocess.run(["git", "-C", tmp, "show", "--format=", "-M", s], capture_output=True, text=True, errors="replace").stdout
            files = D.parse(d)
            if subprocess.run(["git", "-C", tmp, "checkout", "-q", "-f", "--detach", s], capture_output=True).returncode: c["checkout-fail"] += 1; continue
            read = lambda p: open(os.path.join(tmp, p), errors="replace").read() if os.path.isfile(os.path.join(tmp, p)) else ""
            added = {f["path"]: {n for h in f["hunks"] for kk, _, _, n in h["lines"] if kk == "+"} for f in files}
            vals = M.changed_values(files, files)
            rl, _ = M.readers(tmp, vals, added) if vals else ([], {})
            ms = M.missing_paths(tmp, files, read)
            n = sum(1 for x in rl if not x.startswith("(")) + len(ms)
            c["commits"] += 1; c[r] += 1; c["reader lines"] += sum(1 for x in rl if not x.startswith("(")); c["missing lines"] += len(ms)
            if n: fires.append(n)
            for x in rl + ms: print(f"{r[:28]} {s[:8]} {'M' if x in ms else 'R'} {x[:200]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if c["commits"] >= 1000: break
print(picked); print(dict(c)); print("commits firing", len(fires), "dist", sorted(fires))
