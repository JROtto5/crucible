def line_items(order):
    return [f"{i['sku']} x{i['qty']} @ {i['cents']}" for i in order["items"]]
