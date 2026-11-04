from pricing.core import discounted

def test_rounds_to_nearest_cent():
    assert discounted(995, 15) == 846

def test_no_discount():
    assert discounted(500, 0) == 500
