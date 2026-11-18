"""Membership index behind the session registry."""


class UserIndex:
    """add/discard/contains are O(1); a workspace with 8k open tabs spent most of a login in list.remove."""

    def __init__(self):
        self._members = set()

    def add(self, user_id):
        self._members.add(user_id)

    def discard(self, user_id):
        self._members.discard(user_id)

    def __contains__(self, user_id):
        return user_id in self._members

    def __len__(self):
        return len(self._members)

    def users(self):
        return list(self._members)
