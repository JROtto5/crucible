"""gettext catalogs (.po/.pot) in a review: a digest of what a reviewer reads, not msgmerge's bookkeeping.

A catalog refresh (`msgmerge`, `xgettext`, a project's `update-po` target) rewrites thousands of lines: source
reference comments, line wrapping, new untranslated stubs, obsolete `#~` blocks. On Lutris #6952 (2026-11-07) a
one-line markup fix plus the refresh its maintainer asked for was 17k changed lines; 31 of 33 review chunks were
catalogs, and the round cost $19.45 and 41 minutes (a typical round is under $1). The model's catalog findings were
mostly the same "full refresh bundled with a small fix" point, once per language.

The digest keeps every touched entry that carries a translation, joined onto one line each, and counts the rest.
Untouched-text entries stay in it on purpose: on that PR the real catch (French links closed with `<a>`) was in an
entry the refresh only touched through its `#:` line.
"""
import bisect
import os
import re

CATALOG_RX = re.compile(r"\.pot?$")
DIGEST_MIN_LINES = 200        # smaller catalog diffs are hand edits: review them as a plain diff

_STR_RX = re.compile(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(".*")\s*$')
_CONT_RX = re.compile(r'^(".*")\s*$')
# what can break a translation at runtime rather than read badly: markup and entities (GTK/Qt show an empty label
# when markup doesn't parse), printf/format placeholders (a mismatch raises or prints garbage)
RUNTIME_RX = re.compile(r"<[A-Za-z/!]|&#?\w+;|%(?:\(\w+\))?[-#0 +]*\d*(?:\.\d+)?[sdifuxXcreEgG]|\{[\w.\[\]]*(?:![rsa])?(?::[^{}]*)?\}")


def is_catalog(path):
    return bool(CATALOG_RX.search(path or ""))


def _unquote(s):
    s = s[1:-1]
    return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def parse(text):
    """-> entries: {key:(ctx,id,plural), strs:[...], fuzzy, obsolete, start, end} with 1-based line numbers."""
    entries, cur, field = [], None, None

    def close():
        nonlocal cur
        if cur and ("msgid" in cur["f"]):
            f = cur["f"]
            strs = [f[k] for k in sorted(k for k in f if k.startswith("msgstr"))]
            entries.append({"key": (f.get("msgctxt"), f["msgid"], f.get("msgid_plural")), "strs": strs,
                            "fuzzy": cur["fuzzy"], "obsolete": cur["obsolete"], "start": cur["start"],
                            "end": cur["end"]})
        cur = None

    for no, raw in enumerate(text.split("\n"), 1):
        line = raw.strip()
        if not line:
            close(); field = None
            continue
        obsolete = line.startswith("#~")
        if obsolete:
            line = line[2:].lstrip()
            if line.startswith("|"):           # "#~|" previous-msgid lines
                continue
        # a comment or a new msgctxt/msgid after a msgstr starts the next entry, even without a blank line
        if cur is not None and field and field.startswith("msgstr") and not line.startswith('"') \
                and not line.startswith("msgstr"):
            close(); field = None
        if cur is None:
            cur = {"f": {}, "fuzzy": False, "obsolete": obsolete, "start": no, "end": no}
        cur["end"] = no
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line:
                cur["fuzzy"] = True
            continue
        m = _STR_RX.match(line)
        if m:
            field = m.group(1)
            cur["f"][field] = _unquote(m.group(2))
            continue
        m = _CONT_RX.match(line)
        if m and field:
            cur["f"][field] += _unquote(m.group(1))
    close()
    return entries


def runtime_sensitive(e):
    return any(RUNTIME_RX.search(s or "") for s in (e["key"][1], e["key"][2], *e["strs"]))


def _show(s, limit=4000):
    # a cut would hide the very markup an entry is listed for, so only absurd strings are cut, and visibly
    s = s.replace("\n", "\\n")
    return s if len(s) <= limit else s[:limit] + f"…[{len(s) - limit} more chars, open the file]"


# entries go out in "@@" blocks so diff.chunk can split a big digest the way it splits hunks; a block closes at
# BLOCK entries or BLOCK_CHARS characters, whichever comes first, so long strings can't push one past a chunk
BLOCK, BLOCK_CHARS = 25, 15000


def digest(path, old_text, new_text, changed_new_lines, changed_old_lines=0):
    """A review text for one catalog's diff. changed_new_lines: line numbers added in the new file.

    Must show: every translation the change edits, adds or clears (old and new); every touched entry whose
    unchanged translation has markup, entities or placeholders; in a .pot, every msgid new to the template.
    Must count, not show: unchanged plain-text translations, untranslated stubs in a .po, msgmerge's fuzzy
    guesses for new msgids, obsolete (#~) entries."""
    template = path.endswith(".pot")
    old = {e["key"]: e for e in parse(old_text or "") if not e["obsolete"]}
    new = parse(new_text or "")
    changed_new_lines = set(changed_new_lines)
    marks = sorted(changed_new_lines)

    def touched_entry(e):                     # any added line inside the entry; bisect, not a scan per entry
        i = bisect.bisect_left(marks, e["start"])
        return i < len(marks) and marks[i] <= e["end"]
    edited, touched, new_ids, fuzzy_new, untranslated, obsoleted, plain = [], [], [], [], 0, 0, 0
    for e in new:
        if e["obsolete"]:
            if e["key"] in old:
                obsoleted += 1
            continue
        if not touched_entry(e):
            continue
        has_text = any(s for s in e["strs"])
        prev = old.get(e["key"])
        had_text = bool(prev) and any(s for s in prev["strs"])
        if not has_text and not had_text:
            if template and prev is None:
                new_ids.append(e)
            else:
                untranslated += 1
        elif prev is None:
            (fuzzy_new if e["fuzzy"] else edited).append((e, None))
        elif prev["strs"] != e["strs"] or prev["fuzzy"] != e["fuzzy"]:
            edited.append((e, prev))              # includes a translation cleared to ""
        elif runtime_sensitive(e):
            touched.append(e)
        else:
            plain += 1
    new_keys = {e["key"] for e in new}
    removed = sum(1 for k in old if k not in new_keys)
    out = [f"diff --git a/{path} b/{path}",
           f"[crucible: {path} is a gettext {'template' if template else 'catalog'} with {len(changed_new_lines)} "
           f"added and {changed_old_lines} removed lines. It is shown as a digest of its entries, not as a diff: "
           f"source-reference comments, line wrapping and obsolete blocks are left out. Each entry is "
           f"`L<line in the new file>`, the msgid and the msgstr, each joined onto one line (\\n is a newline in "
           f"the string). Open the file at that line when you need the raw text.]",
           f"[not shown: {plain} touched entries whose translation is unchanged plain text (no markup or "
           f"placeholders, so nothing in them can fail at runtime), {untranslated} touched entries without a "
           f"translation, {len(fuzzy_new)} new fuzzy guesses from msgmerge (gettext ignores fuzzy entries at "
           f"runtime), {obsoleted} entries now obsolete (#~), {removed} entries removed outright]"]

    def entry(e, prev=None, tag=""):
        ctx = f" msgctxt \"{_show(e['key'][0])}\"" if e["key"][0] else ""
        rows = [f"L{e['start']}{tag}{ctx} msgid \"{_show(e['key'][1])}\""]
        if e["key"][2] is not None:
            rows.append(f"  msgid_plural \"{_show(e['key'][2])}\"")
        if prev is not None:
            rows += [f"  - msgstr \"{_show(s)}\"" for s in prev["strs"]]
        if prev is not None or not template:      # a template's new msgids have nothing but msgstr ""
            rows += [f"  {'+ ' if prev is not None else ''}msgstr \"{_show(s)}\"" for s in e["strs"]]
        return "\n".join(rows)

    sections = [("translations this change edits (old `-`, new `+`)",
                 [entry(e, p, " (fuzzy)" if e["fuzzy"] else "") for e, p in edited]),
                ("msgids new to this template", [entry(e) for e in new_ids]),
                ("translated entries with markup or placeholders that the change touched without editing their text "
                 "(references or wrapping); a broken one is a pre-existing bug, not this change's",
                 [entry(e) for e in touched])]
    for title, rows in sections:
        if not rows and title.startswith("msgids new"):
            continue
        out.append(f"\n## {title}: {len(rows)}")
        blocks, cur, size = [], [], 0
        for r in rows:
            if cur and (len(cur) >= BLOCK or size + len(r) > BLOCK_CHARS):
                blocks.append(cur); cur, size = [], 0
            cur.append(r); size += len(r)
        if cur:
            blocks.append(cur)
        first = 1
        for b in blocks:                          # the full title on every block: a split chunk keeps the caveat
            out.append(f"@@ {title}, entries {first}-{first + len(b) - 1} of {len(rows)} @@")
            out.extend(b); first += len(b)
    return "\n".join(out) + "\n"


def changed_lines(f):
    """(added line numbers in the new file, removed line count) from a parsed diff file."""
    added, removed = [], 0
    for h in f["hunks"]:
        for kind, _t, _o, n in h["lines"]:
            if kind == "+":
                added.append(n)
            elif kind == "-":
                removed += 1
    return added, removed


def should_digest(f):
    if f["binary"] or f["deleted"] or not is_catalog(f["path"]):
        return False
    added, removed = changed_lines(f)
    return len(added) + removed >= DIGEST_MIN_LINES


def enabled():
    return os.environ.get("CRUCIBLE_CATALOG_DIGEST", "1").strip().lower() not in ("0", "false", "no", "off")


def digest_files(files, read_old, read_new):
    """Swap the review text of each big catalog diff in `files` for its digest. read_old/read_new(path) -> the
    file's text at the old/new commit ("" when absent). Hunks are left alone (scanners and line mapping use them).
    -> the digested paths."""
    out = []
    if not enabled():
        return out
    for f in files:
        if not should_digest(f):
            continue
        added, removed = changed_lines(f)
        old = "" if f["added"] else read_old(f["old_path"] or f["path"])
        f["text"] = digest(f["path"], old, read_new(f["path"]), added, removed)
        out.append(f["path"])
    return out
