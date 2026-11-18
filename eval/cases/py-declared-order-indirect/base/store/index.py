"""Membership index behind the session registry."""


class UserIndex:
    def __init__(self):
        self._members = []

    def add(self, user_id):
        if user_id not in self._members:
            self._members.append(user_id)

    def discard(self, user_id):
        if user_id in self._members:
            self._members.remove(user_id)

    def users(self):
        return list(self._members)
