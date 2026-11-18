import pytest

from webhooks.registry import register, url_for
from webhooks.send import BlockedURL, check_url


def test_public_url_is_kept():
    register(1, "invoice.paid", "https://hooks.example.com/in")
    assert url_for(1, "invoice.paid") == "https://hooks.example.com/in"


@pytest.mark.parametrize("url", [
    "http://localhost/admin",
    "http://LOCALHOST:8080/",
    "http://127.0.0.1:9000/",
    "http://169.254.169.254/latest/meta-data/",
    "file:///etc/passwd",
])
def test_internal_urls_are_refused(url):
    with pytest.raises(BlockedURL):
        check_url(url)
