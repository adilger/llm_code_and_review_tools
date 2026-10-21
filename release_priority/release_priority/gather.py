"""Read a release's priority changes from Gerrit and give each its status.

A release's priority changes are the open changes carrying its Gerrit
hashtag (2.18: 218_review_priority), and its blockers those carrying its
blocker hashtag (218_review_blocker).  master-next comes from Gerrit's
gitiles (the Change-Ids on master..master-next), and a change is behind
when an earlier open change in its series has a failure of its own.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import requests

from . import status as rs

PROJECT = "fs/lustre-release"
QUERY_OPTIONS = ["DETAILED_LABELS", "MESSAGES", "DETAILED_ACCOUNTS", "CURRENT_REVISION",
                 "CURRENT_COMMIT"]
WORKERS = 8
TIMEOUT = 60


def hashtag_for(release: str) -> str:
    """The priority hashtag of a release: 2.18 -> 218_review_priority."""
    return release.replace(".", "") + "_review_priority"


def blocker_hashtag_for(release: str) -> str:
    """The blocker hashtag of a release: 2.18 -> 218_review_blocker."""
    return release.replace(".", "") + "_review_blocker"


def change_url(gerrit_url: str, n: int, project: str = PROJECT) -> str:
    return f"{gerrit_url.rstrip('/')}/c/{project}/+/{n}"


def master_next_ids(gerrit_url: str, get=None) -> set[str] | None:
    """Change-Ids on master..master-next, from gitiles; None when Gerrit
    cannot say."""
    get = get or _anon_get
    ids: set[str] = set()
    path = f"/plugins/gitiles/{PROJECT}/+log/master..master-next?format=JSON&n=500"
    try:
        for _ in range(20):
            page = get(gerrit_url, path)
            for c in page.get("log") or []:
                for line in (c.get("message") or "").splitlines():
                    if line.startswith("Change-Id: "):
                        ids.add(line.split(":", 1)[1].strip())
            nxt = page.get("next")
            if not nxt:
                return ids
            path = (f"/plugins/gitiles/{PROJECT}/+log/master..master-next"
                    f"?format=JSON&n=500&s={quote(nxt)}")
    except (requests.RequestException, ValueError):
        return None
    return ids


def _anon_get(gerrit_url: str, path: str) -> Any:
    r = requests.get(gerrit_url.rstrip("/") + path, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text
    if text.startswith(")]}'"):
        text = text[4:]
    return json.loads(text)


def _ancestors(client, n: int) -> list[int]:
    """The open changes n is built on, nearest first."""
    try:
        related = client.rest.get(f"/changes/{n}/revisions/current/related").get("changes") or []
    except Exception:  # a change whose series cannot be read is behind nothing
        return []
    nums = [int(c.get("_change_number") or 0) for c in related]
    if n not in nums:
        return []
    below = related[nums.index(n) + 1:]
    return [int(c["_change_number"]) for c in below if c.get("status") == "NEW"]


def details(client, numbers) -> dict[int, dict]:
    """ChangeInfo for numbers, with the options the status rules need."""
    numbers = sorted(set(numbers))
    out: dict[int, dict] = {}
    for i in range(0, len(numbers), 40):
        batch = numbers[i:i + 40]
        q = " OR ".join(f"change:{n}" for n in batch)
        for d in client.search_all(q, max_results=len(batch), options=QUERY_OPTIONS):
            out[int(d["_number"])] = d
    return out


def gather(client, hashtag: str, gerrit_url: str, series: bool = True,
           mn_get=None, blocker_hashtag: str | None = None) -> dict:
    """{changes: [record], master_next_known, generated_at}: every open
    change carrying hashtag or blocker_hashtag, each normalised with its
    status and group."""
    tags = [hashtag] + ([blocker_hashtag] if blocker_hashtag else [])
    query = "(" + " OR ".join(f"hashtag:{t}" for t in tags) + ") status:open"
    below: dict[int, list[int]] = {}
    extra: dict[int, dict] = {}
    # The full search is the slow call; master-next and the series are
    # read alongside it, from a bare search for the change numbers.
    with ThreadPoolExecutor(WORKERS + 2) as pool:
        full = pool.submit(client.search_all, query, max_results=2000, options=QUERY_OPTIONS)
        mn_ids = pool.submit(master_next_ids, gerrit_url, mn_get)
        if series:
            nums = [int(d["_number"]) for d in client.search_all(query, max_results=2000,
                                                                 options=[])]
            below = dict(zip(nums, pool.map(lambda n: _ancestors(client, n), nums), strict=True))
            extra = details(client, {a for ancestors in below.values() for a in ancestors}
                            - set(nums))
        tagged = full.result()
        mn = mn_ids.result()
    master_next = frozenset(mn or ())
    patches = {int(d["_number"]): rs.normalize(d, master_next) for d in tagged}

    behind: dict[int, int] = {}
    if series and patches:
        others = {n: rs.normalize(d, master_next) for n, d in extra.items()
                  if n not in patches and d.get("status") == "NEW"}
        blocker = {n: rs.is_hard_blocker(p) for n, p in {**others, **patches}.items()}
        for n in patches:
            ancestors = below.get(n) or []
            if blocker.get(n):
                continue
            # The first failing change from the base up holds back the rest.
            first = next((a for a in reversed(ancestors) if blocker.get(a)), None)
            if first:
                behind[n] = first

    now = datetime.now(UTC)
    records = []
    for n, p in patches.items():
        st = rs.status(p, behind.get(n))
        last = p.get("last_human") or {}
        quiet = None
        stamp = last.get("date") or p.get("updated")
        if stamp:
            try:
                quiet = (now - rs.parse_time(stamp)).days
            except ValueError:
                quiet = None
        records.append(dict(p, status=st, group=rs.group_of(st), behind=behind.get(n),
                            release_blocker=bool(blocker_hashtag) and blocker_hashtag in p["hashtags"],
                            quiet_days=quiet, url=change_url(gerrit_url, n, p["project"] or PROJECT)))
    order = list(rs.GROUP_KEYS)
    records.sort(key=lambda c: (order.index(c["group"]), not c["release_blocker"],
                                -(c["quiet_days"] or 0), c["n"]))
    return {"changes": records, "master_next_known": mn is not None,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"), "source": "gerrit"}


PAGE_DATA_URL = "https://mulberrytree.us/release_priority/data.json"
# Older than this, the page's data is not used: its builder has stopped.
PAGE_STALE_AFTER = 15 * 60


def _ascii(s: str | None) -> str:
    """The page writes a minus sign where the CLI writes a hyphen."""
    return (s or "").replace("\u2212", "-")


def _from_page_row(r: dict) -> dict:
    """A data.json change as the record gather() makes."""
    owner = {"name": r["owner"], "id": r.get("owner_id"), "username": ""}
    whose = [{"name": n, "id": i} for n, i in
             zip(r.get("whose") or [], r.get("whose_ids") or [], strict=False)]
    return {
        "n": r["n"], "url": r["url"], "subject": r["subject"], "branch": r.get("branch") or "",
        "project": PROJECT, "owner": owner,
        "status": {"tone": r.get("tone"), "words": _ascii(r["status"]), "why": _ascii(r.get("why")),
                   "whose": whose, "owner_move": bool(r.get("owner_move"))},
        "group": r["group"], "behind": r.get("behind"),
        "reviewers": [{"name": x["name"], "id": x.get("id"), "cr": x.get("vote") or 0,
                       "bot": False, "review_bot": False} for x in r.get("reviewers") or []],
        "need": r.get("need") or 2, "unresolved": r.get("unresolved") or 0,
        "build": (r.get("build") or "none").upper(),
        "tests": {"state": (r.get("tests") or "none").upper(), "failing": r.get("failing") or 0,
                  "retesting": bool(r.get("retesting"))},
        "master_next": bool(r.get("master_next")), "quiet_days": r.get("quiet_days"),
        "hashtags": r.get("hashtags") or [],
        "release_blocker": bool(r.get("release_blocker")),
    }


def from_page(hashtag: str, blocker_hashtag: str | None, url: str = PAGE_DATA_URL,
              get=None) -> dict | None:
    """What gather() returns, from the public page's data.json, which is
    rebuilt every minute; None when the page is down, stale or follows
    other hashtags."""
    try:
        if get:
            d = get(url)
        else:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            d = r.json()
        if d.get("hashtag") != hashtag or (blocker_hashtag and d.get("blocker_hashtag") != blocker_hashtag):
            return None
        built = rs.parse_time(d["generated_at"])
        if (datetime.now(UTC) - built).total_seconds() > PAGE_STALE_AFTER:
            return None
        changes = [_from_page_row(c) for c in d.get("changes") or []]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None
    return {"changes": changes, "master_next_known": True,
            "generated_at": d["generated_at"] + " UTC", "source": url}
