"""Call sites outside the diff of definitions whose contract the change altered ($0: git grep, no model call).

ReviewBench run 3 found 25.0% of its golden api-architecture issues. The commonest kind is a contract change whose
callers weren't updated: a parameter renamed, dropped or reordered, a new required one, a changed default or return
type, a function removed. The reviewer works pass by pass from the diff, and the stale caller sits in a file the
diff never shows, so the prompt's "grep for its callers" is often skipped. This compares each touched definition's
signature at the base and at HEAD, and for every change an existing caller could feel, lists the call and import
lines outside the change's own added lines. Appending an optional parameter is not listed. The reviewer still judges
each line (a caller may pass only what still works); nothing here is a finding.
"""
import os
import re

from .docrefs import CODE_SPECS, COMMENT_RX, DEF_RX, GENERIC, NOT_NAMES, _enclosing, _grep, _in_prose
from .util import CODE_EXT_RX, TEST_PATH_RX

MAX_NAMES = 8             # names listed with their callers
MAX_SEARCH = 64           # names searched for callers (a deleted file can change hundreds)
MAX_PER_NAME = 8          # more call sites than this: counted, not listed
MAX_LINES = 30
LINE_CHARS = 160
SIG_LINES = 30            # a definition's argument list is read for at most this many lines
PY_JS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"}
CTOR = {"__init__", "constructor"}
CLASS_LINE_RX = re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)")
# from just after a definition's name to its "(": generics, or `= async function` / `= (` for an arrow function
OPEN_RX = re.compile(r"\s*(?:<[^()]*>)?\s*(?:=\s*(?:async\s+)?(?:function\s*\*?\s*\w*)?\s*)?\(")
# from just after the closing ")" to the return type, when the definition states one
# (outside Python, never past the end of that line: Ruby's body follows its signature with no "{" or ";")
RET_RX = {".py": re.compile(r"\s*->\s*([^:]+?)\s*:"),             # Python always closes it with ":"
          None: re.compile(r"[ \t]*:[ \t]*([^{=;\n]+?)[ \t]*(?:\{|=>|;|\n|$)")}
for _e in PY_JS - {".py"}:
    RET_RX[_e] = RET_RX[None]
RET_RX[None] = re.compile(r"[ \t]*([^{;\n]*?)[ \t]*(?:\{|;|\n|$)")   # Go, Rust, C: whatever sits before the body


def _class_above(lines, i):
    """The class a constructor at 0-based line i belongs to."""
    ind = len(lines[i]) - len(lines[i].lstrip())
    for j in range(i - 1, -1, -1):
        c = CLASS_LINE_RX.match(lines[j])
        if c and len(c.group(1)) < ind:
            return c.group(2)
    return None


# names that read as everyday method calls: a removed `install()` would list every pip.install( and pkg.install(
COMMON = {"install", "remove", "delete", "reset", "clear", "load", "save", "send", "write", "read", "format", "fetch",
          "next", "emit", "dispatch", "execute", "invoke", "refresh", "submit", "validate"}


def _name_ok(n):
    # a generic name ("install", "remove") greps every unrelated method call of that name
    return (bool(n) and len(n) >= 4 and n not in NOT_NAMES and n not in GENERIC and n not in COMMON
            and not (n.startswith("__") and n.endswith("__")))


def _strip_comment(ln, ext):
    """A definition line without its trailing comment (a crude cut: a '#' or '//' outside quotes)."""
    mark = "#" if ext in (".py", ".rb") else "//"
    q = None
    for i, c in enumerate(ln):
        if q:
            q = None if c == q else q
        elif c in "\"'`":
            q = c
        elif ln.startswith(mark, i):
            return ln[:i]
    return ln


def _split_top(s, generics=True):
    """s split on commas outside brackets and quotes. "<" opens a bracket only straight after a name (a generic,
    Map<K, V>), and ">" closes only a "<", so `a = x < 3, b` and an arrow's "=>" don't swallow the next parameter;
    a "<" still open at the end was a comparison (`a=x<3, b`), and the split is redone without generics. Best effort:
    an unspaced comparison next to a generic (`a=x<3, m: Map<K, V>`) or a `>` (`a=x<3, b=y>2`) still splits wrong,
    and the worst that does is one wrong "removed or renamed" line for the reviewer to dismiss."""
    out, stack, cur, q = [], [], "", None
    for i, c in enumerate(s):
        if q:
            q = None if c == q else q
        elif c in "\"'`":
            q = c
        elif c in "([{" or generics and c == "<" and i and (s[i - 1].isalnum() or s[i - 1] == "_"):
            stack.append(c)
        elif c in ")]}" and stack:
            stack.pop()
        elif c == ">" and stack and stack[-1] == "<" and s[i - 1:i] != "=":
            stack.pop()
        elif c == "," and not stack:
            out.append(cur)
            cur = ""
            continue
        cur += c
    if "<" in stack:
        return _split_top(s, generics=False)
    out.append(cur)
    return [p.strip() for p in out if p.strip()]


def signatures(text, path):
    """{name: [(params, returns)]} for every definition in text: params is the argument list as written (whitespace
    collapsed, comments cut), returns what follows it up to the body. __init__/constructor is filed under its class."""
    ext = os.path.splitext(path)[1].lower()
    rx = DEF_RX.get(ext)
    if not rx or not text:
        return {}
    lines, out = text.split("\n"), {}
    for i, ln in enumerate(lines):
        m = rx.match(ln)
        gi = next((k for k, g in enumerate(m.groups(), 1) if g), None) if m else None
        name = m.group(gi) if gi else None
        if not name or name in NOT_NAMES or CLASS_LINE_RX.match(ln):   # a class's parentheses hold bases
            continue
        if name in CTOR:
            name = _class_above(lines, i)
            if not name:
                continue
        buf = "\n".join(_strip_comment(x, ext) for x in lines[i:i + SIG_LINES])
        # from where the pattern matched the name: a text search would find "sync" inside "async def sync(" or
        # "Serve" inside "func (s *Server) Serve(" (comment cutting only shortens the line after the name)
        opener = OPEN_RX.match(buf, m.end(gi))
        if not opener:                          # a constant, a type, a struct: no argument list
            continue
        start, depth, q, end = opener.end() - 1, 0, None, -1
        for j in range(start, len(buf)):
            c = buf[j]
            if q:
                q = None if c == q else q
            elif c in "\"'`":
                q = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if not depth:
                    end = j
                    break
        if end < 0:
            continue
        params = re.sub(r"\s+", " ", buf[start + 1:end]).strip().rstrip(",").strip()
        rm = RET_RX.get(ext, RET_RX[None]).match(buf, end + 1)
        rest = re.sub(r"\s+", " ", rm.group(1)).strip() if rm and rm.group(1) else ""
        out.setdefault(name, []).append((params, rest))
    return out


def _param_list(params):
    """[(name, kind, default, keys)]. kind: 'pos' (before a bare * or /), 'kw' (keyword-only), 'star' (*args, **kw,
    ...rest). A destructured {a, b} or [a, b] is named by its position and carries the names it reads as keys."""
    out, kwonly = [], False
    for p in _split_top(params):
        if p in ("*", "/"):
            kwonly = kwonly or p == "*"
            continue
        star = p.startswith("*") or p.startswith("...")
        if p.startswith("*") and not p.startswith("**"):
            kwonly = True
        name_m = re.match(r"[*.]*\s*(\w+|\{[^}]*\}|\[[^\]]*\])", p)
        name = re.sub(r"\s+", "", name_m.group(1)) if name_m else p
        body = p[name_m.end():] if name_m else ""
        keys = None
        if name[:1] in "{[":
            keys = {m.group(1) for k in _split_top(name[1:-1]) if (m := re.match(r"\.{0,3}(\w+)", k))}
            name = f"(destructured #{len(out) + 1})"
        optional = body.lstrip().startswith("?")
        dm = re.search(r"(?<![=!<>])=(?![=>])\s*(.+)$", body)
        default = dm.group(1).strip() if dm else ("?" if optional else None)
        if name in ("self", "cls", "this"):
            continue
        out.append((name, "star" if star else "kw" if kwonly else "pos", default, keys))
    return out


def breaks(old, new, ext):
    """Why a caller written against old may fail or behave differently against new; [] when it can't."""
    (op, orr), (np_, nr) = old, new
    if op == np_ and orr == nr:
        return []
    if ext not in PY_JS:                        # no parameter model for this language: any change counts
        return [f"signature ({op}) -> ({np_})" + (f" returns {orr or '?'} -> {nr or '?'}" if orr != nr else "")]
    O, N = _param_list(op), _param_list(np_)
    on, nn = {p[0]: p for p in O}, {p[0]: p for p in N}
    why = []
    gone = [n for n in on if n not in nn]
    if gone:
        why.append("parameter " + ", ".join(gone) + " removed or renamed")
    for n, *_r, keys in O:                  # a destructured options object: a key it stops reading is ignored
        if keys is not None and n in nn and nn[n][3] is not None and keys - nn[n][3]:
            why.append(f"{n} no longer reads " + ", ".join(sorted(keys - nn[n][3])))
    opos = [p[0] for p in O if p[1] == "pos"]
    npos = [p[0] for p in N if p[1] == "pos"]
    kept = [n for n in opos if n in npos]
    if kept != [n for n in npos if n in opos] or any(npos.index(n) != opos.index(n) for n in kept):
        why.append("positional order " + ", ".join(opos) + " -> " + ", ".join(npos))
    if any(on[n][1] == "pos" and nn[n][1] == "kw" for n in on if n in nn):
        why.append("a positional parameter became keyword-only")
    req = [n for n, k, d, _keys in N if n not in on and k != "star" and d is None]
    if req:
        why.append("new required parameter " + ", ".join(req))
    for n, k, d, _keys in O:                # a parameter that gains a default is still compatible
        if n in nn and d is not None and nn[n][2] != d and k != "star":
            why.append(f"default of {n} {d} -> {nn[n][2] if nn[n][2] is not None else '(none: now required)'}")
    if orr and nr and orr != nr:            # an annotation added or dropped changes nothing at runtime
        why.append(f"return {orr} -> {nr}")
    return why


def changed_contracts(files, read_old, read_new):
    """{name: (path, reason)} for definitions in the change's code files whose contract a caller could feel.
    read_old(path)/read_new(path) -> the file at the base / HEAD ("" when absent)."""
    out, new_defs = {}, {}
    code = [f for f in files if not f.get("binary") and CODE_EXT_RX.search(f.get("path") or "")]
    for f in code:
        path = f["path"]
        if not f.get("deleted"):
            new_defs[path] = signatures(read_new(path), path)
    everywhere = {n for d in new_defs.values() for n in d}
    for f in code:
        path = f["path"]
        if f.get("added") or TEST_PATH_RX.search(path):
            continue
        old_path = f.get("old_path") or path
        ext = os.path.splitext(path)[1].lower()
        old_text = read_old(old_path)
        old_sigs, new_sigs = signatures(old_text, old_path), new_defs.get(path, {})
        # only definitions the change touches: a def line on a +/- line, or one enclosing an edited line
        touched = set()
        old_lines, new_lines = old_text.split("\n"), (read_new(path) or "").split("\n")
        rx = DEF_RX.get(ext)
        for h in f.get("hunks") or []:
            for k, _t, o, n in h["lines"]:
                for ls, no in ((old_lines, o if k == "-" else None), (new_lines, n if k == "+" else None)):
                    nm = _enclosing(ls, no, rx) if no else None
                    if nm in CTOR:              # a constructor's contract is filed under its class
                        idx = next((j for j in range(min(no, len(ls)) - 1, -1, -1)
                                    if (mm := rx.match(ls[j])) and nm in mm.groups()), None)
                        nm = _class_above(ls, idx) if idx is not None else None
                    touched.add(nm)
        for name in sorted(n for n in touched if n and n in old_sigs and _name_ok(n)):
            if name not in new_sigs:
                if name in everywhere:
                    where = next(p for p, d in new_defs.items() if name in d)
                    out.setdefault(name, (path, f"moved to {where}: imports of the old module"))
                else:
                    out.setdefault(name, (path, "removed or renamed"))
                continue
            if len(old_sigs[name]) != 1 or len(new_sigs[name]) != 1:
                continue                         # overloads or same-named methods: can't pair them up
            why = breaks(old_sigs[name][0], new_sigs[name][0], ext)
            if why:
                out.setdefault(name, (path, "; ".join(why)))
        if f.get("deleted"):
            for name in old_sigs:
                if _name_ok(name) and name not in everywhere:
                    out.setdefault(name, (path, "file deleted"))
    return out


def _call_rx(name):
    # a call, an import, or a line that is only the name (one entry of a multi-line import list)
    n = re.escape(name)
    return re.compile(rf"(?<![\w$]){n}\s*(?:<[^()]*>)?\s*\(|\bimport\b.*(?<![\w$]){n}(?![\w$])|"
                      rf"^\s*{n}(?:\s+as\s+\w+)?\s*,?\s*$|"
                      rf"(?<![\w$]){n}(?![\w$]).*\bfrom\s+['\"]|\brequire\(")


def sites(repo, contracts, changed_lines=None):
    """-> (lines, names): ["path:line: text"] call and import lines of each name outside the change's added lines,
    and {name: reason} for the names listed. Every name is searched (one git grep); at most MAX_NAMES of those with
    callers are listed, most specific (longest) first, and the others with callers are named."""
    if not contracts:
        return [], {}
    ranked = sorted(contracts, key=lambda n: (-len(n), n))
    ranked, unsearched = ranked[:MAX_SEARCH], ranked[MAX_SEARCH:]
    changed_lines, spans, rank = changed_lines or {}, {}, {n: i for i, n in enumerate(ranked)}
    by_name = {n: [] for n in ranked}
    rxs = {}
    for p, no, t in _grep(repo, ranked, CODE_SPECS):
        if no in changed_lines.get(p, ()) or COMMENT_RX.match(t):
            continue
        # only the names the line holds as whole words: testing every name on every hit grows as names x hits
        here = sorted(set(re.findall(r"[\w$]+", t)) & rank.keys(), key=rank.get)
        rx = DEF_RX.get(os.path.splitext(p)[1].lower())
        m = rx.match(t) if rx and here else None
        defined = {g for g in (m.groups() if m else ()) if g}
        found = [n for n in here if n not in defined and (rxs.get(n) or rxs.setdefault(n, _call_rx(n))).search(t)]
        if not found or no in _in_prose(repo, p, spans):
            continue
        for n in found:
            by_name[n].append((p, no, t, found))
    # a name with more sites than MAX_PER_NAME is counted, not listed, and doesn't take one of the MAX_NAMES slots
    common = [f"{n} ({len(by_name[n])} lines)" for n in ranked if len(by_name[n]) > MAX_PER_NAME]
    with_callers = [n for n in ranked if 0 < len(by_name[n]) <= MAX_PER_NAME]
    picked, rest = with_callers[:MAX_NAMES], with_callers[MAX_NAMES:] + unsearched
    out, listed = [], set()
    for n in picked:
        for p, no, t, found in by_name[n]:
            if (p, no) in listed:               # an import of several names: listed once, tagged with all of them
                continue
            listed.add((p, no))
            t = t.strip()
            out.append(f"{p}:{no}: {t[:LINE_CHARS] + (' ...' if len(t) > LINE_CHARS else '')}  [{', '.join(found)}]")
    if len(out) > MAX_LINES:
        out = out[:MAX_LINES] + [f"({len(out) - MAX_LINES} more lines not listed)"]
    if common:
        out.append(f"(too many to list; search them: {', '.join(common)})")
    if rest and (out or common):
        out.append(f"(more changed contracts, callers not listed: {', '.join(rest[:20])}"
                   f"{f' and {len(rest) - 20} more' if len(rest) > 20 else ''})")
    elif rest:
        out.append(f"(changed contracts not searched for callers: {', '.join(rest[:20])}"
                   f"{f' and {len(rest) - 20} more' if len(rest) > 20 else ''})")
    return out, {n: contracts[n] for n in picked}


def note(lines, names):
    """The prompt section, or "" when no caller outside the diff uses a changed contract."""
    if not lines:
        return ""
    head = "; ".join(f"{n} in {p}: {why}" for n, (p, why) in names.items())
    return ("Contracts this change altered, compared base -> HEAD: " + head + ".\n"
            "Call and import lines OUTSIDE this diff that use them, from a whole-word search of the checkout:\n" +
            "\n".join(lines) +
            "\nOpen each one. A caller this change breaks (passes a removed or renamed argument, misses a new required "
            "one, relies on the old order, default or return type, imports a name that is gone) is a finding at THAT "
            "file and line, with the definition as the cause. Callers that still work need nothing; say nothing "
            "about them.\n")
