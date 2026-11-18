"""Outbound calls a project makes, retried per its settings."""
import time

from .merge import effective


def call_with_retries(project, fn):
    s = effective(project)
    for attempt in range(s["retries"] + 1):
        try:
            return fn(timeout=s["timeout_s"])
        except TimeoutError:
            if attempt == s["retries"]:
                raise
            time.sleep(2 ** attempt)
