def vendor_name(vendors, vendor_id):
    return vendors.get(vendor_id, {}).get("name", "unknown")
