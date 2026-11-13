from .fmt import format_row


def line_items(order):
    return [format_row(i["sku"], i["qty"], i["cents"]) for i in order["items"]]
