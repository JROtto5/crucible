from jot.cli import main
from jot.store import Store


def test_add_then_show(tmp_path, capsys):
    store = Store(str(tmp_path / "j.json"))
    assert main(["add", "2026-11-20", "dentist"], store) == 0
    assert main(["show", "2026-11-20"], store) == 0
    assert "dentist" in capsys.readouterr().out


def test_delete(tmp_path, capsys):
    store = Store(str(tmp_path / "j.json"))
    main(["add", "2026-11-20", "dentist"], store)
    assert main(["delete", "2026-11-20"], store) == 0
    assert "Deleted" in capsys.readouterr().out
