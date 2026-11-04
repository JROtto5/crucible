import threading

class Counter:
    """Incremented from many worker threads."""
    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def incr(self, by: int = 1) -> None:
        with self._lock:
            self._n += by

    def value(self) -> int:
        return self._n
