"""In-memory registry of logged-in editor sessions."""
from collections import Counter

from store.index import UserIndex


class Registry:
    def __init__(self):
        self._index = UserIndex()
        self._tabs = Counter()

    def login(self, user_id):
        self._tabs[user_id] += 1
        self._index.add(user_id)

    def logout(self, user_id):
        self._tabs[user_id] -= 1
        if self._tabs[user_id] <= 0:
            del self._tabs[user_id]
            self._index.discard(user_id)

    def active_user_ids(self):
        """Ids of users with at least one open tab, once each, oldest login first."""
        return self._index.users()

    def is_active(self, user_id):
        return user_id in self._index
