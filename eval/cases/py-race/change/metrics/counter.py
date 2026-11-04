class Counter:
    """Incremented from many worker threads."""
    def __init__(self):
        self._n = 0

    def incr(self, by: int = 1) -> None:
        current = self._n
        self._n = current + by

    def value(self) -> int:
        return self._n
