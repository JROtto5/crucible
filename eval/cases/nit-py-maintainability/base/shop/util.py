import re


def slugify(text):
    """Lowercase `text` and join its words with single dashes: "Red Shoes!" -> "red-shoes"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def money(cents):
    return f"{cents // 100}.{cents % 100:02d}"
