from pricing.core import discounted

def test_no_discount():
    assert discounted(500, 0) == 500
