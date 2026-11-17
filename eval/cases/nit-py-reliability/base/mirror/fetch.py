import urllib.request

TIMEOUT = 10  # seconds; the index host is slow but never this slow


def head(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return int(resp.headers.get("Content-Length", 0))
