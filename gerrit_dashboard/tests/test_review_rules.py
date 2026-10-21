"""The Code-Review gate: votes add up, a -1 is no veto; only a -2 or the
owner's own -1 (not ready yet) blocks."""

import pytest
from conftest import ADILGER, ME, mk_change, vote

from gerrit_dashboard.review_rules import review_state

A = {"_account_id": 501, "name": "A"}
B = {"_account_id": 502, "name": "B"}
C = {"_account_id": 503, "name": "C"}
TIM = {"_account_id": 931, "name": "Timothy Day"}
BACKPORT = "subject\n\nLustre-change: https://review.example.com/c/x/+/1234\nChange-Id: I1\n"


@pytest.mark.parametrize("votes,backport,total,passes", [
    ([(A, 1), (B, 1), (C, 1), (TIM, -1)], False, 2, True),   # three +1s and a -1 make +2
    ([(A, 1), (TIM, -1)], False, 0, False),
    ([(A, 1), (B, 1), (TIM, -1)], True, 1, True),             # a backport needs +1
    ([(A, 1), (TIM, -1)], True, 0, False),
    ([(ADILGER, 2)], False, 2, True),                         # a +2 counts twice
    ([(A, 1), (ME, 1)], False, 1, False),                     # the owner's +1 does not count
    ([(TIM, -1)], False, -1, False),
])
def test_votes_add_up(votes, backport, total, passes):
    c = mk_change(code_review=[vote(a, v) for a, v in votes],
                  commit_message=BACKPORT if backport else None)
    rs = review_state(c)
    assert (rs["total"], rs["pass"], rs["blocked"]) == (total, passes, False)
    assert rs["has_any_negative"] is any(v < 0 for _, v in votes)


def test_a_minus_two_blocks():
    rs = review_state(mk_change(code_review=[vote(A, 1), vote(B, 1), vote(C, 1), vote(TIM, -2)]))
    assert rs["blocked"] and not rs["pass"] and not rs["owner_hold"]


def test_the_owners_minus_one_holds_it():
    rs = review_state(mk_change(code_review=[vote(A, 1), vote(B, 1), vote(C, 1), vote(ME, -1)]))
    assert rs["owner_hold"] and rs["blocked"] and not rs["pass"]
    assert rs["total"] == 3 and rs["has_any_negative"]
