"""The presence bar: avatars of who is here."""


def avatars(registry, profiles):
    return [profiles[uid].avatar_url for uid in sorted(registry.active_user_ids())]
