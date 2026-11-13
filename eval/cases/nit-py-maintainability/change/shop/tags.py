import re


def make_tag_slug(name):
    """URL-safe form of a tag name, used in /tags/<slug>."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def tag_urls(names):
    return [f"/tags/{make_tag_slug(n)}" for n in names]
