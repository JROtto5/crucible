import os

ROOT = os.environ.get("NOTES_ROOT", "/var/lib/notes")


class RequestError(Exception):
    pass


def inside_root(path: str, root: str | None = None) -> str:
    """The absolute form of `path` under `root` (default ROOT); RequestError if it would leave it."""
    base = os.path.realpath(root or ROOT)
    full = os.path.realpath(os.path.join(base, path))
    if os.path.commonpath([full, base]) != base:
        raise RequestError("path outside the notes root")
    return full
