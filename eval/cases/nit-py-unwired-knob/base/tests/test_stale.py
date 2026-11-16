from feeds.stale import filter_stale


def _m(price=50, **kw):
    return dict({"ticker": "AAA", "price": price}, **kw)


def test_unchanged_price_counts_as_idle():
    _, _, h = filter_stale([_m()], {"AAA": {"price": 50, "idle": 1}})
    assert h["AAA"]["idle"] == 2


def test_skipped_at_threshold():
    kept, skipped, _ = filter_stale([_m()], {"AAA": {"price": 50, "idle": 4}}, threshold=5)
    assert (kept, skipped) == ([], [_m()])


def test_zero_threshold_keeps_everything():
    kept, _, _ = filter_stale([_m()], {"AAA": {"price": 50, "idle": 99}}, threshold=0)
    assert kept == [_m()]
