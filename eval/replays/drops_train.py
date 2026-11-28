"""drops_train.py <run> : $0 read of a ReviewBench run's stored verifier drops against the high items it missed
(eval/NOTES 2026-11-28). TRAIN only: refuses any key of the sealed held-out 50 or FINAL 84. For each high golden TP item
the run's judge output leaves uncovered, prints the item and every finding or nit the verifier dropped in the same file
(the matcher is file-scoped, so a drop in another file can't be credited), with the stored verdict. Same-claim is then
read by hand. RB: the ReviewBench checkout (default ~/rb-work/ReviewBench); review.json is read from .try-agent-<run>."""
import json, os, sys
B = os.path.expanduser(os.environ.get("RB", "~/rb-work/ReviewBench")); run = sys.argv[1]; work = f"{B}/.try-agent-{run}"
sealed = set(json.load(open(f"{B}/corpus/heldout50/SEAL.json"))["keys"]) | set(json.load(open(f"{B}/corpus/final84/SEAL.json"))["keys"])
cov = {}
for p in json.load(open(f"{B}/runs/{run}/scoring/results.details.json")):
    assert p["pr_key"] not in sealed, p["pr_key"]
    s = cov.setdefault(p["pr_key"], set())
    for c in p["candidate_findings"]:
        s |= set(c.get("covered_golden_indices") or [])
nmiss = ndrop = noreview = 0
for k in sorted(cov):
    g = json.load(open(f"{B}/golden/{k}.json"))["findings"]
    miss = [(i, x) for i, x in enumerate(g)
            if x.get("tp_fp") == "tp" and str(x.get("severity", "")).lower() == "high" and i not in cov[k]]
    if not miss:
        continue
    rj = f"{work}/out/{k}/review.json"
    if not os.path.isfile(rj):
        noreview += 1
    d = json.load(open(rj)) if os.path.isfile(rj) else {}
    drops = [("F", y) for y in d.get("dropped") or []] + [("N", y) for y in d.get("nits_dropped") or []]
    for i, x in miss:
        nmiss += 1
        print(f"\n### {k} #{i} [{x.get('category')}] {x.get('file')}:{x.get('start_line')}-{x.get('end_line')}")
        print("   GOLD:", (x.get("message") or "")[:400].replace("\n", " "))
        for kind, y in drops:
            if y.get("file") == x.get("file"):
                ndrop += 1
                v = y.get("verification") or {}
                print(f"   DROP[{kind}] {y.get('severity')} {y['file']}:{y.get('line')} {(y.get('title') or '')[:120]}")
                print(f"      {v.get('status')} {v.get('method')} conf={v.get('confidence')} :: {(v.get('evidence') or '')[:500]}")
print(f"\n{run}: high missed {nmiss}, same-file drops {ndrop}, missed-item PRs with no review.json {noreview}")
