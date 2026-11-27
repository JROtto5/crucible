"""mentions_evalcases.py: with CRUCIBLE_MENTIONS=1, how many of eval/cases the note fires on (each case built as evalrun
builds it: base committed on main, then the change tree replacing it). 0 means every eval prompt is byte-identical."""
import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from crucible import diff as D, review as V  # noqa: E402 (after the sys.path line)
C = os.path.join(ROOT, "eval", "cases"); fired = 0
for case in sorted(os.listdir(C)):
    d = tempfile.mkdtemp()
    run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True, text=True).stdout
    shutil.copytree(f"{C}/{case}/base", d, dirs_exist_ok=True)
    run("git", "init", "-q", "-b", "main"); run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base", "--allow-empty")
    run("git", "checkout", "-qb", "fix")
    for x in os.listdir(d):
        if x != ".git": shutil.rmtree(f"{d}/{x}") if os.path.isdir(f"{d}/{x}") else os.remove(f"{d}/{x}")
    shutil.copytree(f"{C}/{case}/change", d, dirs_exist_ok=True)
    run("git", "add", "-A"); run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c", "--allow-empty")
    files = D.parse(run("git", "diff", "-M", "main..fix") + "\n")
    os.environ["CRUCIBLE_MENTIONS"] = "1"
    n = V.mentions_note(d, "fix", files, {"files": [f["path"] for f in files]})
    if n: fired += 1; print("FIRES", case); print(n)
    shutil.rmtree(d)
print("cases", len(os.listdir(C)), "fired", fired)
