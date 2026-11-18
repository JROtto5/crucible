"""Who holds the edit lock in a shared document."""


def pick_leader(registry):
    """The longest-connected user leads; everyone else follows their cursor."""
    ids = registry.active_user_ids()
    return ids[0] if ids else None


def handover(registry, leaving):
    """Called when the leader leaves: the next-oldest takes over."""
    rest = [u for u in registry.active_user_ids() if u != leaving]
    return rest[0] if rest else None
