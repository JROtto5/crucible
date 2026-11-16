"""Scanner settings, read from feeds.toml ([scanner] table)."""
import tomllib
from dataclasses import dataclass, fields


@dataclass
class ScanConfig:
    # skip a market after this many scans with no activity; 0 turns the filter off
    stale_cycles: int = 5
    # markets priced below this (in cents) are ignored
    min_price: int = 3
    max_markets: int = 200


def load(path):
    with open(path, "rb") as fh:
        raw = tomllib.load(fh).get("scanner", {})
    known = {f.name for f in fields(ScanConfig)}
    return ScanConfig(**{k: v for k, v in raw.items() if k in known})
