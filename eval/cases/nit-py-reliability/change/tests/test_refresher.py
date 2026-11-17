import threading

from mirror import refresher


def test_refresher_downloads_index(monkeypatch, tmp_path):
    got = threading.Event()
    monkeypatch.setattr(refresher, "fetch", lambda url: got.set() or b"{}")
    refresher.Refresher("http://x/index.json", str(tmp_path), interval=3600).start()
    assert got.wait(2)
