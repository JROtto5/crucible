"""Deliver webhook events to customer-supplied URLs."""
import json
import urllib.request

TIMEOUT_S = 5


def deliver(url, event):
    body = json.dumps(event).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.status
