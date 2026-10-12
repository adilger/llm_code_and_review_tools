"""Tests for _maloo_for_change retest detection. No network."""

from gerrit_cli.commands.ci import _maloo_for_change

GROUP = "review-ldiskfs-ubuntu"


class FakeClient:
    def __init__(self, msgs):
        self.msgs = msgs

    def get_change_detail(self, change_number):
        return {"subject": "test", "revisions": {}}

    def get_messages(self, change_number):
        return self.msgs


def _maloo_fail(date):
    return {
        "author": {"name": "Maloo"},
        "_revision_number": 13,
        "date": date,
        "message": (
            f"Patch Set 13:\n\nFailed enforced test {GROUP} on RHEL 8.10 "
            "uploaded by Trevis Autotest: "
            "https://testing.whamcloud.com/test_sessions/abc "
            "ran 6 tests. 1 tests failed: sanity-lnet."
        ),
    }


def _retest(date):
    return {
        "author": {"name": "Autotest"},
        "_revision_number": 13,
        "date": date,
        "message": (
            f"Patch Set 13:\n\nTrevis Autotest retesting enforced {GROUP} "
            "session"
        ),
    }


def _group(msgs):
    data = _maloo_for_change(FakeClient(msgs), 1)
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
    assert t["failed"] == 2
