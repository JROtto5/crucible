"""App routes."""
from .upstream import route


@route("/admin")
def admin(path, user):
    return 200, f"admin console for {user}"


@route("/internal/metrics")
def metrics(path, user):
    return 200, "uptime 99.99"


@route("/docs")
def docs(path, user):
    return 200, "docs"
