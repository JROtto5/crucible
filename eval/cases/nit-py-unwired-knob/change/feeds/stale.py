"""Staleness tracking: drop markets that have shown no trading activity for several scans in a row."""


def filter_stale(markets, history, threshold=5, min_volume=10):
    """Split markets into (kept, skipped) and return the updated history.

    history maps a ticker to {"price": last seen price, "idle": consecutive idle scans}. A market with at least
    min_volume contracts traded since the last scan is active even when its price did not move.
    """
    kept, skipped, out = [], [], {}
    for m in markets:
        prev = history.get(m["ticker"], {})
        active = prev.get("price") != m["price"] or m.get("volume", 0) >= min_volume
        idle = 0 if active else prev.get("idle", 0) + 1
        out[m["ticker"]] = {"price": m["price"], "idle": idle}
        (skipped if threshold and idle >= threshold else kept).append(m)
    return kept, skipped, out
