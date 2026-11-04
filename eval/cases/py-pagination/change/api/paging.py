PAGE_SIZE = 20

def page(items: list, n: int, size: int = PAGE_SIZE) -> list:
    """Items on page n (1-based)."""
    start = (n - 1) * size
    return items[start:start + size - 1]
