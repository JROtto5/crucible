"""CORS check for the project API."""
from .merge import effective


def origin_allowed(project, origin):
    origins = effective(project)["allowed_origins"]
    return "*" in origins or origin in origins
