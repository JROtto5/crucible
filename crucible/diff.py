"""Unified-diff parsing, deterministic scanners, and chunking with coverage."""
import collections
import re
from .util import TEST_PATH_RX

SECRET_RX = re.compile(r"(sk-ant-[\w-]{10,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
                       r"-----BEGIN [A-Z ]*PRIVATE KEY|xox[abpr]-[\w-]{10,}|eyJ[\w-]{20,}\.[\w-]{20,}\.[\w-]{10,})")
# an elided example key ("-----BEGIN PRIVATE KEY-----\n...", "AKIA...<id>") in docs is not a secret: ReviewBench
# run 2 had 2 critical scanner findings, both doc-comment placeholders, both judged false
PLACEHOLDER_RX = re.compile(r"\.\.\.|\u2026|<[^<>]+>|[xX]{6,}")
DEBUG_RX = re.compile(r"\b(debugger;|console\.log\(|print\(['\"]DEBUG|pdb\.set_trace\(\)|breakpoint\(\))")
# console.log is a debug leftover in product code, but the intended output of a build/bench/example script and of a
# tagged server log line: every real-code fire through 2026-11-16 was one of those (eval/NOTES 2026-11-16, DRG-146).
# Falsifiers (tests/test_core.py test_intended_console_output_is_not_a_debug_leftover). Must flag: console.log(res)
# in src/, packages/next/src/build/, src/tools/, app/docs/page.tsx, packages/@scope/docs/src/; a `[DEBUG]`/`[]` tag;
# a `[` ... `]` split across string pieces (`"[" + x + "]"`); a JS `#private` member line;
# debugger and breakpoint calls even in scripts/. Must let through: i18n/build.ts, an `[OAuth]`-tagged line, scripts/,
# bench/, examples/ at the repo root or a packages|apps/[@scope/]<name>/ root, a commented-out line, a Markdown file.
CONSOLE_RX = re.compile(r"\bconsole\.log\(")
TAGGED_LOG_RX = re.compile(r"""console\.log\(\s*['"`]\[(?!(debug|tmp|temp|todo|test)\b)[^\]\s'"`][^\]'"`]*\]""", re.I)
SCRIPT_DIR_RX = re.compile(r"^((packages|apps)/(@[^/]+/[^/]+|[^@/][^/]*)/)?"
                           r"(scripts?|bin|tools?|bench(marks?)?|examples?|demos?|docs?|build)/", re.I)
SCRIPT_FILE_RX = re.compile(r"(^|/)(build|bench\w*|cli)\.[cm]?[jt]s$", re.I)
PROSE_PATH_RX = re.compile(r"\.(md|mdx|markdown|rst|txt|adoc)$", re.I)
JS_PATH_RX = re.compile(r"\.([cm]?[jt]sx?|vue|svelte)$", re.I)
CONFLICT_RX = re.compile(r"^(<<<<<<< |>>>>>>> |=======$)")
HUNK_RX = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


_C_ESC = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _git_path(s, prefix=""):
    """A path as git prints it in diff headers -> the real path. Git C-quotes names with non-ASCII or special bytes
    ("b/caf\\303\\251.py", octal UTF-8 bytes) and ends a ---/+++ name that has a space with a tab ("b/a b.py\\t")."""
    s = s.rstrip("\t") if not s.startswith('"') else s.split("\t")[0]
    if len(s) >= 2 and s[0] == s[-1] == '"':
        out, i, body = bytearray(), 0, s[1:-1]
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                n = body[i + 1]
                if n in "01234567" and re.match(r"[0-7]{3}", body[i + 1:i + 4]):
                    out.append(int(body[i + 1:i + 4], 8)); i += 4
                    continue
                out.append(_C_ESC.get(n, ord(n))); i += 2
                continue
            out += c.encode(); i += 1
        s = out.decode("utf-8", "replace")
    return s[len(prefix):] if prefix and s.startswith(prefix) else s


def parse(diff):
    """-> list of files: {path, old_path, deleted, added, hunks:[{old_start,old_len,new_start,new_len,lines:[(kind,text,old_no,new_no)]}], text}"""
    files, cur, hunk = [], None, None
    for raw in diff.split("\n"):
        if raw.startswith("diff --git "):
            cur = {"path": None, "old_path": None, "deleted": False, "added": False, "binary": False, "hunks": [], "text": [raw]}
            files.append(cur); hunk = None
            continue
        if cur is None:
            continue
        cur["text"].append(raw)
        if hunk is None and raw.startswith("--- "):
            cur["old_path"] = None if raw[4:] == "/dev/null" else _git_path(raw[4:], "a/")
            cur["added"] = raw[4:] == "/dev/null"
        elif hunk is None and raw.startswith("+++ "):
            if raw[4:] == "/dev/null":
                cur["deleted"], cur["path"] = True, cur["old_path"]
            else:
                cur["path"] = _git_path(raw[4:], "b/")
        elif raw.startswith("Binary files "):
            cur["binary"] = True
            # a /dev/null side is unambiguous; otherwise split at the last " and " before b/ (a " and " inside a name)
            m = (re.match(r"Binary files (/dev/null) and (.*) differ$", raw)
                 or re.match(r'Binary files (.*) and ("b/(?:[^"\\]|\\.)*"|b/.*|/dev/null) differ$', raw))
            if m and not cur["path"]:
                if m.group(2) == "/dev/null":
                    cur["deleted"], cur["path"] = True, _git_path(m.group(1), "a/")
                else:
                    cur["added"] = m.group(1) == "/dev/null"
                    cur["path"] = _git_path(m.group(2), "b/")
        elif HUNK_RX.match(raw):
            m = HUNK_RX.match(raw)
            hunk = {"old_start": int(m.group(1)), "old_len": int(m.group(2) or 1),
                    "new_start": int(m.group(3)), "new_len": int(m.group(4) or 1), "lines": []}
            hunk["_o"], hunk["_n"] = hunk["old_start"], hunk["new_start"]
            cur["hunks"].append(hunk)
        elif hunk is not None:
            if raw.startswith("\\"):           # "\ No newline at end of file": not a line
                continue
            k = raw[:1]
            if k == "+":
                hunk["lines"].append(("+", raw[1:], None, hunk["_n"])); hunk["_n"] += 1
            elif k == "-":
                hunk["lines"].append(("-", raw[1:], hunk["_o"], None)); hunk["_o"] += 1
            elif k == " " or raw == "":
                if raw == "" and hunk["_o"] >= hunk["old_start"] + hunk["old_len"] and hunk["_n"] >= hunk["new_start"] + hunk["new_len"]:
                    continue                    # trailing blank line after the last hunk
                hunk["lines"].append((" ", raw[1:], hunk["_o"], hunk["_n"])); hunk["_o"] += 1; hunk["_n"] += 1
    for f in files:
        f["text"] = "\n".join(f["text"])
        if not f["path"]:
            head = f["text"].split("\n", 1)[0]
            m = re.match(r'diff --git (?:a/.+?|"a/(?:[^"\\]|\\.)*") (b/.+|"b/(?:[^"\\]|\\.)*")$', head)
            f["path"] = _git_path(m.group(1), "b/") if m else "?"
        for h in f["hunks"]:
            h.pop("_o", None); h.pop("_n", None)
    return files


def authored_added(hunk):
    """-> [(new_no, text)] for the hunk's added lines that this change wrote, leaving out lines that only re-add a
    removed line of the same hunk with different indentation. Wrapping a block in `try {` or `if` re-indents every
    line in it; those lines were already in the file, so a pre-existing comment or `console.log` there is not the
    author's (three-mesh-bvh bvh-errors: a 2024 comment re-indented by a new `try` was flagged as narration)."""
    removed = collections.Counter(re.sub(r"\s+", "", t) for k, t, *_ in hunk["lines"] if k == "-")
    out = []
    for k, t, _o, n in hunk["lines"]:
        if k != "+":
            continue
        key = re.sub(r"\s+", "", t)
        if key and removed[key]:
            removed[key] -= 1
            continue
        out.append((n, t))
    return out


def script_path(path):
    """A build/bench/example/tool script, where printing is the point. Only a script dir at the repo root or a
    packages|apps/[@scope/]<name>/ root counts (deeper package layouts are not recognised): tools/ or build/ deeper
    down is product code (Next.js packages/next/src/build/, an app router's app/docs/)."""
    return bool(SCRIPT_DIR_RX.search(path) or SCRIPT_FILE_RX.search(path))


def intended_output(path, text):
    """True when a DEBUG_RX hit is not a leftover: prose (a code sample in docs), a commented-out line of any kind,
    or a console.log in a script or with a `[tag]` log prefix. Live debugger, pdb and breakpoint calls and DEBUG
    prints always count."""
    if PROSE_PATH_RX.search(path):
        return True
    s = text.lstrip()
    if s.startswith(("//", "/*", "*")) or (s.startswith("#") and not JS_PATH_RX.search(path)):
        return True
    if DEBUG_RX.search(CONSOLE_RX.sub("", text)):
        return False
    return script_path(path) or bool(TAGGED_LOG_RX.search(text))


def scan(files):
    """Deterministic findings from added lines only. Secrets and conflict markers are checked on every added line;
    a debug statement only on lines the change wrote (see authored_added)."""
    out = []
    for f in files:
        if f["deleted"] or f["binary"]:
            continue
        in_test = bool(TEST_PATH_RX.search(f["path"]))
        for h in f["hunks"]:
            authored = {n for n, _ in authored_added(h)}
            for kind, text, _o, n in h["lines"]:
                if kind != "+":
                    continue
                hit = None
                m = SECRET_RX.search(text)
                if m and not PLACEHOLDER_RX.search(text[m.start():]):
                    hit = ("medium" if in_test else "critical", "Possible secret in added line")
                elif CONFLICT_RX.match(text):
                    hit = ("critical", "Merge conflict marker")
                elif DEBUG_RX.search(text) and not in_test and n in authored and not intended_output(f["path"], text):
                    hit = ("low", "Debug statement left in")
                if hit:
                    out.append({"severity": hit[0], "file": f["path"], "line": n, "title": hit[1],
                                "problem": text.strip()[:200], "caused_by_this_change": True,
                                "reachable_in_real_use": not in_test, "source": "scanner",
                                "wrong_if": "the matched text is a fixture/placeholder or intentional, not a real value",
                                "fix": "remove it, or move it to configuration / a fixture that is clearly fake"})
    return out


# Pass order when a change needs more than one pass. Passes used to run in path order, so on a large change the
# budget went to whatever sorts first. ReviewBench run 5, emdash (408 files, $5 cap): `.agents/` skill docs, `demos/`
# and `i18n/` took the first passes, and the three auth routes holding all three of its high-severity golden issues
# sat in pass 8 of 24, never reviewed (261 files left). Ranks, path order within each (so a package's files stay
# together): 0 code under a security-sensitive name, 1 other code (tests, config, CI and agent files count as code
# here, as everywhere in crucible), 2 docs, 3 low-value: lockfiles, generated or vendored output, changesets, and
# demo/example/sample/fixture trees. templates/ is code (a Django or Flask app keeps its views there). Nothing is
# skipped; only the order changes. A change that fits one pass keeps path order, so its prompt is byte-identical.
# Falsifiers (tests/test_core.py test_review_order_*):
#   rank 0: src/auth/login.ts, packages/auth-x/src/routes/callback.ts, app/middleware/session.py
#   rank 1: packages/admin/src/App.tsx, src/routes/api/posts.ts, tests/auth/test_login.py, src/util.ts,
#           .github/workflows/ci.yml, src/user/.codex/AGENTS.md.template, templates/index.html
#   rank 2: README.md, docs/guide.md
#   rank 3: pnpm-lock.yaml, demos/a/src/x.astro, .changeset/x.md, dist/a.min.js
# Route and admin trees are not "sensitive" by name: in a web app that is most of the code.
SENSITIVE_RX = re.compile(r"(^|[/_.-])(auth\w*|log(in|out)|oauth\w*|sessions?|tokens?|crypto|security|secrets?|"
                          r"permissions?|acl|rbac|csrf|passkeys?|password\w*)([/_.-]|$)", re.I)
LOW_VALUE_RX = re.compile(r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock|"
                          r"uv\.lock|Pipfile\.lock|Cargo\.lock|Gemfile\.lock|composer\.lock|go\.sum|bun\.lockb?)$|"
                          r"\.min\.(js|css)$|\.snap$|(^|/)(__snapshots__|dist|vendor|third_party|node_modules|"
                          r"\.changeset|demos?|examples?|samples?|fixtures?|testdata)/", re.I)


def review_rank(path):
    from .routing import is_doc                     # routing imports util only; imported here to keep diff's deps flat
    if LOW_VALUE_RX.search(path):
        return 3
    if is_doc(path):
        return 2
    return 1 if TEST_PATH_RX.search(path) or not SENSITIVE_RX.search(path) else 0


def chunk(files, max_chars=45000):
    """Group files into review chunks. A file bigger than max_chars is split by hunks. More than one chunk: the files
    are regrouped riskiest first (review_rank), so a budget that runs out leaves the least useful passes.
    Returns (chunks, uncovered): chunk = {files:[path], text}, uncovered = paths that could not be fully included."""
    chunks, uncovered = _chunk(files, max_chars)
    if len(chunks) > 1:
        chunks, uncovered = _chunk(sorted(files, key=lambda f: review_rank(f["path"])), max_chars)   # stable sort
    return chunks, uncovered


def _chunk(files, max_chars):
    chunks, cur, size, uncovered = [], {"files": [], "text": ""}, 0, []
    def flush():
        nonlocal cur, size
        if cur["files"]:
            chunks.append(cur)
        cur, size = {"files": [], "text": ""}, 0
    for f in files:
        if f["binary"]:
            continue
        t = f["text"]
        if len(t) <= max_chars:
            if size + len(t) > max_chars:
                flush()
            cur["files"].append(f["path"]); cur["text"] += t + "\n"; size += len(t)
            continue
        flush()
        header = t.split("\n@@", 1)[0]
        parts = ["@@" + p for p in t.split("\n@@")[1:]]
        piece = header
        for p in parts:
            if len(p) > max_chars:
                uncovered.append(f["path"]); p = p[:max_chars] + "\n[... hunk truncated ...]"
            if len(piece) + len(p) > max_chars and piece != header:
                chunks.append({"files": [f["path"]], "text": piece}); piece = header
            piece += "\n" + p
        chunks.append({"files": [f["path"]], "text": piece})
    flush()
    return chunks, sorted(set(uncovered))


# Falsifiers (tests/test_core.py test_formatting_only_keeps_whitespace_inside_string_literals). Must flag:
# `foo( 'a b' , x )` -> `foo('a b', x)`; `x = f( 1 )  # don't` -> `x = f(1)  # don't`. Must let through: whitespace
# changed inside '...', "..." or `...` on the line (a regex `(    \(` -> `(  \(`), after an escaped quote, or after
# an unclosed apostrophe in a comment.
def _strip_code_whitespace(line):
    """Drop whitespace outside quoted literals on one line; whitespace inside '...', "..." or `...` is data
    (a regex or message), so changing it is not formatting. Quote state does not carry across lines, so the body
    lines of a triple-quoted string or template literal are still treated as code. An unclosed quote (an
    apostrophe in a comment) keeps the rest of that line, which can only hide churn there."""
    out, quote, esc = [], None, False
    for c in line:
        if quote:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c; out.append(c)
        elif not c.isspace():
            out.append(c)
    return "".join(out)


def formatting_only_hunks(files):
    """Hunks whose removed and added lines are identical once whitespace outside string literals is ignored."""
    out = []
    for f in files:
        for h in f["hunks"]:
            rem = [t for k, t, *_ in h["lines"] if k == "-"]
            add = [t for k, t, *_ in h["lines"] if k == "+"]
            if not (rem or add):
                continue
            # The literal-aware strip keeps a superset of what \s+ keeps, so only hunks that pass the cheap
            # check can pass it; this keeps lockfile-sized diffs off the per-character loop.
            if re.sub(r"\s+", "", "".join(rem)) != re.sub(r"\s+", "", "".join(add)):
                continue
            if "".join(map(_strip_code_whitespace, rem)) == "".join(map(_strip_code_whitespace, add)):
                out.append(f"{f['path']}:{h['new_start']}")
    return out


def changed_old_ranges(diff_text):
    """For carry-forward: old-side line ranges touched by a diff, per file -> [(start, end)]."""
    out = {}
    for f in parse(diff_text):
        rs = out.setdefault(f["old_path"] or f["path"], [])
        for h in f["hunks"]:
            rs.append((h["old_start"], h["old_start"] + max(h["old_len"], 1) - 1))
    return out


def region_touched(ranges, line, pad=3):
    return any(a - pad <= line <= b + pad for a, b in ranges)


def hunks_old_new(diff_text):
    """per file -> [(old_start, old_len, new_start, new_len)] for mapping old line numbers forward."""
    out = {}
    for f in parse(diff_text):
        out[f["old_path"] or f["path"]] = [(h["old_start"], h["old_len"], h["new_start"], h["new_len"]) for h in f["hunks"]]
    return out


def map_line(hunks, line):
    """Old line -> new line for a line outside any hunk (None if inside a changed hunk).

    A zero-length side of a unified-diff hunk names the line *before* the change ("@@ -20,0 +21,2 @@" inserts after old
    line 20), so the shift is measured between the last line of each side, not between their starts."""
    shift = 0
    for os_, ol, ns, nl in hunks:
        if (ol and line < os_) or (not ol and line <= os_):
            break
        if ol and os_ <= line < os_ + ol:
            return None
        old_end = os_ + ol - 1 if ol else os_
        new_end = ns + nl - 1 if nl else ns
        shift = new_end - old_end
    return line + shift
