"""Deliver webhook events to customer-supplied URLs."""
import json
import urllib.request
from urllib.parse import urlsplit

TIMEOUT_S = 5

# A customer's webhook URL must never reach our own services or the cloud metadata endpoint.
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"}


class BlockedURL(ValueError):
    pass


def check_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL(f"scheme {parts.scheme!r} is not allowed")
    host = parts.hostname or ""
    if host in BLOCKED_HOSTS:
        raise BlockedURL(f"host {host!r} is internal")
    return url


def deliver(url, event):
    check_url(url)
    body = json.dumps(event).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.status
