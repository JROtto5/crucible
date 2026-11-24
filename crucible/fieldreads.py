"""Field names a change reads that nothing writes, beside a similar name the change writes and nothing reads ($0: git
grep, no model call).

ReviewBench run 6 never raised apilix #26 (high): the settings form stores the S3 credentials under `accessKeyId` and
`secretAccessKey`, and the adapter in another file reads `config.keyId` and `config.secret`, so every request is built
with undefined credentials. Each file looks right on its own; the bug is the pair. This lists a member read on an
added line (`recv.field`, `recv["field"]` or `recv.get("field")`; not a call, not an assignment) when nothing in the change or the checkout writes that name
(as a key, a quoted string, an assignment or a keyword) and the change does write a name that shares its words at one
end (`keyId` / `accessKeyId`, `user_id` / `userId` excluded: same words, a serializer's job) that nothing reads.

Replayed at $0 before shipping: on R6's 25 PRs it fires once, on apilix #26; on 1,047 recent commits of seven
projects we work in (colyseus, schema, supabase-js, Lutris, umu, Heroic, MangoHud) it fires on none once a receiver
bound by an import is skipped. The reviewer still judges each pair; nothing here is a finding.
"""
import re

from .docrefs import CODE_SPECS, COMMENT_RX, _grep
from .util import CODE_EXT_RX, TEST_PATH_RX

MAX_ROWS = 6
LINE_CHARS = 140
# receivers that are the language, the runtime or a test harness, never the change's own data
SKIP_RECV = {"this", "self", "cls", "super", "Math", "JSON", "console", "window", "document", "process", "os", "sys",
             "path", "re", "np", "pd", "torch", "module", "exports", "require", "e", "err", "error", "event", "ev",
             "evt", "json", "math", "time", "datetime", "logging", "logger", "log", "fs", "util", "utils", "assert",
             "expect", "t", "it", "vi", "jest", "mock", "pytest", "location", "navigator", "history", "crypto", "http",
             "url", "globalThis"}
STRING_RX = re.compile(r"""(['"`])(?:\\.|(?!\1).)*\1""")
# a receiver: a bare name, or one link after `this.` / `self.` (`this.config.keyId`); deeper chains
# (`a.b.c.keyId`) are left out, since the replay has no case of them and each link widens what can match
RECV = r"(?:(?<=\bthis\.)|(?<=\bself\.)|(?<![\w.$]))"
# `recv.field` or `recv?.field`, not a call, not the target of an assignment
# (inside a lookahead, so matches overlap: `this.config` must not consume `config.keyId`)
READ_RX = re.compile(r"(?=" + RECV + r"([a-z_][A-Za-z0-9_]*)\??\.([A-Za-z_][A-Za-z0-9_]{3,})\b"
                     r"(?!\s*\()(?!\s*(?:=(?!=)|\+=|-=|\|\|=|\?\?=|&&=)))")
# a name the change writes: a quoted string or a key (`name:`)
WRITE_RX = re.compile(r"""(['"`])([A-Za-z_][A-Za-z0-9_]{3,})\1|(?<![\w.$])([A-Za-z_][A-Za-z0-9_]{3,})\s*\??\s*:(?!:)""")
# `recv["field"]` or `recv.get("field"`, a dict read (Python configs, JSON bodies)
KEY_READ_RX = re.compile(r"(?=" + RECV + r"""([a-z_][A-Za-z0-9_]*)(?:\[\s*(['"])([A-Za-z_][A-Za-z0-9_]{3,})\2\s*\]"""
                         r"""(?!\s*(?:=(?!=)|\+=|-=))|\.get\(\s*(['"])([A-Za-z_][A-Za-z0-9_]{3,})\4))""")
IMPORT_RX = re.compile(r"^\s*(?:from\s+\S+\s+)?import\b|\brequire\s*\(")


def _words(s):
    return [x.lower() for x in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", s)]


def similar(read, written):
    """True when one name's words are the other's first or last words, two or more of them: keyId / accessKeyId,
    userName / user_name_display. Same words in another case or separator (user_id / userId) is False: JSON tags,
    aliases and serializers map those on purpose."""
    a, b = _words(read), _words(written)
    if a == b:
        return False
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return len(short) >= 2 and (long_[-len(short):] == short or long_[:len(short)] == short)


def _writes_rx(n):
    n = re.escape(n)
    # a key, a quoted string, an assignment or keyword, or a definition that computes it: a property or getter
    # (`def launcher_service(self)` under @property, umu c227efa9), a Go/Rust method, a class method `name() {`
    return re.compile(rf"""(['"`]){n}\1|(?<![\w.$]){n}\s*\??\s*:(?!:)|\.{n}\s*=(?!=)|\[\s*['"]{n}['"]\s*\]\s*=(?!=)|"""
                      rf"""(?<![\w.$]){n}\s*=(?!=)|\b(?:def|get|fn|func)\s+(?:\([^)]*\)\s*)?{n}\s*[(<]|"""
                      rf"""^\s*(?:(?:public|private|protected|static|async|override|readonly)\s+)*{n}\s*\([^)]*\)\s*(?::[^{{]*)?\{{""")


def _reads_rx(n, plain=False):
    """A line reading the name: a member, subscript or .get() read, getattr(), or an assigned destructure
    (`const { accessKeyId } = cfg`, `const { accessKeyId: id } = c`). Unless `plain`, also a parameter destructure
    (`({ accessKeyId }: Cfg) =>`) or a line holding only the name inside a wrapped one (`  accessKeyId,`), never
    `  accessKeyId: string,` (a declaration writes it). A shorthand object passed on (`f({ accessKeyId })`) matches
    those too: that silences the pair, the safe side for a note. plain=True is for a line that also writes the name
    (`saveConfig({ accessKeyId: k })`), where only a read the write can't mimic counts."""
    n = re.escape(n)
    rx = (rf"""\.{n}\b(?!\s*=(?!=))|\[\s*['"]{n}['"]\s*\](?!\s*=(?!=))|\.get\(\s*['"]{n}['"]|"""
          rf"""\bgetattr\([^,]+,\s*['"]{n}['"]|\{{[^{{}}]*(?<![\w$.]){n}(?![\w$])[^{{}}]*\}}\s*""")
    return re.compile(rx + (r"=(?!=)" if plain else rf"""(?:=(?!=)|:|\)|=>)|^\s*{n}\s*,?\s*$"""))


def _code(p):
    return bool(p) and bool(CODE_EXT_RX.search(p.lower()))


def mismatches(repo, files, read_text, paths=None):
    """parsed diff (the whole change) -> [(path, line, "recv.field", [(written, path, line)])]: each read on an added
    line of a code file outside the tests (and in `paths`, when given) of a name nothing writes, with the similar
    names the change writes on another line and nothing reads. read_text(path) -> the file at HEAD, to skip a
    receiver its imports bind (`ts.ModuleResolutionKind`)."""
    added = [(f["path"], n, t) for f in files if not f.get("deleted") and _code(f.get("path"))
             for h in f["hunks"] for k, t, _, n in h["lines"] if k == "+" and not COMMENT_RX.match(t)]
    written = {}
    for p, n, t in added:
        for m in WRITE_RX.finditer(t):
            written.setdefault(m.group(2) or m.group(3), []).append((p, n))
    out, seen, texts, orphan = [], set(), {}, {}

    def is_orphan(w):
        if w not in orphan:
            rx, plain = _reads_rx(w), _reads_rx(w, plain=True)
            own = set(written[w])                  # a line that writes the name reads it only in a plain read
            lines = [(p2, n2, t) for p2, n2, t in added] + [
                (p2, n2, t) for p2, n2, t in _grep(repo, [w], CODE_SPECS) if not COMMENT_RX.match(t)]
            orphan[w] = not any((plain if (p2, n2) in own else rx).search(t) for p2, n2, t in lines)
        return orphan[w]

    for p, n, t in added:
        if TEST_PATH_RX.search(p) or (paths is not None and p not in paths) or IMPORT_RX.match(t):
            continue
        reads = [m.groups() for m in READ_RX.finditer(STRING_RX.sub('""', t))]
        reads += [(m.group(1), m.group(3) or m.group(5)) for m in KEY_READ_RX.finditer(t)]
        for recv, field in reads:
            if recv in SKIP_RECV or (recv, field) in seen:
                continue
            seen.add((recv, field))
            sims = [w for w in written if similar(field, w) and any(s != (p, n) for s in written[w])]
            if not sims:
                continue
            if p not in texts:
                texts[p] = read_text(p) or ""
            if re.search(rf"^.*(?:\bimport\b|\brequire\s*\().*(?<![\w$]){re.escape(recv)}(?![\w$])", texts[p], re.M):
                continue
            r, f = re.escape(recv), re.escape(field)
            wrx = _writes_rx(field)
            # the read's own line doesn't write it: `keyId: config.keyId`, `x = cfg["keyId"]`
            here = re.compile(rf"""(?<![\w$]){r}(?:\??\.{f}\b|\[\s*['"]{f}['"]|\.get\(\s*['"]{f}['"])""")
            if any(wrx.search(t2) and not here.search(t2) for _, _, t2 in added):
                continue
            if any(wrx.search(t2) and not here.search(t2) for _, _, t2 in _grep(repo, [field], CODE_SPECS)
                   if not COMMENT_RX.match(t2)):
                continue
            sims = [w for w in sims if is_orphan(w)]
            if sims:
                out.append((p, n, f"{recv}.{field}",
                            [(w, *next(s for s in written[w] if s != (p, n))) for w in sims[:3]]))
    return out[:MAX_ROWS]


def note(rows, lines=None):
    """The prompt section, or "" when there are no rows. lines: {(path, line): text} for the quoted lines."""
    if not rows:
        return ""
    lines = lines or {}

    def q(p, n):
        t = (lines.get((p, n)) or "").strip()
        return f"{p}:{n}" + (f": {t[:LINE_CHARS]}" if t else "")
    body = "\n".join(f"- read {r} at {q(p, n)}\n" + "\n".join(f"  written {w} at {q(wp, wn)}" for w, wp, wn in ws)
                     for p, n, r, ws in rows)
    return ("Fields this change reads that nothing in the change or the checkout writes, each beside a similar name "
            "the change writes and nothing reads (from a whole-word search of the checkout):\n" + body +
            "\nOpen both ends of each pair. If they are meant to be the same value under two names (one side stores "
            "or sends it as one name, the other reads it as another), the reader always gets nothing (undefined, "
            "None, a zero value): a finding at the read, naming the write as also_at. If the read is filled by "
            "something the search can't see (a library, a schema, a computed key), say nothing.\n")
