"""What each command shows: the changes as plain records, and for one
engineer what is theirs to do and where they can help."""

from __future__ import annotations

from . import status as rs

JIRA = "https://jira.whamcloud.com/browse"
PAGE_URL = "https://mulberrytree.us/release_priority/"
PAGE_RELEASE = "2.18"

# What the owner does about each status, and the commands that help.
OWNER_ACTIONS = {
    "Work in progress": ("Finish it and mark it ready for review.", []),
    "Build failed": ("Fix the build: the Jenkins result is on the change.", ["gc info {n}"]),
    "Needs rebase": ("Rebase it onto {branch}: it no longer applies.", ["gc rebase {n}"]),
    "Tests failed": ("Look at the failing tests: fix what the patch broke, or ask for a retest "
                     "of failures it did not cause.", ["gc maloo {n}", "pw-cli retest {n}"]),
    "Janitor failures": ("Look at the Janitor's failures unique to this patch.", ["gc info {n}"]),
    "Verified -1": ("Answer the {why}.", ["gc comments {n}"]),
    "Reviewer -1": ("Answer the {why}: rework the patch or reply to the comments.",
                    ["gc comments {n}"]),
    "Checkpatch -1": ("Fix the checkpatch style problems.", ["gc comments {n}"]),
    "Robot -1": ("Look at the review robot's comments ({why}).", ["gc comments {n}"]),
    "Needs reviewers": ("Add reviewers: {why}.", ['gc add-reviewer {n} "NAME"',
                                                   "pw-cli reviewers {n}"]),
    "Comments to answer": ("Answer the comments: {why}.", ["gc comments {n}"]),
    "Waiting on review": ("Nothing to fix: if it has sat, ping the reviewers who have not "
                          "voted ({whose}).", []),
}


def _names(people) -> list[str]:
    return [p.get("name") or "" for p in people or []]


def record(c: dict) -> dict:
    """One change as the commands show it."""
    st = c["status"]
    people = rs.humans(c)
    ticket = rs.ticket_of(c["subject"])
    out = {
        "n": c["n"], "url": c["url"], "subject": c["subject"],
        "ticket": ticket, "ticket_url": f"{JIRA}/{ticket}" if ticket else None,
        "branch": c["branch"], "owner": c["owner"]["name"],
        "status": st["words"], "why": st["why"], "group": c["group"],
        "whose_move": "owner" if st["owner_move"] else ", ".join(_names(st["whose"])) or "nobody",
        "reviewers": [{"name": r["name"], "vote": r["cr"] or 0} for r in people],
        "plus": sum(1 for r in people if (r["cr"] or 0) > 0),
        "need": c["need"], "unresolved": c["unresolved"],
        "ci": {"build": c["build"].lower(), "tests": c["tests"]["state"].lower(),
               "failing": c["tests"]["failing"], "retest_asked": c["tests"]["retesting"]},
        "quiet_days": c["quiet_days"],
    }
    if c.get("behind"):
        out["behind"] = c["behind"]
    if c["master_next"]:
        out["master_next"] = True
    return out


def owner_action(c: dict) -> dict:
    st = c["status"]
    text, cmds = OWNER_ACTIONS.get(st["words"], ("", []))
    if st["words"].startswith("Behind "):
        text, cmds = f"Wait for {c['behind']} (earlier in the series) to be fixed.", []
    fmt = {"n": c["n"], "branch": c["branch"] or "master", "why": st["why"],
           "whose": ", ".join(_names(st["whose"]))}
    return {"action": text.format(**fmt), "commands": [x.format(**fmt) for x in cmds]}


def counts(changes: list[dict]) -> dict:
    out = {k: sum(1 for c in changes if c["group"] == k) for k in rs.GROUP_KEYS}
    out["open"] = len(changes)
    return out


def web_page(release: str) -> dict:
    if release != PAGE_RELEASE:
        return {"url": None, "note": f"The public page shows {PAGE_RELEASE} only."}
    return {"url": PAGE_URL, "note": "The same changes, grouped, on a public web page "
                                     "rebuilt every minute."}


def listing(got: dict, release: str, hashtag: str, groups=None, owner=None) -> dict:
    """Everything at the release priority, grouped as the web page groups it."""
    changes = got["changes"]
    if owner:
        o = owner.lower()
        changes = [c for c in changes if o in c["owner"]["name"].lower()
                   or o == (c["owner"].get("username") or "").lower()]
    shown = [g for g in rs.GROUPS if not groups or g[0] in groups]
    return {
        "release": release, "hashtag": hashtag, "generated_at": got["generated_at"],
        "web_page": web_page(release),
        "counts": counts(changes),
        "master_next_known": got["master_next_known"],
        "groups": [{"key": k, "title": t, "about": a,
                    "changes": [record(c) for c in changes if c["group"] == k]}
                   for k, t, a in shown],
    }


def _is(person: dict, me: dict) -> bool:
    return person.get("id") is not None and person.get("id") == me.get("id")


def me_view(got: dict, me: dict, release: str, hashtag: str, master_next: bool = False) -> dict:
    """What is the engineer's to do, and where they can help."""
    changes = got["changes"]
    mine = [c for c in changes if _is(c["owner"], me)]
    your_move, in_review, other = [], [], []
    for c in mine:
        st = c["status"]
        if st["words"] == "Waiting on review":
            in_review.append(dict(record(c), **owner_action(c)))
        elif st["owner_move"] and c["group"] in ("owner", "review"):
            your_move.append(dict(record(c), **owner_action(c)))
        else:
            other.append(record(c))

    owed, others_review = [], []
    for c in changes:
        if c["group"] != "review" or _is(c["owner"], me):
            continue
        reviewer = next((r for r in rs.humans(c) if _is(r, me)), None)
        if reviewer and c["status"]["words"] == "Waiting on review" and not reviewer["cr"]:
            owed.append(dict(record(c), action="Review it: you are a reviewer and have not "
                             "voted on this patchset.", commands=[f"gc review {c['n']}"]))
        else:
            r = record(c)
            others_review.append(dict(r, you_are_reviewer=bool(reviewer),
                                      reviewer_count=len(r["reviewers"]),
                                      action="Review it.", commands=[f"gc review {c['n']}"]))
    others_review.sort(key=lambda r: (r["reviewer_count"] >= r["need"], r["plus"],
                                      -(r["quiet_days"] or 0)))

    out = {
        "you": {k: me.get(k) for k in ("name", "username", "id")},
        "release": release, "hashtag": hashtag, "generated_at": got["generated_at"],
        "web_page": web_page(release),
        "counts": dict(counts(changes), your_move=len(your_move), your_changes_in_review=len(in_review),
                       reviews_owed=len(owed), needs_review=len(others_review),
                       yours=len(mine)),
        "your_move": your_move,
        "your_changes_in_review": in_review,
        "reviews_owed": owed,
        "needs_review": others_review,
        "your_other_changes": other,
        "suggestions": suggestions(your_move, in_review, owed, others_review),
    }
    if master_next:
        out["master_next"] = [record(c) for c in changes if c["group"] == "master_next"]
    return out


def suggestions(your_move, in_review, owed, others_review) -> list[str]:
    out = []
    if your_move:
        out.append(f"{len(your_move)} of your priority changes need you: start with "
                   f"{your_move[0]['n']} ({your_move[0]['status']}).")
    if owed:
        out.append(f"You are a reviewer on {len(owed)} change(s) waiting on your vote: "
                   + ", ".join(str(c["n"]) for c in owed) + ".")
    if in_review:
        out.append(f"{len(in_review)} of your changes wait on reviewers; ping them if they "
                   "have sat.")
    thin = [c for c in others_review if c["reviewer_count"] < c["need"] or c["plus"] == 0]
    if others_review:
        pick = (thin or others_review)[:3]
        out.append(f"{len(others_review)} other priority change(s) need review; any +1 from "
                   "someone other than the owner helps. Good places to start: "
                   + ", ".join(str(c["n"]) for c in pick) + ".")
    if not out:
        out.append("Nothing at the release priority waits on you, and nothing needs review.")
    return out


def master_next_view(got: dict, release: str, hashtag: str) -> dict:
    return {
        "release": release, "hashtag": hashtag, "generated_at": got["generated_at"],
        "master_next_known": got["master_next_known"],
        "master_next": [record(c) for c in got["changes"] if c["group"] == "master_next"],
        "ready_to_land": [record(c) for c in got["changes"] if c["group"] == "ready"],
    }
