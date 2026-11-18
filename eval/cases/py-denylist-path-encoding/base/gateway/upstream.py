"""Forward a request path to the app server's router."""
import posixpath
from urllib.parse import unquote

ROUTES = {}


def route(prefix):
    def deco(fn):
        ROUTES[prefix] = fn
        return fn
    return deco


def forward(raw_path, user):
    path = posixpath.normpath(unquote(raw_path))
    for prefix, fn in sorted(ROUTES.items(), key=lambda kv: -len(kv[0])):
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            return fn(path, user)
    return 404, "not found"
