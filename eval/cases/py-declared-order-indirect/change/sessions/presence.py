"""The presence bar: avatars of who is here, alphabetical."""


def avatars(registry, profiles):
    people = [profiles[uid] for uid in registry.active_user_ids()]
    return [p.avatar_url for p in sorted(people, key=lambda p: p.name.lower())]
