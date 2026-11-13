"""Docs and comments outside the diff that mention what the change touched ($0: git grep, no model call).

ReviewBench run 3 found 25.0% of its golden documentation issues. A stale README section, a docstring in another
module or a guide that still shows the old flag lives in a file the diff never shows, so the reviewer, working pass
by pass from the diff, rarely opens it. This lists those lines for the --nits review prompt: the names whose
definition the change edits or removes, the functions its hunks sit in (a behaviour change keeps the signature), and
the CLI flags and environment variables on its removed lines, each searched as a whole word in the docs and in
comment lines of other code. The reviewer still judges whether each line is stale; nothing here is a finding.
"""
import os
import re

from .util import CODE_EXT_RX, TEST_PATH_RX, git

# a definition at any indent: docs name methods as often as top-level functions
DEF_RX = {
    ".py": re.compile(r"^\s*(?:async\s+def|def|class)\s+(\w+)"),
    ".rb": re.compile(r"^\s*(?:def\s+(?:self\.)?|class\s+|module\s+)([\w?!]+)"),
    ".go": re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)|^type\s+(\w+)"),
    ".rs": re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+)?(?:fn|struct|enum|trait)\s+(\w+)"),
    ".js": re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:(?:async\s+)?function\s*\*?\s*|(?:abstract\s+)?class\s+"
                      r"|(?:interface|type|enum)\s+)(\w+)|^\s*export\s+(?:const|let|var)\s+(\w+)"
                      r"|^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*(\w+)\s*\([^)]*\)\s*(?::[^{]*)?\{\s*$"),
}
for _e in (".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"):
    DEF_RX[_e] = DEF_RX[".js"]
# a long flag or an environment variable, as it appears in a string on a removed line
FLAG_RX = re.compile(r"""["'`](--[a-z][a-z0-9]*(?:-[a-z0-9]+)+|--[a-z]{4,})(?:=|["'`])""")
ENV_RX = re.compile(r"""["'`]([A-Z][A-Z0-9]*_[A-Z0-9_]{2,})["'`]""")
# control flow that the method alternative of the JS pattern would otherwise read as a method named "if"
NOT_NAMES = {"if", "for", "while", "switch", "catch", "function", "return", "constructor", "super"}
GENERIC = {"main", "init", "setup", "teardown", "setUp", "tearDown", "initialize", "default", "render", "update",
           "handle", "process", "create", "build", "parse", "start", "stop", "close", "open", "test", "value",
           "config", "options", "get", "set", "run", "call", "apply", "toString", "constructor"}
# docs search: prose files anywhere. Release notes are left out: their old entries are meant to describe old behaviour.
DOC_GLOBS = ("*.md", "*.mdx", "*.rst", "*.adoc", "*.txt", "*README", "*README.*")
HISTORY_RX = re.compile(r"(?:^|/)(?:CHANGELOG|CHANGES|HISTORY|NEWS|RELEASE[-_]?NOTES)[^/]*$|(?:^|/)changelog\.d/|"
                        r"(?:^|/)(?:LICENSE|COPYING|NOTICE|requirements[^/]*\.txt|CMakeLists\.txt)$", re.I)
COMMENT_RX = re.compile(r"^\s*(?:#(?!include|define|if|end|pragma|!)|//|/?\*|<!--|--\s|\"\"\"|''')")
MAX_NAMES = 12            # most specific names first (longest), so a big diff doesn't search 200 words
MAX_PER_NAME = 6          # a name mentioned more often than this is common prose ("timeout"): say how often, not where
MAX_LINES = 30
LINE_CHARS = 160


def _name_ok(n):
    return n and len(n) >= 4 and n not in GENERIC and n not in NOT_NAMES and not (n.startswith("__") and n.endswith("__"))


def _defs(path, text):
    rx = DEF_RX.get(os.path.splitext(path)[1].lower())
    m = rx.match(text) if rx else None
    return [g for g in (m.groups() if m else ()) if _name_ok(g)]


# a class's parentheses hold its bases (or a metaclass keyword), not parameters
CLASS_RX = re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\b")
PARAM_RX = re.compile(r"(?:^|[(,])\s*\**(\w+)\s*(?::\s*[^=,()]+?)?\s*(?:=\s*([^,()]+?))?\s*(?=[,)])")


def _params(text):
    """{name: default or None} from the argument list of a definition line that closes on the line."""
    m = re.search(r"\((.*)\)", text)
    return {n: (d or "").strip() for n, d in PARAM_RX.findall("(" + m.group(1) + ")")} if m else {}


def _enclosing(lines, n, rx):
    """The nearest definition at or above 1-based line n, at a smaller indent than the changed line when there is one."""
    if not rx or not lines:
        return None
    n = min(n, len(lines))
    ind = len(lines[n - 1]) - len(lines[n - 1].lstrip())
    for i in range(n - 1, -1, -1):
        m = rx.match(lines[i])
        if m and (i == n - 1 or len(lines[i]) - len(lines[i].lstrip()) < ind or not lines[n - 1].strip()):
            return next((g for g in m.groups() if g), None)
    return None


def touched_names(files, read_new):
    """{name: why} for a parsed diff (crucible.diff.parse). read_new(path) -> the file's text at HEAD, or None."""
    out = {}
    for f in files:
        path = f.get("path") or ""
        # a test's names aren't documented anywhere (40 real commits, 2026-11-13: test_* names were the noise)
        if f.get("binary") or not CODE_EXT_RX.search(path) or f.get("added") or TEST_PATH_RX.search(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        removed_defs = set()
        for h in f.get("hunks") or []:
            new_params = {}                 # {def name: its parameters} on this hunk's added lines
            for k, t, *_ in h["lines"]:
                if k == "+" and re.search(r"\(.*\)", t) and not CLASS_RX.match(t):
                    for n in _defs(path, t):
                        new_params[n] = _params(t)
            for k, t, *_ in h["lines"]:
                if k == "-":
                    for n in _defs(path, t):
                        removed_defs.add(n)
                        # a parameter renamed, dropped or given a new default: docs quote it with the old one
                        # (only against the same definition re-added with its argument list on one line: a
                        # deleted function is named itself, and a reflowed one can't be compared)
                        for pn, d in (_params(t).items() if n in new_params and not CLASS_RX.match(t) else ()):
                            if _name_ok(pn) and pn not in ("self", "cls") and new_params[n].get(pn) != d:
                                out.setdefault(pn, f"parameter of {n} renamed, removed or re-defaulted in {path}")
                    for n in FLAG_RX.findall(t):
                        out.setdefault(n, f"flag on a removed line of {path}")
                    for n in ENV_RX.findall(t):
                        out.setdefault(n, f"environment variable on a removed line of {path}")
        for n in removed_defs:
            out.setdefault(n, f"definition changed or removed in {path}")
        if f.get("deleted"):
            continue
        text = read_new(path)
        lines = text.split("\n") if text else []
        for h in f.get("hunks") or []:
            # one hunk can span two functions (3 lines of context merge nearby edits), so each edited spot counts
            spots, hl = set(), h["lines"]
            for i, (k, _t, _o, nn) in enumerate(hl):
                if k == "+":
                    spots.add(nn)
                elif k == "-" and (i == 0 or hl[i - 1][0] != "-"):   # a removal: the next new line sits where it was
                    nxt = next((x[3] for x in hl[i + 1:] if x[3]), None)
                    if nxt:
                        spots.add(nxt)
            for n in sorted(spots):
                name = _enclosing(lines, n, DEF_RX.get(ext))
                if _name_ok(name):
                    out.setdefault(name, f"{path} changes inside it")
    return out


def _grep(repo, names, pathspecs):
    if not names:
        return []
    args = ["grep", "-n", "-I", "-w", "-F", "--no-color"]
    for n in names:
        args += ["-e", n]
    try:
        raw = git(repo, *args, "--", *pathspecs, check=False)
    except Exception:
        return []
    out = []
    for ln in raw.splitlines():
        p, _, rest = ln.partition(":")
        no, _, text = rest.partition(":")
        if no.isdigit():
            out.append((p, int(no), text))
    return out


TRIPLE_RX = re.compile(r'"""|\'\'\'')


def _in_prose(repo, path, cache):
    """Line numbers of path (at the checkout) inside a docstring or a block comment: a docstring's body lines carry
    no comment marker, and that is where Python documents parameters and behaviour."""
    if path not in cache:
        lines, out = set(), set()
        try:
            with open(os.path.join(repo, path), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        py = path.endswith(".py")
        inside = None                   # the open delimiter, while in a docstring or block comment
        for no, ln in enumerate(text.split("\n"), 1):
            if inside:
                out.add(no)
            for m in (TRIPLE_RX.finditer(ln) if py else re.finditer(r"/\*|\*/", ln)):
                d = m.group(0)
                if inside is None and d != "*/":
                    inside = d
                elif inside is not None and (d == inside or (inside == "/*" and d == "*/")):
                    inside = None
        cache[path] = out
    return cache[path]


def mentions(repo, files, read_new, changed_lines=None):
    """-> (lines, names): ["path:line: text"] outside the change's own +/- lines that mention a touched name, and the
    names searched. changed_lines: {path: set(new line numbers)} the diff added, which the reviewer already sees."""
    names = touched_names(files, read_new)
    if not names:
        return [], {}
    picked = sorted(names, key=lambda n: (-len(n), n))[:MAX_NAMES]
    changed_lines = changed_lines or {}
    hits = [(p, no, t, True) for p, no, t in _grep(repo, picked, list(DOC_GLOBS)) if not HISTORY_RX.search(p)]
    code_specs = [f"*.{e}" for e in ("py", "rb", "go", "rs", "js", "mjs", "cjs", "jsx", "ts", "tsx", "java", "kt",
                                     "c", "cc", "cpp", "h", "hpp", "cs", "swift", "php")]
    spans = {}
    for p, no, t in _grep(repo, picked, code_specs):
        if COMMENT_RX.match(t) or no in _in_prose(repo, p, spans):
            hits.append((p, no, t, False))
    by_name, out, seen = {n: [] for n in picked}, [], set()
    for p, no, t, _doc in hits:
        if no in changed_lines.get(p, ()) or (p, no) in seen:
            continue
        found = [n for n in picked if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", t)]
        if found:                       # listed once, under its first name, tagged with every name it mentions
            by_name[found[0]].append((p, no, t, found))
            seen.add((p, no))
    common = []
    for n in picked:
        hs = by_name[n]
        if len(hs) > MAX_PER_NAME:
            common.append(f"{n} ({len(hs)} lines)")
            continue
        for p, no, t, found in hs:
            t = t.strip()
            out.append(f"{p}:{no}: {t[:LINE_CHARS] + (' ...' if len(t) > LINE_CHARS else '')}  [{', '.join(found)}]")
    out = out[:MAX_LINES]
    if common:
        out.append(f"(mentioned too often to list; search if the change alters what they mean: {', '.join(common)})")
    return out, {n: names[n] for n in picked}


def note(lines, names):
    """The prompt section, or "" when nothing outside the diff mentions a touched name."""
    if not lines:
        return ""
    return ("Docs and comments OUTSIDE this diff that mention names this change touched (" +
            ", ".join(names) + "), from a whole-word search of the checkout:\n" + "\n".join(lines) +
            "\nOpen each one that could describe the changed behaviour, signature, default, flag or name. A line that "
            "the change made wrong is a nit (or a finding, if users following it would break something) at THAT "
            "file and line. Most will still be right; say nothing about those.\n")
