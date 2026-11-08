"""Background jobs and the set that owns them."""
import threading


class Job:
    def __init__(self, fn):
        self._thread = threading.Thread(target=fn, daemon=True)
        self._thread.start()

    def done(self):
        return not self._thread.is_alive()

    def close(self):
        # Wait for the job so whatever it holds is released before the pool goes away.
        self._thread.join()


class JobSet:
    def __init__(self):
        self._jobs = []

    def add(self, fn):
        self._jobs.append(Job(fn))

    def pending(self):
        return [j for j in self._jobs if not j.done()]

    def clear(self):
        """Close every job and forget it."""
        for job in self._jobs:
            job.close()
        self._jobs = []

    def forget_done(self):
        """Forget finished jobs without waiting on the ones still running."""
        self._jobs = [j for j in self._jobs if not j.done()]
