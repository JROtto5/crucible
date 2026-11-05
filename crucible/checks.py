"""Run the project's own lint / typecheck / tests before any model call."""
import glob, json, os, re, shutil, subprocess, tempfile
from .util import git, project_dir, read_json

SCRIPT_ORDER = [("lint", ["lint"]), ("typecheck", ["typecheck", "type-check", "tsc", "types", "check-types"]),
                ("test", ["test:unit", "test"])]


def runner(repo):
    """The repo's package manager, if it is installed; otherwise npm (which runs the same package.json scripts)."""
    if os.path.exists(os.path.join(repo, "pnpm-lock.yaml")) and shutil.which("pnpm"):
        return "pnpm"
    if os.path.exists(os.path.join(repo, "yarn.lock")) and shutil.which("yarn"):
        return "yarn"
    return "npm"


def is_monorepo(repo):
    pkg = read_json(os.path.join(repo, "package.json"), {}) or {}
    return any(os.path.exists(os.path.join(repo, n)) for n in ("nx.json", "pnpm-workspace.yaml", "lerna.json", "turbo.json")) \
        or bool(pkg.get("workspaces"))


def package_dirs(repo, paths):
    """Nearest package.json (below the repo root) with scripts, for each changed path. -> sorted relative dirs."""
    out = set()
    for p in paths or []:
        d = os.path.dirname(p)
        while d:
            pkg = read_json(os.path.join(repo, d, "package.json"))
            if pkg is not None:
                if isinstance(pkg.get("scripts"), dict) and pkg["scripts"]:
                    out.add(d)
                break
            d = os.path.dirname(d)
    return sorted(out)


def script_checks(scripts, r, cwd=None, label=""):
    checks = []
    for name, keys in SCRIPT_ORDER:
        for k in keys:
            if k in scripts:
                cmd = f"{r} run {k}" if not (k == "test" and r == "npm") else "npm test"
                c = {"name": (f"{label} " if label else "") + name, "cmd": cmd, "timeout": 900 if name == "test" else 600}
                if cwd:
                    c["cwd"] = cwd
                checks.append(c)
                break
    return checks


def detect(repo, project, paths=None):
    """-> {"checks": [{name, cmd, timeout, cwd?}], "hints": [ci run lines], "source": "..."}
    In a monorepo (nx / pnpm workspaces / lerna / turbo / "workspaces"), the scripts of the packages the change
    touches are used, run in the package directory; the root scripts only as a fallback."""
    cfg = read_json(os.path.join(project_dir(project), "config.json"), {}) or {}
    hints = []
    for wf in glob.glob(os.path.join(repo, ".github", "workflows", "*.y*ml")):
        for line in open(wf, errors="replace"):
            m = re.match(r"\s*-?\s*run:\s*(.+)", line)
            if m and re.search(r"\b(lint|test|tsc|typecheck|check|build)\b", m.group(1)):
                hints.append(f"{os.path.basename(wf)}: {m.group(1).strip()[:160]}")
    if cfg.get("checks"):
        return {"checks": cfg["checks"], "hints": hints[:20], "source": "config.json"}
    checks = []
    pkg = read_json(os.path.join(repo, "package.json"))
    if pkg and is_monorepo(repo):
        r = runner(repo)
        for d in package_dirs(repo, paths):
            sub = read_json(os.path.join(repo, d, "package.json"), {}) or {}
            checks += script_checks(sub.get("scripts") or {}, r, cwd=d, label=os.path.basename(d))
        if checks:
            return {"checks": checks, "hints": hints[:20], "source": "monorepo packages: " + ", ".join(package_dirs(repo, paths))}
    if pkg and isinstance(pkg.get("scripts"), dict):
        checks = script_checks(pkg["scripts"], runner(repo))
    elif os.path.exists(os.path.join(repo, "pyproject.toml")) or os.path.exists(os.path.join(repo, "setup.py")):
        if shutil.which("ruff"):
            checks.append({"name": "lint", "cmd": "ruff check .", "timeout": 300})
        checks.append({"name": "test", "cmd": "python3 -m pytest -q -x", "timeout": 900})
    return {"checks": checks, "hints": hints[:20], "source": "package.json" if pkg else "auto"}


def _run(cmd, cwd, timeout, watch=(), repo=None, rel_cwd=None):
    """watch: paths to look for in the full output (not just the kept tail) -> "mentions"."""
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, CI="1", FORCE_COLOR="0", NO_COLOR="1"))
        out = (r.stdout + "\n" + r.stderr).strip()
        res = {"status": "pass" if r.returncode == 0 else "fail", "code": r.returncode, "tail": out[-2500:]}
    except subprocess.TimeoutExpired as e:
        out = "\n".join(x.decode(errors="replace") if isinstance(x, bytes) else (x or "") for x in (e.stdout, e.stderr))
        res = {"status": "timeout", "code": None, "tail": f"timed out after {timeout}s"}
    if watch and res["status"] != "pass":
        res["mentions"] = mentioned(out, watch, repo, rel_cwd)
    return res


def untracked(repo):
    """Untracked, non-ignored files: scratch scripts, captures, notes. They are not part of the commit under
    review, but a linter or test runner globbing the working tree picks them up (bug h: eslint crashed on an
    untracked .cjs in the repo root and the PR was reported as failing lint)."""
    out = git(repo, "ls-files", "--others", "--exclude-standard", "-z", check=False) or ""
    return [p for p in out.split("\0") if p]


def mentioned(output, paths, repo=None, cwd=None):
    """The untracked paths the output names as a whole path: repo-relative, relative to the check's cwd, or
    absolute, bare or as ./path or file://path. "a.cjs" does not match inside "src/a.cjs" or "a.cjs.map".
    One pass over the output, then set lookups, so thousands of untracked files and a long log stay cheap."""
    named = set()
    for tok in re.findall(r"[\w./@+~-]+", output):
        tok = tok.rstrip(".")
        if tok.startswith("//"):  # file:///abs/path -> //abs/path after the scheme's ':'
            tok = "/" + tok.lstrip("/")
        while tok.startswith("./"):
            tok = tok[2:]
        named.add(tok)
    hits = []
    for p in paths:
        forms = {p}
        if repo:
            forms.add(os.path.join(repo, p))
            if cwd and p.startswith(cwd.rstrip("/") + "/"):
                forms.add(os.path.relpath(p, cwd))
        if forms & named:
            hits.append(p)
    return hits


def deps_present(repo):
    return not os.path.exists(os.path.join(repo, "package.json")) or os.path.isdir(os.path.join(repo, "node_modules"))


def run_all(repo, project, base_sha=None, on_base=False, log=print, paths=None):
    det = detect(repo, project, paths)
    results = []
    if not det["checks"]:
        return {"detected": det, "results": [], "note": "no checks detected; add ~/.crucible/projects/%s/config.json" % project}
    if not deps_present(repo):
        return {"detected": det, "results": [{"name": c["name"], "cmd": c["cmd"], "status": "skipped",
                                               "tail": "dependencies not installed (no node_modules)"} for c in det["checks"]],
                "note": "install dependencies to enable checks"}
    scratch = untracked(repo)
    for c in det["checks"]:
        log(f"  check {c['name']}: {c['cmd']}" + (f" (in {c['cwd']})" if c.get("cwd") else ""))
        res = dict(c, **_run(c["cmd"], os.path.join(repo, c.get("cwd") or ""), c.get("timeout", 600),
                          watch=scratch, repo=repo, rel_cwd=c.get("cwd")))
        named = res.pop("mentions", [])
        if res["status"] in ("fail", "timeout") and named:
            # The failure names files that are not in the commit: judge the commit itself, in a clean checkout.
            log(f"  check {c['name']} {res['status']}s naming untracked file(s) {', '.join(named[:5])}; "
                "re-running on a clean checkout of HEAD")
            clean = run_in_worktree(repo, "HEAD", c)
            if clean["status"] in ("pass", "fail", "timeout"):
                res.update(clean, untracked=named, in_working_tree=res["status"], working_tree_tail=res["tail"][-800:])
            else:
                res["untracked"] = named
        if on_base and base_sha and res["status"] in ("fail", "timeout"):
            res["on_base"] = run_on_base(repo, base_sha, c)
        results.append(res)
    return {"detected": det, "results": results}


def link_deps(repo, wt, cwd=None):
    """Share the installed node_modules (root, and the check's package in a monorepo) with a worktree.
    A path that already exists in the worktree is left alone: a commit can track node_modules/ entries,
    and symlinking over them used to fail with "[Errno 17] File exists" (bug f)."""
    for rel in dict.fromkeys(["", cwd or ""]):
        src = os.path.join(repo, rel, "node_modules")
        dst = os.path.join(wt, rel, "node_modules")
        if os.path.isdir(src) and os.path.isdir(os.path.dirname(dst)) and not os.path.lexists(dst):
            os.symlink(src, dst)


def run_in_worktree(repo, rev, check):
    """Run one check in a throwaway worktree of rev (tracked files only, plus the shared node_modules).
    -> _run's result, or {"status": "error: ..."} if the worktree could not be made."""
    wt = tempfile.mkdtemp(prefix="crucible-wt-")
    try:
        git(repo, "worktree", "add", "--detach", wt, rev)
        link_deps(repo, wt, check.get("cwd"))
        return _run(check["cmd"], os.path.join(wt, check.get("cwd") or ""), check.get("timeout", 600))
    except Exception as e:  # noqa: BLE001 - recorded, not fatal
        return {"status": f"error: {e}"}
    finally:
        git(repo, "worktree", "remove", "--force", wt, check=False)
        shutil.rmtree(wt, ignore_errors=True)


def run_on_base(repo, base_sha, check):
    """Is a failure pre-existing? Run the same check in a throwaway worktree of the base. -> its status."""
    return run_in_worktree(repo, base_sha, check)["status"]


def facts(checks):
    """Failures as plain facts for the reviewer prompt."""
    lines = []
    for r in checks.get("results", []):
        if r["status"] in ("fail", "timeout"):
            pre = f" (also fails on base: {r['on_base']})" if r.get("on_base") else ""
            if r.get("in_working_tree"):
                pre += (f" (on a clean checkout of HEAD: the working-tree run named untracked files not in this commit, "
                        f"{', '.join(r['untracked'][:5])}, so it was re-run with tracked files and node_modules only; "
                        "a missing gitignored file such as .env or generated code can also cause this failure)")
            elif r.get("untracked"):
                pre += f" (output names untracked files not in this commit: {', '.join(r['untracked'][:5])}; " \
                       "a clean re-run could not be made)"
            lines.append(f"- `{r['cmd']}` {r['status'].upper()}{pre}. Output tail:\n```\n{r['tail'][-1500:]}\n```")
        else:
            note = f" (failed in the working tree only, on untracked files {', '.join(r['untracked'][:5])})" \
                if r.get("untracked") else ""
            lines.append(f"- `{r['cmd']}`: {r['status']}{note}")
    return "\n".join(lines) or "(no project checks were run)"
