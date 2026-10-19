"""Tests for how `gc maloo` and `gc info` read CI from a change. No network."""

from gerrit_cli.commands.ci import _info_for_change, _maloo_for_change

GROUP = "review-ldiskfs-ubuntu"


class FakeClient:
    def __init__(self, msgs, revisions=None, current="r13", labels=None):
        self.msgs = msgs
        self.revisions = revisions or {"r13": {"_number": 13, "kind": "REWORK"}}
        self.current = current
        self.labels = labels or {}

    def get_change(self, change_number, options=None):
        return {
            "subject": "test",
            "current_revision": self.current,
            "revisions": self.revisions,
            "labels": self.labels,
            "messages": self.msgs,
        }

    def get_reviewers(self, change_number):
        return []


def _maloo_fail(date, ps=13):
    return {
        "author": {"name": "Maloo"},
        "_revision_number": ps,
        "date": date,
        "message": (
            f"Patch Set {ps}:\n\nFailed enforced test {GROUP} on RHEL 8.10 "
            "uploaded by Trevis Autotest: "
            "https://testing.whamcloud.com/test_sessions/abc "
            "ran 6 tests. 1 tests failed: sanity-lnet."
        ),
    }


def _retest(date, ps=13):
    return {
        "author": {"name": "Autotest"},
        "_revision_number": ps,
        "date": date,
        "message": (
            f"Patch Set {ps}:\n\nTrevis Autotest retesting enforced {GROUP} "
            "session"
        ),
    }


def _maloo_vote(value):
    return {"Verified": {"all": [{"name": "Maloo", "value": value}]}}


def _group(msgs, **kw):
    data = _maloo_for_change(FakeClient(msgs, **kw), 1)
    return data["enforced"]["tests"][0]


def test_retest_after_failure_is_pending():
    t = _group([_maloo_fail("2026-10-09 09:09:30.000000000"),
                _retest("2026-10-09 19:08:08.000000000")])
    assert t.get("retest_pending") is True


def test_retest_that_failed_again_is_not_pending():
    t = _group([_maloo_fail("2026-10-09 09:09:30.000000000"),
                _retest("2026-10-09 19:08:08.000000000"),
                _maloo_fail("2026-10-10 02:51:59.000000000")])
    assert "retest_pending" not in t
    assert t["verdict"] == "FAIL"
    assert t["failed"] == 1
    assert t["failures"][0]["attempts"] == 2


def test_maloo_plus_one_clears_a_silently_retested_failure():
    # 69572: the retest passed with no message of its own; Maloo only
    # changed its vote to +1.
    msgs = [_maloo_fail("2026-10-11 11:14:28.000000000"),
            _retest("2026-10-11 11:33:22.000000000")]
    client = FakeClient(msgs, labels=_maloo_vote(1))
    data = _maloo_for_change(client, 1)
    assert data["enforced"]["total_fail"] == 0
    assert data["enforced"]["tests"][0]["verdict"] == "PASSED_LATER"
    assert "retest_pending" not in data["enforced"]["tests"][0]

    ci = _info_for_change(client, 1)["ci"]
    assert ci["status"] == "all passing"
    assert ci["enforced_fail"] == 0
    assert ci["retests_pending"] == 0


def test_commit_message_only_patchset_reports_earlier_results():
    # 69585: patchset 2 only changed the commit message, so nothing ran
    # on it and Gerrit copied patchset 1's votes.
    jenkins = {
        "author": {"name": "jenkins"},
        "_revision_number": 1,
        "date": "2026-10-11 17:14:00.000000000",
        "message": ("Patch Set 1: Verified+1\n\nBuild Successful\n\n"
                    "https://build.whamcloud.com/job/lustre-reviews/133396/ : SUCCESS"),
    }
    checkpatch = {
        "author": {"name": "wc-checkpatch"},
        "_revision_number": 2,
        "date": "2026-10-12 01:18:49.000000000",
        "message": "Patch Set 2:\n\nLooks good to me.",
    }
    revisions = {
        "r1": {"_number": 1, "kind": "REWORK"},
        "r2": {"_number": 2, "kind": "NO_CODE_CHANGE"},
    }
    labels = {"Verified": {"all": [{"name": "jenkins", "value": 1},
                                   {"name": "Maloo", "value": 1}]}}
    client = FakeClient([jenkins, checkpatch], revisions=revisions,
                        current="r2", labels=labels)

    info = _info_for_change(client, 1)
    assert info["ci"]["status"] == "all passing"
    assert info["ci"]["results_patchset"] == 1
    assert info["jenkins_build"]["build_number"] == "133396"

    data = _maloo_for_change(client, 1)
    assert data["patchset"] == 1
    assert data["current_patchset"] == 2
    assert data["state"] == "PASS"


class _OpenChange(FakeClient):
    """An open change whose mergeability Gerrit reports on request."""

    def __init__(self, answer):
        super().__init__([])
        self.answer = answer
        self.asked = []

    def get_change(self, change_number, options=None):
        return {**super().get_change(change_number, options), "status": "NEW"}

    def get_mergeable(self, change_number, revision="current"):
        self.asked.append((change_number, revision))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_info_reports_a_merge_conflict_of_the_current_patchset():
    client = _OpenChange({"submit_type": "CHERRY_PICK", "mergeable": False})
    info = _info_for_change(client, 69696)
    assert info["mergeable"] is False
    assert client.asked == [(69696, "r13")], "asked for the current revision"
    assert _info_for_change(_OpenChange({"mergeable": True}), 1)["mergeable"] is True


def test_info_mergeable_is_null_when_gerrit_cannot_say_or_the_change_is_closed():
    assert _info_for_change(_OpenChange(RuntimeError("503")), 1)["mergeable"] is None
    assert _info_for_change(_OpenChange({"submit_type": "CHERRY_PICK"}), 1)["mergeable"] is None
    merged = _OpenChange({"mergeable": False})
    merged.get_change = lambda number, options=None: {**FakeClient.get_change(merged, number, options), "status": "MERGED"}
    assert _info_for_change(merged, 1)["mergeable"] is None
    assert merged.asked == [], "a closed change is never asked"


STC = "review-dne-subtest-change"


def _enum(groups, ps=13):
    lines = "\n\n".join(f"- {g} on el9.7-x86_64/el9.7-x86_64/ldiskfs/ldiskfs" for g in groups)
    return {"author": {"name": "Maloo"}, "_revision_number": ps, "date": "2026-10-09 08:00:00.000000000",
            "message": f"Patch Set {ps}:\n\n#### The following sessions will be run for Build 1 "
                       f"(patch #{ps}):\n\n#### Enforced:\n\n{lines}\n"}


def _verdict(date, group, status="Failed", suite="sanity-flr", ps=13):
    return {"author": {"name": "Maloo"}, "_revision_number": ps, "date": date,
            "message": f"Patch Set {ps}:\n\n{status} enforced test {group} on RHEL 9.7 / x86_64 "
                       f"uploaded by Onyx Autotest: https://testing.whamcloud.com/test_sessions/{date[-12:-9]} "
                       f"ran 3 tests.  1 tests failed: {suite}."}


def _retest_of(date, group, client="el9.7-x86_64", ps=13):
    return {"author": {"name": "Autotest"}, "_revision_number": ps, "date": date,
            "message": f"Patch Set {ps}:\n\nOnyx Autotest retesting enforced {group} session on "
                       f"el9.4-x86_64/ldiskfs servers and {client}/ldiskfs clients for build 1 patch {ps}. "
                       "Requested by Patrickbot because of LU-1."}


def test_sibling_slots_are_separate_failures():
    # 68361 PS11: three subtest-change sessions of one build failed.
    t = _group([_enum([STC] * 3), _verdict("2026-10-09 09:01:00.000000000", STC, suite="sanity-ec"),
                _verdict("2026-10-09 09:02:00.000000000", STC),
                _verdict("2026-10-09 09:03:00.000000000", STC)])
    assert t["failed"] == 3 and [f["attempts"] for f in t["failures"]] == [1, 1, 1]


def test_a_sibling_slots_pass_is_not_a_retest():
    msgs = [_enum([STC] * 2), _verdict("2026-10-09 09:01:00.000000000", STC),
            _verdict("2026-10-09 09:02:00.000000000", STC, status="Passed")]
    t = _group(msgs)
    assert t["verdict"] == "FAIL" and t["failed"] == 1
    # once a retest is asked for, the next verdict answers it
    t = _group(msgs + [_retest_of("2026-10-09 10:00:00.000000000", STC)])
    assert t["retest_pending"] is True
    data = _maloo_for_change(FakeClient(msgs + [
        _retest_of("2026-10-09 10:00:00.000000000", STC),
        _verdict("2026-10-09 11:00:00.000000000", STC, status="Passed")]), 1)
    assert data["enforced"]["total_fail"] == 0


def test_a_retest_of_one_slot_fails_again():
    t = _group([_enum([STC] * 2), _verdict("2026-10-09 09:01:00.000000000", STC),
                _verdict("2026-10-09 09:02:00.000000000", STC),
                _retest_of("2026-10-09 10:00:00.000000000", STC),
                _verdict("2026-10-09 11:00:00.000000000", STC)])
    assert t["failed"] == 2 and sorted(f["attempts"] for f in t["failures"]) == [1, 2]
    assert "retest_pending" not in t


def test_a_custom_retest_is_pending():
    msgs = [_enum(["custom"] * 2), _verdict("2026-10-09 09:01:00.000000000", "custom-1001")]
    assert _group(msgs + [_retest_of("2026-10-09 10:00:00.000000000", "custom")])["retest_pending"]
    # not a retest of another platform, nor of a group whose name holds this one
    assert "retest_pending" not in _group(
        msgs + [_retest_of("2026-10-09 10:00:00.000000000", "custom", client="el10.1-x86_64")])
    msgs = [_verdict("2026-10-09 09:01:00.000000000", "review-ldiskfs-dne")]
    assert "retest_pending" not in _group(
        msgs + [_retest_of("2026-10-09 10:00:00.000000000", "review-ldiskfs-dne-arm")])
