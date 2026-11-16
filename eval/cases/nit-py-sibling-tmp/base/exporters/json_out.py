import json


def write(rows, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"rows": rows, "count": len(rows)}, fh, indent=2)
