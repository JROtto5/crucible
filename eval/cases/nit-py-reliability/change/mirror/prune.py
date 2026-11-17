import logging
import os
import time

log = logging.getLogger(__name__)


def prune(cache_dir, max_age_s):
    """Delete cached files older than max_age_s. Returns how many were removed."""
    cutoff = time.time() - max_age_s
    stale = [e.path for e in os.scandir(cache_dir) if e.is_file() and e.stat().st_mtime < cutoff]
    for path in stale:
        try:
            os.remove(path)
        except OSError as exc:
            log.warning("could not remove %s: %s", path, exc)
    return len(stale)
