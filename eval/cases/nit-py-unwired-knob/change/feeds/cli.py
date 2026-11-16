"""feeds scan: list the markets worth a look this cycle."""
import json
import sys
from pathlib import Path

from . import config
from .stale import filter_stale

STATE = Path.home() / ".feeds" / "stale.json"


def load_history():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def scan(markets, cfg):
    markets = [m for m in markets if m["price"] >= cfg.min_price][: cfg.max_markets]
    if cfg.stale_cycles > 0:
        markets, skipped, history = filter_stale(
            markets, load_history(),
            threshold=cfg.stale_cycles,
        )
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(history))
        if skipped:
            print(f"skipped {len(skipped)} stale market(s)", file=sys.stderr)
    return markets


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cfg = config.load(argv[0] if argv else "feeds.toml")
    markets = json.load(sys.stdin)
    for m in scan(markets, cfg):
        print(m["ticker"], m["price"])


if __name__ == "__main__":
    main()
