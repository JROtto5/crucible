from sessions.leader import handover, pick_leader
from sessions.registry import Registry


def test_first_user_leads():
    r = Registry()
    for u in (1, 2, 3):
        r.login(u)
    assert pick_leader(r) == 1


def test_handover_goes_to_the_next_user():
    r = Registry()
    for u in (1, 2, 3):
        r.login(u)
    assert handover(r, 1) == 2
