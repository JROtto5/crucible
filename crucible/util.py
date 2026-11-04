"""Shared helpers: git, state paths, the model call, budget tracking."""
import hashlib, json, os, re, subprocess, threading

HOME = os.path.expanduser(os.environ.get("CRUCIBLE_HOME", "~/.crucible"))

MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5", "fable": "claude-fable-5-1"}
PREFERENCE = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"]

SEV = ["critical", "important", "medium", "low"]
BLOCKING = {"critical", "important"}

TEST_PATH_RX = re.compile(r"(^|/)(tests?|__tests__|spec|specs|fixtures?|testdata|__fixtures__|__mocks__)(/|$)|"
                          r"\.(test|spec)\.[cm]?[jt]sx?$|_test\.(py|go)$|(^|/)test_[^/]+\.py$")
CODE_EXT_RX = re.compile(r"\.(c|cc|cpp|h|hpp|cs|go|java|kt|rs|swift|py|rb|php|[cm]?[jt]sx?|vue|svelte|glsl|wgsl|frag|vert)$")


class Failed(Exception):
    """A review step failed in a way that must be recorded, not crash."""


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Failed(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def ref_exists(repo, ref):
    return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                          capture_output=True).returncode == 0


def remote_slug(repo, remote):
    url = git(repo, "remote", "get-url", remote, check=False)
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url) or re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def upstream_slug(repo):
    """owner/name of the project the change is FOR (upstream remote wins over origin)."""
    remotes = git(repo, "remote", check=False).split()
    for r in ("upstream", "origin"):
        if r in remotes and remote_slug(repo, r):
            return remote_slug(repo, r)
    return None


def project_key(repo):
    slug = upstream_slug(repo)
    return (slug or os.path.basename(os.path.abspath(repo))).replace("/", "__")


def default_base(repo):
    """upstream/<default> > origin/<default> > local main/master/dev. Returns a ref name."""
    remotes = git(repo, "remote", check=False).split()
    for r in [x for x in ("upstream", "origin") if x in remotes]:
        head = git(repo, "symbolic-ref", "--quiet", f"refs/remotes/{r}/HEAD", check=False)
        if head:
            return head.replace("refs/remotes/", "")
        for b in ("main", "master", "dev", "develop", "next"):
            if ref_exists(repo, f"{r}/{b}"):
                return f"{r}/{b}"
    for b in ("main", "master", "dev", "develop"):
        if ref_exists(repo, b):
            return b
    raise Failed("could not find a base branch; pass --base")


def is_dirty(repo):
    return bool(git(repo, "status", "--porcelain", "--untracked-files=no", check=False))


def project_dir(project):
    d = os.path.join(HOME, "projects", project)
    os.makedirs(d, exist_ok=True)
    return d


def review_dir(project, sha):
    d = os.path.join(HOME, "reviews", project, sha)
    os.makedirs(d, exist_ok=True)
    return d


def norm_words(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def stable_id(file, title):
    h = hashlib.sha1((file + "|" + " ".join(norm_words(title))).encode()).hexdigest()[:8]
    return f"CR-{h}"


def read_json(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def exclude_locally(repo, names=("PR_DRAFT.md", "PR_DRAFT.polished.md", "PR_DRAFT.polish-notes.md", "PR.diff", "PREP.md", "REPLIES.md")):
    """Keep crucible's working files out of the contributor's commits."""
    gd = git(repo, "rev-parse", "--git-dir", check=False)
    if not gd:
        return
    p = os.path.join(repo if not os.path.isabs(gd) else "", gd, "info", "exclude")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    have = open(p).read() if os.path.exists(p) else ""
    add = [n for n in names if n not in have.split("\n")]
    if add:
        with open(p, "a") as fh:
            fh.write(("\n" if have and not have.endswith("\n") else "") + "\n".join(add) + "\n")


class Budget:
    def __init__(self, limit):
        self.limit, self.spent, self.lock = limit, 0.0, threading.Lock()

    def remaining(self):
        return None if self.limit is None else max(0.0, self.limit - self.spent)

    def add(self, c):
        with self.lock:
            self.spent += c or 0

    def exhausted(self):
        return self.limit is not None and self.spent >= self.limit


TOOLS_READ = ["Read", "Grep", "Glob", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git grep:*)",
              "Bash(git blame:*)", "Bash(ls:*)"]
TOOLS_RUN = TOOLS_READ + ["Bash(node:*)", "Bash(npx vitest:*)", "Bash(npx jest:*)", "Bash(npx mocha:*)",
                          "Bash(npm test:*)", "Bash(npm run test:*)", "Bash(pytest:*)", "Bash(python3 -m pytest:*)"]


def claude(prompt, model, schema, cwd, budget=None, tools=TOOLS_READ, effort="high", timeout=1500):
    """One isolated, structured model call. Raises Failed on any problem."""
    if budget and budget.exhausted():
        raise Failed("budget exhausted")
    env = dict(os.environ)
    if os.environ.get("CRUCIBLE_CLAUDE_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(os.environ["CRUCIBLE_CLAUDE_DIR"])
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--output-format", "json",
           "--json-schema", json.dumps(schema), "--no-session-persistence",
           # never load the checked-out project's settings/hooks or the user's MCP servers
           "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--permission-mode", "default"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    else:
        cmd += ["--tools", ""]
    if budget and budget.remaining() is not None:
        cmd += ["--max-budget-usd", f"{max(budget.remaining(), 0.01):.2f}"]
    # prompt goes on stdin: --allowedTools is variadic and would swallow a trailing positional prompt
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failed(f"model call timed out after {timeout}s")
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise Failed(f"model call failed: {(r.stderr or r.stdout)[-500:]}")
    if budget:
        budget.add(d.get("total_cost_usd", 0))
    if d.get("is_error") or "structured_output" not in d:
        raise Failed(f"model call failed ({d.get('subtype')}): {str(d.get('result'))[:500]}")
    return d["structured_output"], d.get("total_cost_usd", 0)


def gh_json(*args, check=False):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        if check:
            raise Failed(f"gh api {' '.join(args)}: {r.stderr.strip()[:300]}")
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None
