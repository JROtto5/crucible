def delay(attempt: int, base: float = 0.1, cap: float = 5.0) -> float:
    """Seconds to wait before retry number `attempt` (0-based): base * 2**attempt, capped at `cap`."""
    return min(cap, base * 2 ** attempt)
