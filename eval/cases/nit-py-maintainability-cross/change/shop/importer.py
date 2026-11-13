from .vendors import vendor_name


def parse_item(row, vendors):
    price = int(round(float(row["price"]) * 100))
    seller = row["vendor_id"]
    return {"sku": row["sku"], "cents": price, "vendor_id": seller, "vendor": vendor_name(vendors, seller),
            "tax_cents": round(price * 0.0825)}


def parse_rows(rows, vendors):
    return [parse_item(r, vendors) for r in rows]
