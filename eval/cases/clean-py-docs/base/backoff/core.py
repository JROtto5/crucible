def delay(attempt: int, base: float = 0.1, cap: float = 5.0) -> float:
    return min(cap, base * 2 ** attempt)
