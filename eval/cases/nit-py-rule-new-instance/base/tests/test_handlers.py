import pytest

from notes import handlers, paths


def test_list_and_read(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("hello")
    monkeypatch.setattr(paths, "ROOT", str(tmp_path))
    assert handlers.list_notes({"folder": str(tmp_path)}) == {"names": ["a.md"]}
    assert handlers.read_note({"path": "a.md"}) == {"text": "hello"}


def test_read_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROOT", str(tmp_path))
    with pytest.raises(paths.RequestError):
        handlers.read_note({"path": "nope.md"})
