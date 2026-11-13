def format_row(sku, qty, cents):
    return f"{sku:<12}{qty:>5}{cents / 100:>10.2f}"
