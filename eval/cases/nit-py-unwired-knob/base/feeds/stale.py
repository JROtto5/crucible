"""Staleness tracking: drop markets that have shown no movement for several scans in a row."""


def filter_stale(markets, history, threshold=5):
    """Split markets into (kept, skipped) and return the updated history.

    history maps a ticker to {"price": last seen price, "idle": consecutive idle scans}.
    """
    kept, skipped, out = [], [], {}
    for m in markets:
        prev = history.get(m["ticker"], {})
        idle = prev.get("idle", 0) + 1 if prev.get("price") == m["price"] else 0
        out[m["ticker"]] = {"price": m["price"], "idle": idle}
        (skipped if threshold and idle >= threshold else kept).append(m)
    return kept, skipped, out
