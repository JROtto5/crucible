"""Write report rows to disk in one of three formats."""
from . import csv_out, json_out, ndjson_out

WRITERS = {"csv": csv_out.write, "json": json_out.write, "ndjson": ndjson_out.write}


def export(rows, path, fmt):
    WRITERS[fmt](rows, path)
