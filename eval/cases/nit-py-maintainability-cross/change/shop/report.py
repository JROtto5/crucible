def line_items(order):
    return [f"{i['sku']} x{i['qty']}" for i in order["items"]]
