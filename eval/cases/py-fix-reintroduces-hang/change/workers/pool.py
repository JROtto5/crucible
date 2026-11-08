"""A small pool that runs callables on background threads."""
import time

from .jobs import JobSet

# A job that never returns used to hang shutdown() forever (#41).
SHUTDOWN_TIMEOUT = 5.0


class Pool:
    def __init__(self):
        self.jobs = JobSet()

    def submit(self, fn):
        self.jobs.add(fn)

    def shutdown(self, timeout=SHUTDOWN_TIMEOUT):
        """Stop the pool. Jobs still running after `timeout` seconds are abandoned (they are daemon
        threads), so shutdown always returns. Returns True when every job finished in time."""
        self.jobs.clear()
        deadline = time.monotonic() + timeout
        while self.jobs.pending() and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.jobs.pending()
