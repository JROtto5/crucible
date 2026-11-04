"""Unified-diff parsing, deterministic scanners, and chunking with coverage."""
import re
from .util import TEST_PATH_RX

SECRET_RX = re.compile(r"(sk-ant-[\w-]{10,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
                       r"-----BEGIN [A-Z ]*PRIVATE KEY|xox[abpr]-[\w-]{10,}|eyJ[\w-]{20,}\.[\w-]{20,}\.[\w-]{10,})")
DEBUG_RX = re.compile(r"\b(debugger;|console\.log\(|print\(['\"]DEBUG|pdb\.set_trace\(\)|breakpoint\(\))")
CONFLICT_RX = re.compile(r"^(<<<<<<< |>>>>>>> |=======$)")
HUNK_RX = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


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
            cur["old_path"] = None if raw[4:] == "/dev/null" else re.sub(r"^a/", "", raw[4:])
            cur["added"] = raw[4:] == "/dev/null"
        elif hunk is None and raw.startswith("+++ "):
            if raw[4:] == "/dev/null":
                cur["deleted"], cur["path"] = True, cur["old_path"]
            else:
                cur["path"] = re.sub(r"^b/", "", raw[4:])
        elif raw.startswith("Binary files "):
            cur["binary"] = True
            m = re.search(r" and (?:b/)?(.+?) differ$", raw)
            cur["path"] = cur["path"] or (m.group(1) if m else None)
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
            m = re.match(r"diff --git a/(.+?) b/(.+)$", f["text"].split("\n", 1)[0])
            f["path"] = m.group(2) if m else "?"
        for h in f["hunks"]:
            h.pop("_o", None); h.pop("_n", None)
    return files


def scan(files):
    """Deterministic findings from added lines only."""
    out = []
    for f in files:
        if f["deleted"] or f["binary"]:
            continue
        in_test = bool(TEST_PATH_RX.search(f["path"]))
        for h in f["hunks"]:
            for kind, text, _o, n in h["lines"]:
                if kind != "+":
                    continue
                hit = None
                if SECRET_RX.search(text):
                    hit = ("medium" if in_test else "critical", "Possible secret in added line")
                elif CONFLICT_RX.match(text):
                    hit = ("critical", "Merge conflict marker")
                elif DEBUG_RX.search(text) and not in_test:
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
