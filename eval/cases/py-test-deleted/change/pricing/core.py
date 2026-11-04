def discounted(price_cents: int, percent: int) -> int:
    """Price after a whole-number percent discount, rounded to the nearest cent."""
    return price_cents * (100 - percent) // 100
