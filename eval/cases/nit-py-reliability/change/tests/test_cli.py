from mirror import cli


def test_size(monkeypatch, capsys):
    monkeypatch.setattr(cli, "head", lambda url: 42)
    assert cli.main(["size", "http://x/a"]) == 0
    assert capsys.readouterr().out.strip() == "42"
