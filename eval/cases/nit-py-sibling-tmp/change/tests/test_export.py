import json

from exporters import export

ROWS = [{"id": 1, "name": "a", "total": 3}, {"id": 2, "name": "b", "total": 5}]


def test_csv(tmp_path):
    p = tmp_path / "r.csv"
    export(ROWS, str(p), "csv")
    assert p.read_text(encoding="utf-8").splitlines()[0] == "id,name,total"


def test_json(tmp_path):
    p = tmp_path / "r.json"
    export(ROWS, str(p), "json")
    assert json.loads(p.read_text(encoding="utf-8"))["count"] == 2


def test_ndjson(tmp_path):
    p = tmp_path / "r.ndjson"
    export(ROWS, str(p), "ndjson")
    assert len(p.read_text(encoding="utf-8").splitlines()) == 2


def test_replaces_an_existing_export(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("old", encoding="utf-8")
    export(ROWS, str(p), "json")
    assert json.loads(p.read_text(encoding="utf-8"))["count"] == 2
    assert not (tmp_path / "r.json.tmp").exists()
