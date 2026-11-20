import os

from notes.paths import RequestError, inside_root

MAX_NOTE_BYTES = 1_000_000


def list_notes(req: dict) -> dict:
    folder = inside_root(req.get("folder", "."))
    return {"names": sorted(n for n in os.listdir(folder) if n.endswith(".md"))}


def read_note(req: dict) -> dict:
    path = inside_root(req["path"])
    if not os.path.exists(path):
        raise RequestError(f"no such note: {path}")
    size = os.stat(path).st_size
    if size > MAX_NOTE_BYTES:
        raise RequestError(f"{path} is {size} bytes, over the {MAX_NOTE_BYTES} byte limit")
    with open(path, encoding="utf-8") as f:
        return {"text": f.read()}


def delete_note(req: dict) -> dict:
    os.remove(inside_root(req["path"]))
    return {"ok": True}
