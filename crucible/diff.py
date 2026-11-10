"""Unified-diff parsing, deterministic scanners, and chunking with coverage."""
import collections
import re
from .util import TEST_PATH_RX

SECRET_RX = re.compile(r"(sk-ant-[\w-]{10,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
                       r"-----BEGIN [A-Z ]*PRIVATE KEY|xox[abpr]-[\w-]{10,}|eyJ[\w-]{20,}\.[\w-]{20,}\.[\w-]{10,})")
DEBUG_RX = re.compile(r"\b(debugger;|console\.log\(|print\(['\"]DEBUG|pdb\.set_trace\(\)|breakpoint\(\))")
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
            # the greedy old side makes " and " inside a name harmless: the split is the last " and " before b/
            m = re.match(r'Binary files (.*) and ("b/(?:[^"\\]|\\.)*"|b/.*|/dev/null) differ$', raw)
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
                if SECRET_RX.search(text):
                    hit = ("medium" if in_test else "critical", "Possible secret in added line")
                elif CONFLICT_RX.match(text):
                    hit = ("critical", "Merge conflict marker")
                elif DEBUG_RX.search(text) and not in_test and n in authored:
                    hit = ("low", "Debug statement left in")
                if hit:
                    out.append({"severity": hit[0], "file": f["path"], "line": n, "title": hit[1],
                                "problem": text.strip()[:200], "caused_by_this_change": True,
                                "reachable_in_real_use": not in_test, "source": "scanner",
                                "wrong_if": "the matched text is a fixture/placeholder or intentional, not a real value",
                                "fix": "remove it, or move it to configuration / a fixture that is clearly fake"})
    return out


def chunk(files, max_chars=45000):
    """Group files into review chunks. A file bigger than max_chars is split by hunks.
    Returns (chunks, uncovered): chunk = {files:[path], text}, uncovered = paths that could not be fully included."""
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


def formatting_only_hunks(files):
    """Hunks whose removed and added lines are identical once whitespace is ignored."""
    out = []
    for f in files:
        for h in f["hunks"]:
            rem = [re.sub(r"\s+", "", t) for k, t, *_ in h["lines"] if k == "-"]
            add = [re.sub(r"\s+", "", t) for k, t, *_ in h["lines"] if k == "+"]
            if (rem or add) and "".join(rem) == "".join(add):
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
