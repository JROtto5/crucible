"""Tiny markup check for UI labels: <b>, <i> and <a href="..."> only.

A string the toolkit can't parse shows up as an empty label, so to_label()
returns "" on any error, the same way the real widget does.
"""
import re

TAG = re.compile(r'<(/?)(b|i|a)((?:\s+[a-z]+="[^"<>]*")*)\s*>')


class MarkupError(ValueError):
    pass


def parse(s):
    """Return the plain text of ``s``, or raise MarkupError."""
    out, stack, pos = [], [], 0
    while True:
        lt = s.find("<", pos)
        if lt < 0:
            out.append(s[pos:])
            break
        out.append(s[pos:lt])
        m = TAG.match(s, lt)
        if not m:
            raise MarkupError(f"bad tag at {lt}: {s[lt:lt + 20]!r}")
        closing, name = m.group(1), m.group(2)
        if closing:
            if not stack or stack.pop() != name:
                raise MarkupError(f"unexpected </{name}> at {lt}")
        else:
            stack.append(name)
        pos = m.end()
    if stack:
        raise MarkupError(f"unclosed <{stack[-1]}>")
    return "".join(out)


def to_label(s):
    try:
        return parse(s)
    except MarkupError:
        return ""
