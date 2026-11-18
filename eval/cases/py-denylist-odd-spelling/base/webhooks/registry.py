"""Customers register a URL per event type."""
_hooks = {}


def register(account_id, event_type, url):
    _hooks[(account_id, event_type)] = url


def url_for(account_id, event_type):
    return _hooks.get((account_id, event_type))
