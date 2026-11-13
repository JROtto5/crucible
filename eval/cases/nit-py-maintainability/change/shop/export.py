import csv
import io


def export_csv(items):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["sku", "name", "price_cents"])
    for it in items:
        w.writerow([it["sku"], it["name"], it["price_cents"]])
    return out.getvalue()


def legacy_export(items):
    """Pipe-separated export for the old warehouse importer."""
    return "\n".join(f"{it['sku']}|{it['name']}|{it['price_cents']}" for it in items)


def export_all(items):
    # The old warehouse importer is gone; everything is CSV now.
    return export_csv(items)
