"""Public edge: every external request comes through here."""
import logging
import time

from .upstream import forward

log = logging.getLogger(__name__)

# Operator-only areas. They are served on the internal listener; the public edge must never reach them.
BLOCKED_PREFIXES = ("/admin", "/internal")


def handle(raw_path, user):
    started = time.monotonic()
    if raw_path.lower().startswith(BLOCKED_PREFIXES):
        log.info("blocked %s for %s", raw_path, user)
        return 403, "forbidden"
    status, body = forward(raw_path, user)
    log.info("%s %s %.1fms", status, raw_path, (time.monotonic() - started) * 1000)
    return status, body
