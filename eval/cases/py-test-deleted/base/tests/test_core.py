from pricing.core import discounted

def test_rounds_to_nearest_cent():
    assert discounted(999, 15) == 849

def test_no_discount():
    assert discounted(500, 0) == 500
