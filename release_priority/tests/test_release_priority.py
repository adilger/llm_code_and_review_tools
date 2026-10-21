import json

import pytest
from click.testing import CliRunner

from release_priority import cli, views
from release_priority import gather as rg
from release_priority import status as rs

NOW = "2026-10-01 00:00:00.000000000"
OWEN = {"_account_id": 1, "name": "Owen", "username": "owen"}
RITA = {"_account_id": 2, "name": "Rita", "username": "rita"}
SAM = {"_account_id": 3, "name": "Sam", "username": "sam"}
JENKINS = {"_account_id": 90, "name": "jenkins", "username": "jenkins"}
MALOO = {"_account_id": 91, "name": "Maloo", "username": "maloo"}


def change(n, owner=OWEN, reviewers=(RITA, SAM), votes=None, ok=True, **kw):
    """A ChangeInfo that built and passed, unless ok is False."""
    votes = votes or {}
    msgs = []
    labels = {"Code-Review": {"all": [dict(a, value=votes.get(a["_account_id"], 0))
                                      for a in reviewers]}}
    if ok:
        msgs = [{"author": JENKINS, "date": NOW, "_revision_number": 1,
                 "message": "Patch Set 1: Verified+1\n\nBuild Successful\n\n"
                            "https://build.whamcloud.com/job/lustre-reviews/1/ : SUCCESS"},
                {"author": MALOO, "date": NOW, "_revision_number": 1,
                 "message": "Patch Set 1: Verified+1\n\nMaloo Results: "
                            "https://testing.whamcloud.com/test_sessions/1"}]
        labels["Verified"] = {"all": [dict(MALOO, value=1), dict(JENKINS, value=1)]}
    d = {"_number": n, "subject": f"LU-{n} llite: change {n}", "branch": "master",
         "project": "fs/lustre-release", "change_id": f"I{n:040d}", "status": "NEW",
         "owner": owner, "current_revision": "r", "current_revision_number": 1,
         "revisions": {"r": {"_number": 1, "kind": "REWORK", "uploader": owner}},
         "messages": msgs, "labels": labels,
         "reviewers": {"REVIEWER": list(reviewers) + [JENKINS, MALOO]},
         "updated": NOW, "hashtags": ["218_review_priority"], "unresolved_comment_count": 0}
    d.update(kw)
    return d


def words(d, behind=None, mn=frozenset()):
    return rs.status(rs.normalize(d, mn), behind)["words"]


def test_rules():
    assert words(change(1)) == "Waiting on review"
    assert words(change(1, votes={2: 1, 3: 1})) == "Ready to land"
    assert words(change(1, votes={2: -1})) == "Reviewer -1"
    assert words(change(1, reviewers=(RITA,))) == "Needs reviewers"
    assert words(change(1, ok=False)) == "In CI"
    assert words(change(1, work_in_progress=True)) == "Work in progress"
    assert words(change(1), behind=7) == "Behind 7"
    assert words(change(1), mn={f"I{1:040d}"}) == "In master-next"


def test_comments_to_answer():
    d = change(1, unresolved_comment_count=2,
               messages=change(1)["messages"] + [{"author": RITA, "date": NOW, "message": "hm"}])
    assert words(d) == "Comments to answer"


def test_groups():
    assert rs.group_of({"tone": "warn", "words": "Needs reviewers"}) == "review"
    assert rs.group_of({"tone": "bad", "words": "Tests failed"}) == "owner"
    assert rs.group_of({"tone": "special", "words": "In master-next"}) == "master_next"
    assert rs.group_of({"tone": "running", "words": "Retest pending"}) == "ci"
    assert rs.group_of({"tone": "none", "words": "Behind 3"}) == "behind"


def test_hashtag_for():
    assert rg.hashtag_for("2.18") == "218_review_priority"
    assert rg.hashtag_for("2.17.1") == "2171_review_priority"


def test_master_next_ids_pages():
    pages = iter([{"log": [{"message": "LU-1 x: y\n\nChange-Id: Iaaa\n"}], "next": "abc"},
                  {"log": [{"message": "Change-Id: Ibbb"}]}])
    asked = []

    def get(url, path):
        asked.append(path)
        return next(pages)
    assert rg.master_next_ids("https://g", get) == {"Iaaa", "Ibbb"}
    assert asked[1].endswith("&s=abc")


def test_master_next_unknown():
    def get(url, path):
        raise ValueError("bad json")
    assert rg.master_next_ids("https://g", get) is None


class FakeRest:
    def __init__(self, related):
        self.related = related

    def get(self, path):
        n = int(path.split("/")[2])
        return {"changes": [{"_change_number": x, "status": "NEW"} for x in self.related.get(n, [n])]}


class FakeClient:
    """Gerrit: changes by number, related chains newest first."""

    def __init__(self, changes, related=None):
        self.changes = {c["_number"]: c for c in changes}
        self.rest = FakeRest(related or {})
        self.authenticated = True

    def search_all(self, q, max_results=500, options=None):
        if q.startswith("hashtag:"):
            tag = q.split()[0].split(":", 1)[1]
            return [c for c in self.changes.values() if tag in c.get("hashtags", [])]
        nums = {int(t.split(":")[1]) for t in q.split(" OR ")}
        return [c for n, c in self.changes.items() if n in nums]


def gathered(changes, related=None, mn=()):
    return rg.gather(FakeClient(changes, related), "218_review_priority", "https://g",
                     mn_get=lambda url, path: {"log": [{"message": f"Change-Id: {i}"} for i in mn]})


def test_gather_behind_an_untagged_failure():
    base = change(10, votes={2: -1}, hashtags=[])
    top = change(11)
    got = gathered([base, top], related={11: [11, 10]})
    (c,) = got["changes"]
    assert c["n"] == 11 and c["status"]["words"] == "Behind 10" and c["group"] == "behind"
    assert c["url"] == "https://g/c/fs/lustre-release/+/11"


def test_gather_master_next():
    got = gathered([change(12)], mn=[f"I{12:040d}"])
    assert got["changes"][0]["group"] == "master_next" and got["master_next_known"]


def me_of(changes, me, **kw):
    return views.me_view(gathered(changes, **kw), me, "2.18", "218_review_priority")


def test_me_sections():
    mine_bad = change(20, votes={2: -1})
    mine_review = change(21)
    mine_ready = change(22, votes={2: 1, 3: 1})
    rita_owes = change(23, owner=SAM, reviewers=(RITA, OWEN), votes={2: 0, 1: 1})
    needs = change(24, owner=SAM, reviewers=(RITA,))
    d = me_of([mine_bad, mine_review, mine_ready, rita_owes, needs],
              {"id": 1, "name": "Owen", "username": "owen"})
    assert [c["n"] for c in d["your_move"]] == [20]
    assert "Marc" not in d["your_move"][0]["action"] and "-1 from Rita" in d["your_move"][0]["action"]
    assert [c["n"] for c in d["your_changes_in_review"]] == [21]
    assert [c["n"] for c in d["your_other_changes"]] == [22]
    # Owen voted +1 on 23, so it is not owed; it still needs review.
    assert d["reviews_owed"] == []
    assert {c["n"] for c in d["needs_review"]} == {23, 24}
    assert d["web_page"]["url"] == views.PAGE_URL
    rita = me_of([rita_owes, needs], {"id": 2, "name": "Rita", "username": "rita"})
    assert [c["n"] for c in rita["reviews_owed"]] == [23]
    assert [c["n"] for c in rita["needs_review"]] == [24]
    assert rita["needs_review"][0]["you_are_reviewer"]


def test_me_nothing_to_do():
    d = me_of([change(30, votes={2: 1, 3: 1})], {"id": 9, "name": "Nobody"})
    assert d["suggestions"] == ["Nothing at the release priority waits on you, and nothing "
                                "needs review."]


def test_listing_filters():
    got = gathered([change(40), change(41, owner=SAM, reviewers=(RITA, OWEN), votes={2: 1, 1: 1})])
    d = views.listing(got, "2.18", "218_review_priority", groups={"ready"})
    assert [g["key"] for g in d["groups"]] == ["ready"]
    assert [c["n"] for c in d["groups"][0]["changes"]] == [41]
    d = views.listing(got, "2.18", "218_review_priority", owner="owen")
    assert d["counts"]["open"] == 1


@pytest.fixture
def run(monkeypatch):
    fake = FakeClient([change(50, votes={2: -1}), change(51, owner=SAM)])
    monkeypatch.setattr(cli, "client", lambda: fake)
    monkeypatch.setattr(rg, "master_next_ids", lambda url, get=None: set())
    monkeypatch.setattr(cli, "identity", lambda c, login: {"id": 1, "name": "Owen",
                                                            "username": "owen"})
    monkeypatch.setattr(cli, "maybe_check_for_updates", lambda: None)

    def go(*args):
        r = CliRunner().invoke(cli.main, list(args))
        return r.exit_code, json.loads(r.output)
    return go


def test_cli_me(run):
    rc, d = run("me")
    assert rc == 0 and [c["n"] for c in d["your_move"]] == [50]


def test_cli_list_envelope(run):
    rc, d = run("list", "--envelope", "-g", "owner")
    assert rc == 0 and d["ok"] and d["data"]["groups"][0]["changes"][0]["n"] == 50
    assert "release-priority me" in d["next_actions"]


def test_cli_show(run):
    rc, d = run("show", "https://review.whamcloud.com/c/fs/lustre-release/+/50")
    assert rc == 0 and d["status"] == "Reviewer -1" and d["commands"] == ["gc comments 50"]
    rc, d = run("show", "99")
    assert rc == 3 and d["code"] == "NOT_FOUND"


def test_cli_release_option(run):
    rc, d = run("list", "--release", "2.17")
    assert rc == 0 and d["hashtag"] == "217_review_priority" and d["counts"]["open"] == 0
