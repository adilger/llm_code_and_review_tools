"""Read a release's priority changes from Gerrit and give each its status.

A release's priority changes are the open changes carrying its Gerrit
hashtag (2.18: 218_review_priority).  master-next comes from Gerrit's
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
           mn_get=None) -> dict:
    """{changes: [record], master_next_known, generated_at}: every open
    change carrying hashtag, each normalised with its status and group."""
    tagged = client.search_all(f"hashtag:{hashtag} status:open", max_results=2000,
                               options=QUERY_OPTIONS)
    mn = master_next_ids(gerrit_url, mn_get)
    master_next = frozenset(mn or ())
    patches = {int(d["_number"]): rs.normalize(d, master_next) for d in tagged}

    behind: dict[int, int] = {}
    if series and patches:
        with ThreadPoolExecutor(WORKERS) as pool:
            below = dict(zip(patches, pool.map(lambda n: _ancestors(client, n), list(patches)), strict=True))
        extra = {a for ancestors in below.values() for a in ancestors} - set(patches)
        others = {n: rs.normalize(d, master_next) for n, d in details(client, extra).items()
                  if d.get("status") == "NEW"}
        blocker = {n: rs.is_hard_blocker(p) for n, p in {**others, **patches}.items()}
        for n, ancestors in below.items():
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
                            quiet_days=quiet, url=change_url(gerrit_url, n, p["project"] or PROJECT)))
    order = list(rs.GROUP_KEYS)
    records.sort(key=lambda c: (order.index(c["group"]), -(c["quiet_days"] or 0), c["n"]))
    return {"changes": records, "master_next_known": mn is not None,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S UTC")}
