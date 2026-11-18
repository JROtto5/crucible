from store.index import UserIndex


def test_add_is_idempotent():
    ix = UserIndex()
    ix.add(3)
    ix.add(3)
    assert len(ix) == 1 and 3 in ix


def test_discard_missing_is_fine():
    ix = UserIndex()
    ix.discard(9)
    assert len(ix) == 0
