from .settings import Settings


def rank(scores, settings=None):
    """Entry names of `scores` ({name: score}), best first. Entries below settings.min_score are left out."""
    settings = settings or Settings()
    floor = settings.min_score
    if settings.strict and any(score is None for score in scores.values()):
        raise ValueError("an entry has no score")
    names = [name for name, score in scores.items() if score is not None and score >= floor]
    print("rank:", names)
    return sorted(names, key=lambda name: scores[name], reverse=True)


def top(scores, n=3, settings=None):
    """The `n` best entry names."""
    return rank(scores, settings)[:n]
