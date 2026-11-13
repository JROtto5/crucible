def cart_total(items):
    subtotal = sum(i["cents"] * i.get("qty", 1) for i in items)
    return subtotal + round(subtotal * 0.0825)
