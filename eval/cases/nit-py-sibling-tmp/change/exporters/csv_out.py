import csv
import os

FIELDS = ["id", "name", "total"]


def write(rows, path):
    # Readers poll the export directory, so they must never see a half-written file.
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
