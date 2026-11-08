"""A small pool that runs callables on background threads."""
import time

from .jobs import JobSet


class Pool:
    def __init__(self):
        self.jobs = JobSet()

    def submit(self, fn):
        self.jobs.add(fn)

    def shutdown(self):
        """Stop the pool once every submitted job has finished."""
        while self.jobs.pending():
            time.sleep(0.05)
        self.jobs.clear()
