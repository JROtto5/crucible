from .util import money


def totals_by_category(orders):
    totals = {}
    for o in orders:
        if o.get("refunded"):
            continue
        key = o["category"]
        totals[key] = totals.get(key, 0) + o["qty"] * o["price_cents"]
    return {k: money(v) for k, v in sorted(totals.items())}


def totals_by_vendor(orders):
    totals = {}
    for o in orders:
        if o.get("refunded"):
            continue
        key = o["vendor"]
        totals[key] = totals.get(key, 0) + o["qty"] * o["price_cents"]
    print("DEBUG vendor totals", totals)
    return {k: money(v) for k, v in sorted(totals.items())}
