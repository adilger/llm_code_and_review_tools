"""Code-Review gate rules for the Lustre project.

Self-contained on purpose: the dashboard ships without the internal
patch-status tooling it originally borrowed these from, and the rules
themselves are just the project's public review policy.

Both thresholds are configurable (Config.review_threshold /
backport_review_threshold) for anyone whose project counts differently.
"""

from __future__ import annotations

import re

REVIEW_LABEL = "Code-Review"

# A backport declares its master ancestor in the commit message.
# "Lustre-commit: TBD" still counts — the patch claims to mirror a master
# change that has not landed yet.
_CHANGE_TRAILER_RE = re.compile(r"^Lustre-change:\s*(\S+)\s*$", re.MULTILINE)
_COMMIT_TRAILER_RE = re.compile(r"^Lustre-commit:\s*(\S+)\s*$", re.MULTILINE)
_TRAILING_NUM_RE = re.compile(r"/(\d+)/?$")


def commit_message(change: dict) -> str:
    cur = change.get("current_revision")
    rev = (change.get("revisions") or {}).get(cur) if cur else None
    if not rev:
        return ""
    return (rev.get("commit") or {}).get("message") or ""


def parse_backport_refs(change: dict) -> dict:
    """Lustre-change / Lustre-commit trailers of the current revision."""
    msg = commit_message(change)
    if not msg:
        return {"lustre_change": None, "lustre_change_number": None,
                "lustre_commit": None}
    m_change = _CHANGE_TRAILER_RE.search(msg)
    m_commit = _COMMIT_TRAILER_RE.search(msg)
    lustre_change = m_change.group(1) if m_change else None
    number = None
    if lustre_change:
        n = _TRAILING_NUM_RE.search(lustre_change)
        if n:
            try:
                number = int(n.group(1))
            except ValueError:
                number = None
    return {
        "lustre_change": lustre_change,
        "lustre_change_number": number,
        "lustre_commit": m_commit.group(1) if m_commit else None,
    }


def is_backport(change: dict) -> bool:
    """True if the commit message declares an upstream ancestor."""
    refs = change.get("_backport_refs")
    if refs is None:
        refs = parse_backport_refs(change)
    return bool(refs.get("lustre_change"))


def owner_self_review_score(change: dict) -> int:
    """The owner's own Code-Review vote (-2..+2), 0 if none.

    With several entries for the owner (patchset-specific votes) the
    last one wins.
    """
    owner_id = (change.get("owner") or {}).get("_account_id")
    body = (change.get("labels") or {}).get(REVIEW_LABEL) or {}
    score = 0
    for e in body.get("all") or []:
        if e.get("_account_id") != owner_id:
            continue
        v = e.get("value")
        if isinstance(v, int) and v != 0:
            score = v
    return score


def review_state(change: dict, threshold: int = 2,
                 backport_threshold: int = 1) -> dict:
    """Code-Review gate state.

    The votes of everyone but the owner add up, and the gate is met at a
    total of two for a native patch, one for a backport by default: a -1
    is no veto, three +1s and a -1 make +2.  Only a -2 blocks, or the
    owner's own negative vote: the owner says the patch is not ready,
    and the reviews do not count until it is lifted.  The owner's
    positive votes do not count at all.
    """
    owner_id = (change.get("owner") or {}).get("_account_id")
    body = (change.get("labels") or {}).get(REVIEW_LABEL) or {}
    plus_one: set = set()
    plus_two: set = set()
    has_neg = False
    minus_two = False
    total = 0
    for e in body.get("all") or []:
        val = e.get("value")
        acc = e.get("_account_id")
        if not isinstance(val, int) or acc is None:
            continue
        if val <= -2:
            minus_two = True
        if acc == owner_id:
            continue
        total += val
        if val == 1:
            plus_one.add(acc)
        elif val == 2:
            plus_two.add(acc)
        elif val < 0:
            has_neg = True

    owner_hold = owner_self_review_score(change) < 0
    blocked = minus_two or owner_hold
    needed = backport_threshold if is_backport(change) else threshold
    return {
        "plus_one_count": len(plus_one),
        "plus_two_count": len(plus_two),
        "has_any_negative": has_neg or owner_hold,
        "total": total,
        "blocked": blocked,
        "owner_hold": owner_hold,
        "pass": total >= needed and not blocked,
        "threshold": needed,
    }
