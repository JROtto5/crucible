import json
from dataclasses import dataclass


@dataclass
class Settings:
    """How entries are ranked. `strict`: entries with a missing score are an error instead of being skipped."""
    strict: bool = True
    min_score: float = float("-inf")


def load_settings(path):
    with open(path) as fh:
        return Settings(**json.load(fh))
