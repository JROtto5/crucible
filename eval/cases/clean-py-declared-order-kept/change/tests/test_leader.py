from sessions.leader import pick_leader
from sessions.registry import Registry


def test_first_user_leads():
    r = Registry()
    r.login(1)
    r.login(2)
    r.login(3)
    assert pick_leader(r) == 1


def test_leader_moves_on_logout():
    r = Registry()
    a = r.login(1)
    r.login(2)
    r.logout(a)
    assert pick_leader(r) == 2


def test_two_tabs_count_once():
    r = Registry()
    r.login(4)
    r.login(4)
    r.login(5)
    assert r.active_count() == 2
