def rank(scores):
    """Indices of `scores` (any sequence of numbers), best first."""
    values = list(scores)
    return sorted(range(len(values)), key=lambda i: values[i], reverse=True)


def top(scores, n=3):
    """The `n` best indices."""
    return rank(scores)[:n]
