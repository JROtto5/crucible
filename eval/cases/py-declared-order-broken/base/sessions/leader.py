"""Who holds the edit lock in a shared document."""


def pick_leader(registry):
    """The longest-connected user leads; everyone else follows their cursor."""
    ids = registry.active_user_ids()
    return ids[0] if ids else None


def followers(registry):
    return registry.active_user_ids()[1:]
