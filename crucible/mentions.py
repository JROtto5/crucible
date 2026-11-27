"""Readers of a value the change altered, and repo paths it names that aren't there ($0: git grep, no model call).

callers_note fires on a signature, fields_note on a field name and docs_note on a definition's name. None fires when
what the change alters is a VALUE: a route or path string, an id format, a file's location. TRAIN's never-raised high
misses (eval/NOTES 2026-11-24) include two of that kind: a dashboard link that now passes the raw id while the pages
it opens compare ids with 'COMP-001' (the old format, still in the checkout), and a moved script that still names
`$REPO_ROOT/packages/agent-orchestrator/bin/ao.js`, a directory that no longer exists. This lists, for the --nits
review prompt:
- values: a path, route or id-format string on a removed line that no added line of the change still carries (so
  the change replaced or dropped it), and the old path of a moved or deleted file, each with the lines of the
  checkout that still use it;
- missing paths: a repo path named on an added line, or anywhere in a file the change adds or moves, whose top
  directory exists at HEAD but which itself doesn't.
The reviewer judges each line; nothing here is a finding.
"""
import os
import re

from .util import TEST_PATH_RX, git
from .docrefs import COMMENT_RX

# a quoted string, one line: '...', "..." or `...` (a template literal's ${} parts stay in; they make it not a value)
STR_RX = re.compile(r"""'([^'\\\n]{3,200})'|"([^"\\\n]{3,200})"|`([^`\\\n]{3,200})`""")
# an id in a fixed format: COMP-001, ABC-12 (a letter prefix and a number). JIRA-shaped keys in prose are values too.
ID_RX = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{2,}$")
# a path or route: two or more segments, no spaces, no glob, no interpolation, no URL scheme
PATH_RX = re.compile(r"^/?[\w@.+-]+(?:/[\w@.+-]+)+/?(?:\?[\w=&-]*)?$")
SCHEME_RX = re.compile(r"^\w+://|^(?:mailto|data|javascript):", re.I)
# a repo path in a script or string: an optional $VAR/ or ${VAR}/ root, then segments. Only the root-relative form
# is checked; ./ and ../ depend on the working directory.
REPO_PATH_RX = re.compile(r"""(?:(?<=[\s'"`=(:])|^)(?:\$\{?([A-Za-z_]\w*)\}?/)?((?:[A-Za-z0-9_@][\w@.+-]*/)+[\w@.+-]+)(?![\w@.+/-]|\$|\{|\(| \w)""")
# a $VAR/ root counts only when the variable names the checkout (REPO_ROOT, PROJECT_DIR, GITHUB_WORKSPACE); a temp,
# home or cache root is somewhere else
ROOT_VAR_RX = re.compile(r"root|repo|workspace|project|src|source|top", re.I)
NOT_ROOT_VAR_RX = re.compile(r"te?mp|home|cache|runner|tool|out|build|dist", re.I)
# docs, ignore files and templates name example or future paths; a placeholder segment (epic-XXXX) isn't a path
PROSE_RX = re.compile(r"\.(md|mdx|rst|adoc|txt|html?)$|(^|/)\.\w*ignore$|(^|/)(README|AGENTS|CLAUDE)[^/]*$", re.I)
PLACEHOLDER_RX = re.compile(r"X{3,}|Y{3,}|N{3,}|<|\{")
# a removed import names a module, not a value: other files importing it aren't readers of anything the change altered
IMPORT_RX = re.compile(r"^\s*(?:import\b|from\s+\S+\s+import\b|export\b.*\bfrom\b|.*\brequire\s*\(|use\s|#\s*include\b)")
# a filesystem path outside the checkout
SYSTEM_RX = re.compile(r"^/(?:etc|usr|bin|sbin|tmp|var|opt|dev|proc|sys|home|Users|root|mnt|Library)(?:/|$)")
# never grep or check these: build output, dependencies, lockfiles, minified or generated text, release history
SKIP_PATH_RX = re.compile(r"(^|/)(node_modules|vendor|third_party|dist|build|out|target|coverage|\.venv|venv|"
                          r"__pycache__|\.git)(/|$)|\.min\.(js|css)$|\.(lock|snap|map|svg)$|"
                          r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|go\.sum|poetry\.lock)$|"
                          r"(^|/)(CHANGELOG|CHANGES|HISTORY|NEWS|RELEASE[-_]?NOTES)[^/]*$", re.I)
# not files: a MIME type, a date, a version, an npm scope alone, a fraction
NOT_PATH_RX = re.compile(r"^(?:application|text|image|audio|video|font|multipart)/|^\d+(?:/\d+)+$|^\d|"
                         r"^[\w.-]+/[\w.-]+@|^@[\w-]+/[\w-]+$", re.I)
MAX_VALUES = 12           # values searched per pass, most specific (longest) first
MAX_IDS_PER_FORMAT = 2    # COMP-001 .. COMP-020: the format is one value; two samples find its readers
MAX_PER_VALUE = 5         # a value used more often than this is shared vocabulary: say how often, not where
MAX_VALUE_FILES = 8       # ... and one in more files than this isn't one flaw's reader at all: left out
MAX_MISSING = 10
MAX_LINES = 40
LINE_CHARS = 160


def _strings(text):
    return [next(g for g in m.groups() if g is not None) for m in STR_RX.finditer(text)]


def _token_like(seg):
    """A key or hash, not a name: 10+ letters and digits that switch case 5+ times (wJalrXUtnFEMI)."""
    return (len(seg) >= 10 and seg.isalnum()
            and sum(1 for a, b in zip(seg, seg[1:]) if a.isalpha() and b.isalpha() and a.islower() != b.islower()) >= 5)


def _value_ok(s):
    """A string worth searching for: an id in a fixed format, or a path or route of two or more segments."""
    s = s.strip()
    if ID_RX.match(s):
        return True
    if s[:1] in ".~#" or s.startswith("@/") or SYSTEM_RX.match(s):
        return False                    # relative (a module specifier) or outside the checkout
    if (len(s) < 6 or SCHEME_RX.match(s) or NOT_PATH_RX.match(s.lstrip("/")) or PLACEHOLDER_RX.search(s) or "*" in s
            or any(_token_like(x) for x in s.split("/"))):
        return False
    return bool(PATH_RX.match(s)) and not SKIP_PATH_RX.search(s.split("?")[0])


def moves(f):
    """(old path, new path) when the diff moves or deletes this file, else None. A pure rename has no ---/+++ lines,
    so the parser leaves old_path unset; the rename header carries it."""
    m = re.search(r"^rename from (.+)$", f.get("text") or "", re.M)
    if m:
        return m.group(1), f.get("path")
    if f.get("deleted"):
        return f.get("path"), None
    return None


def changed_values(files, all_files=None):
    """{value: why} for the pass's files. all_files: the whole change; a value an added line anywhere in it still
    carries wasn't replaced (moved to another file, reformatted), so it isn't listed."""
    added = set()
    for f in all_files if all_files is not None else files:
        for h in f.get("hunks") or []:
            for k, t, *_ in h["lines"]:
                if k == "+":
                    added.update(x.strip() for x in _strings(t))
    out, per_format = {}, {}
    for f in files:
        path = f.get("path") or ""
        mv = moves(f)
        if mv and not SKIP_PATH_RX.search(mv[0]):
            out.setdefault(mv[0], f"{mv[0]} was {'moved to ' + mv[1] if mv[1] else 'deleted'}")
        # a test's removed strings are fixtures, read by nothing outside it
        if f.get("binary") or SKIP_PATH_RX.search(path) or TEST_PATH_RX.search(path):
            continue
        for h in f.get("hunks") or []:
            for k, t, *_ in h["lines"]:
                if k != "-" or IMPORT_RX.match(t):
                    continue
                for s in _strings(t):
                    s = s.strip()
                    if s in added or s in out or not _value_ok(s):
                        continue
                    if ID_RX.match(s):
                        fmt = re.sub(r"\d", "0", s)
                        if per_format.get(fmt, 0) >= MAX_IDS_PER_FORMAT:
                            continue
                        per_format[fmt] = per_format.get(fmt, 0) + 1
                        out[s] = f"id format on a removed line of {path}; no added line uses it"
                    else:
                        out[s] = f"on a removed line of {path}; no added line uses it"
    return out


def _grep(repo, values):
    if not values:
        return []
    args = ["grep", "-n", "-I", "-F", "--no-color"]
    for v in values:
        args += ["-e", v]
    try:
        raw = git(repo, *args, check=False)
    except Exception:
        return []
    out = []
    for ln in raw.splitlines():
        p, _, rest = ln.partition(":")
        no, _, text = rest.partition(":")
        if no.isdigit() and not SKIP_PATH_RX.search(p):
            out.append((p, int(no), text))
    return out


def _bounded(v, t):
    """v appears in t as a whole value, not inside a longer path or id: COMP-001 isn't COMP-0012, a/b isn't a/bc."""
    return re.search(rf"(?<![\w/.-]){re.escape(v)}(?![\w-]|/?\w|\.\w)", t) is not None


def readers(repo, values, changed_lines=None):
    """-> (lines, picked): ["path:line: text  [value]"] in the checkout that still use a changed value, outside the
    change's own added lines. changed_lines: {path: set(new line numbers)} the reviewer already sees."""
    picked = sorted(values, key=lambda v: (-len(v), v))[:MAX_VALUES]
    changed_lines = changed_lines or {}
    by_value, seen = {v: [] for v in picked}, set()
    for p, no, t in _grep(repo, picked):
        if no in changed_lines.get(p, ()) or (p, no) in seen:
            continue
        found = [v for v in picked if v in t and _bounded(v, t)]
        if found:
            by_value[found[0]].append((p, no, t, found))
            seen.add((p, no))
    out, common = [], []
    for v in picked:
        hs = by_value[v]
        if len({p for p, *_ in hs}) > MAX_VALUE_FILES:
            continue
        if len(hs) > MAX_PER_VALUE:
            common.append(f"{v} ({len(hs)} lines in {len({p for p, *_ in hs})} files)")
            continue
        for p, no, t, found in hs:
            t = t.strip()
            out.append(f"{p}:{no}: {t[:LINE_CHARS] + (' ...' if len(t) > LINE_CHARS else '')}  [{', '.join(found)}]")
    out = out[:MAX_LINES]
    if common:
        out.append(f"(used too often to list; search them if the change alters what they mean: {', '.join(common)})")
    return out, {v: values[v] for v in picked}


def _tracked(repo):
    try:
        return [p for p in git(repo, "ls-files", check=False).splitlines() if p]
    except Exception:
        return []


def missing_paths(repo, files, read_new, tracked=None):
    """-> ["path:line: text  [missing path]"]: a repo-root path named on an added line, or on any line of a file the
    change adds or moves (a move is where an old path goes stale), whose top directory is tracked at HEAD but which
    is neither a tracked file, a tracked directory, nor a file's name without its extension (a module import), from
    the root or from the naming file's own directory."""
    tracked = _tracked(repo) if tracked is None else tracked
    if not tracked:
        return []
    exact = set(tracked)
    dirs = {p.rsplit("/", i)[0] for p in tracked for i in range(1, p.count("/") + 1)}
    stems = {os.path.splitext(p)[0] for p in tracked}
    tops = {p.split("/", 1)[0] for p in tracked if "/" in p}

    def there(c):
        c = c.rstrip("/")
        return c in exact or c in dirs or c in stems

    out = []
    for f in files:
        path = f.get("path") or ""
        # tests name fake paths on purpose; docs name example and planned ones
        if (f.get("deleted") or f.get("binary") or SKIP_PATH_RX.search(path) or TEST_PATH_RX.search(path)
                or PROSE_RX.search(path)):
            continue
        seen = set()                    # once per naming file: a stale path copied into two scripts is two sites
        if f.get("added") or moves(f):
            text = read_new(path) or ""
            lines = list(enumerate(text.split("\n"), 1))
        else:
            lines = [(n, t) for h in f.get("hunks") or [] for k, t, _, n in h["lines"] if k == "+"]
        here = os.path.dirname(path)
        for no, t in lines:
            if COMMENT_RX.match(t):
                continue
            for m in REPO_PATH_RX.finditer(t):
                var, c = m.group(1), m.group(2).rstrip(".,;:")
                top = c.split("/", 1)[0]
                if var and (not ROOT_VAR_RX.search(var) or NOT_ROOT_VAR_RX.search(var)):
                    continue
                if (top not in tops or c in seen or SKIP_PATH_RX.search(c) or NOT_PATH_RX.match(c)
                        or PLACEHOLDER_RX.search(c) or there(c)
                        or (here and there(os.path.normpath(os.path.join(here, c))))):
                    continue
                seen.add(c)
                t = t.strip()
                out.append(f"{path}:{no}: {t[:LINE_CHARS] + (' ...' if len(t) > LINE_CHARS else '')}  [{c}]")
                if len(out) >= MAX_MISSING:
                    return out
    return out


def note(reader_lines, values, missing):
    """The prompt section, or "" when nothing fired."""
    parts = []
    if reader_lines:
        parts.append(
            "Values this change removed, replaced or moved (" + ", ".join(values) + ") that lines OUTSIDE the "
            "change still use, from a fixed-string search of the checkout:\n" + "\n".join(reader_lines) +
            "\nEach line is a reader of the old value. Open the ones the change could break: a page comparing ids "
            "in the old format, a script or doc naming the old path, a route the new code no longer serves. A "
            "reader the change broke is a finding at THAT file and line. Most will be fine; say nothing about "
            "those.\n")
    if missing:
        parts.append(
            "Repo paths this change names (on an added line, or in a file it adds or moves) that do not exist at "
            "the reviewed commit, though their top directory does:\n" + "\n".join(missing) +
            "\nCheck each: a path the code opens, runs or imports at that location fails at runtime. One built at "
            "runtime, created by a build step or meant for another checkout is fine; say nothing about those.\n")
    return "\n".join(parts)


def mentions(repo, files, read_new, all_files=None, changed_lines=None):
    """-> the note text for one pass's files ("" when nothing fired)."""
    values = changed_values(files, all_files)
    lines, picked = readers(repo, values, changed_lines) if values else ([], {})
    return note(lines, picked, missing_paths(repo, files, read_new))
