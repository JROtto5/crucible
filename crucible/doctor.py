"""`crucible doctor`: what a new install is missing (Python, git, the Claude Code CLI and its login, gh, the state dir).

Nothing here calls a model unless --live is given: then one tiny call per model a review would use, which proves
the account can reach it (a few cents)."""
import json, os, re, shutil, subprocess, sys, tempfile

from . import util

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
# flags util.claude passes on every call: a CLI without one of them fails every review
CLI_FLAGS = ("--json-schema", "--setting-sources", "--strict-mcp-config", "--no-session-persistence", "--effort",
             "--max-budget-usd", "--permission-mode")
FABLE_MIN = (2, 1, 290)              # util.py's fallback note: Fable needs this CLI or newer
GIT_MIN = (2, 28)                    # `crucible demo` (init -b, --object-format)
INSTALL = "https://docs.claude.com/en/docs/claude-code/setup"


def _run(cmd, env=None, timeout=30):
    """-> (returncode, stdout + stderr); 127 when the program is missing, 124 on timeout."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _version(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x) for x in m.groups(default="0")) if m else None


def _claude_env(env):
    e = dict(env)
    if env.get("CRUCIBLE_CLAUDE_DIR"):
        e["CLAUDE_CONFIG_DIR"] = os.path.expanduser(env["CRUCIBLE_CLAUDE_DIR"])
    return e


def check(run=_run, which=shutil.which, env=None, home=None):
    """-> [(status, what, detail)], in the order a new user should fix them."""
    env = os.environ if env is None else env
    rows = []
    py = sys.version_info
    rows.append((OK if py >= (3, 10) else FAIL, "python", f"{py.major}.{py.minor}.{py.micro}"
                 + ("" if py >= (3, 10) else ": crucible needs 3.10 or newer")))

    if not which("git"):
        rows.append((FAIL, "git", "not found on PATH: install git"))
    else:
        v = _version(run(["git", "--version"])[1])
        vs = ".".join(map(str, v)) if v else "version unknown"
        rows.append((OK, "git", vs) if v and v[:2] >= GIT_MIN else
                    (WARN, "git", f"{vs}: `crucible demo` needs {GIT_MIN[0]}.{GIT_MIN[1]} or newer"))
        name = run(["git", "config", "user.name"])[1].strip()
        email = run(["git", "config", "user.email"])[1].strip()
        rows.append((OK, "git identity", f"{name} <{email}>") if name and email else
                    (WARN, "git identity", "user.name / user.email not set: you'll need them to commit your change "
                                           "(`git config --global user.name ...`)"))

    claude = which("claude")
    if not claude:
        rows.append((FAIL, "Claude Code CLI", f"`claude` not found on PATH: install it ({INSTALL})"))
    else:
        cenv = _claude_env(env)
        rc, out = run(["claude", "--version"], env=cenv)
        v = _version(out)
        vs = ".".join(map(str, v)) if v else "version unknown"
        helptext = run(["claude", "--help"], env=cenv)[1] if rc == 0 else ""
        missing = [f for f in CLI_FLAGS if f not in helptext]
        if rc != 0:
            rows.append((FAIL, "Claude Code CLI", f"`claude --version` failed ({rc}): {out.strip()[:200]}"))
        elif missing:
            rows.append((FAIL, "Claude Code CLI", f"{vs} at {claude} lacks {', '.join(missing)}: update it "
                                                  "(`claude update` or reinstall)"))
        else:
            note = "" if v and v >= FABLE_MIN else (f"; Fable 5.2 needs {'.'.join(map(str, FABLE_MIN))}+ (its calls "
                                                    "move to Opus on this one)")
            rows.append((OK if not note else WARN, "Claude Code CLI", f"{vs} at {claude}{note}"))
        rows.append(_auth(run, cenv))

    if not which("gh"):
        rows.append((WARN, "gh", "not found: optional, for `learn`, `reply` and the issue/open-PR readiness "
                                 "checks (`--offline` skips them)"))
    else:
        rc, out = run(["gh", "auth", "status"])
        rows.append((OK, "gh", "logged in") if rc == 0 else
                    (WARN, "gh", "not logged in: `gh auth login` (optional; `--offline` skips the GitHub lookups)"))

    home = home or util.HOME
    try:
        os.makedirs(home, exist_ok=True)
        tempfile.TemporaryFile(dir=home).close()
        rows.append((OK, "state dir", home))
    except OSError as e:
        rows.append((FAIL, "state dir", f"{home} is not writable ({e.strerror}); set CRUCIBLE_HOME"))
    return rows


def _auth(run, env):
    for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        if env.get(k):
            return OK, "Claude login", f"{k} is set"
    rc, out = run(["claude", "auth", "status"], env=env)
    try:
        d = json.loads(out[out.index("{"):]) if "{" in out else None
    except ValueError:
        d = None
    if isinstance(d, dict) and "loggedIn" in d:
        if d["loggedIn"]:
            return OK, "Claude login", f"logged in ({d.get('authMethod') or 'unknown method'})"
        return FAIL, "Claude login", "not logged in: run `claude` once and log in, or set ANTHROPIC_API_KEY"
    return WARN, "Claude login", "couldn't tell (`claude auth status` gave no answer); `crucible doctor --live` checks it"


def live(models, call=None):
    """One tiny structured call per model. -> [(status, what, detail)]. call(prompt, model, schema, cwd) is
    util.claude's signature (tests stub it)."""
    # _claude_once, not claude(): a Fable probe refused for a limit must show as a failure, not quietly answer as Opus
    call = call or (lambda p, m, s, cwd: util._claude_once(p, m, s, cwd, None, None, "low", 180, "doctor"))
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    rows = []
    for m in models:
        try:
            _, cost = call('Reply with {"ok": true}.', m, schema, tempfile.gettempdir())
            rows.append((OK, f"model {m}", f"answered (${cost or 0:.4f})"))
        except util.Failed as e:
            rows.append((FAIL, f"model {m}", str(e)[:300]))
    return rows


def default_models():
    """The models a review with no known author uses: reviewer, strong verifier, cheap verifier (review.py's own
    choice, so --live probes what a review would call)."""
    from . import review
    return list(dict.fromkeys(m for m in (*review.pick_models(set()), review.cheap_model()) if m))


def report(rows):
    width = max(len(w) for _, w, _ in rows)
    lines = [f"{MARK[s]} {w.ljust(width)}  {d}" for s, w, d in rows]
    bad = sum(s == FAIL for s, _, _ in rows)
    lines.append("")
    lines.append(f"{bad} problem(s) to fix before `crucible review` can run." if bad else
                 "Ready: try `crucible demo` and `crucible review crucible-demo --offline --budget 1`.")
    return "\n".join(lines)
