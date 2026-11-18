"""Customers register a URL per event type."""
from .send import check_url

_hooks = {}


def register(account_id, event_type, url):
    _hooks[(account_id, event_type)] = check_url(url)


def url_for(account_id, event_type):
    return _hooks.get((account_id, event_type))
