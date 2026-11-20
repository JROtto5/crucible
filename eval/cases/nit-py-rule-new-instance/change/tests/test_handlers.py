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


def test_read_too_big(tmp_path, monkeypatch):
    (tmp_path / "big.md").write_text("x" * 20)
    monkeypatch.setattr(paths, "ROOT", str(tmp_path))
    monkeypatch.setattr(handlers, "MAX_NOTE_BYTES", 10)
    with pytest.raises(paths.RequestError, match="byte limit"):
        handlers.read_note({"path": "big.md"})
