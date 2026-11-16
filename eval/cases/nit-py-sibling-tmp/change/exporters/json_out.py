import json
import os


def write(rows, path):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"rows": rows, "count": len(rows)}, fh, indent=2)
    os.replace(tmp, path)
