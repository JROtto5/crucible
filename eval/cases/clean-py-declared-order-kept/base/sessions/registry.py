"""In-memory registry of logged-in editor sessions."""
import itertools
from dataclasses import dataclass, field

_seq = itertools.count()


@dataclass
class Session:
    user_id: int
    active: bool = True
    seq: int = field(default_factory=lambda: next(_seq))


class Registry:
    def __init__(self):
        self._sessions = []

    def login(self, user_id):
        s = Session(user_id)
        self._sessions.append(s)
        return s

    def logout(self, session):
        session.active = False

    def active_user_ids(self):
        """Ids of users with an active session, once each, in the order they first logged in."""
        ids = []
        for s in self._sessions:
            if s.active and s.user_id not in ids:
                ids.append(s.user_id)
        return ids
