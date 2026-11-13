from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount):
    """Parse a price like "12.5" or 12.5 into integer cents, rounding half up."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
