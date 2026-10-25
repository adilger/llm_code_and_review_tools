"""Tests for the GERRIT_CLI_MODE draft gate."""

from unittest.mock import MagicMock

import pytest

from gerrit_cli.mode import (
    MODE_DRAFTS,
    MODE_ENV_VAR,
    MODE_FULL,
    DraftModeError,
    DraftModeRest,
    get_mode,
    is_drafts_mode,
    result_fields,
    wrap_rest,
)

pytestmark = pytest.mark.unit

REVIEW_ENDPOINT = "/changes/62796/revisions/current/review"
DRAFTS_ENDPOINT = "/changes/62796/revisions/current/drafts"


@pytest.fixture
def rest():
    """A mock pygerrit2 REST API."""
    api = MagicMock()
    api.post.return_value = {"labels": {}}
    api.put.return_value = {"id": "draft1"}
    return api


class TestGetMode:
    def test_full_when_set_to_full(self, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, "full")
        assert get_mode() == MODE_FULL
        assert not is_drafts_mode()

    def test_case_and_whitespace_insensitive(self, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, " FULL ")
        assert get_mode() == MODE_FULL

    @pytest.mark.parametrize("value", [None, "", "  "])
    def test_full_when_unset_or_empty(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv(MODE_ENV_VAR, raising=False)
        else:
            monkeypatch.setenv(MODE_ENV_VAR, value)
        assert get_mode() == MODE_FULL
        assert not is_drafts_mode()

    @pytest.mark.parametrize("value", ["drafts", "draft", "yes", "FULL2", "0"])
    def test_anything_else_is_drafts(self, monkeypatch, value):
        monkeypatch.setenv(MODE_ENV_VAR, value)
        assert get_mode() == MODE_DRAFTS

    def test_result_fields(self, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, "drafts")
        assert result_fields() == {
            "gerrit_cli_mode": MODE_DRAFTS,
            "published": False,
        }
        monkeypatch.setenv(MODE_ENV_VAR, "full")
        assert result_fields() == {
            "gerrit_cli_mode": MODE_FULL,
            "published": True,
        }


class TestWrapRest:
    def test_full_mode_returns_original(self, rest, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, "full")
        assert wrap_rest(rest) is rest

    def test_drafts_mode_wraps(self, rest, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, MODE_DRAFTS)
        assert isinstance(wrap_rest(rest), DraftModeRest)

    def test_explicit_mode_beats_environment(self, rest, monkeypatch):
        monkeypatch.setenv(MODE_ENV_VAR, "full")
        assert isinstance(wrap_rest(rest, mode=MODE_DRAFTS), DraftModeRest)


class TestDraftModeRest:
    def test_non_review_post_passes_through(self, rest):
        gate = DraftModeRest(rest)
        gate.post("/changes/62796/reviewers", json={"reviewer": "x"})
        rest.post.assert_called_once_with(
            "/changes/62796/reviewers", json={"reviewer": "x"}
        )
        rest.put.assert_not_called()

    def test_attribute_delegation(self, rest):
        rest.kwargs = {"timeout": 60}
        gate = DraftModeRest(rest)
        assert gate.kwargs["timeout"] == 60
        gate.get("/changes/62796/detail")
        rest.get.assert_called_once_with("/changes/62796/detail")

    def test_inline_comments_become_drafts(self, rest):
        gate = DraftModeRest(rest)
        result = gate.post(REVIEW_ENDPOINT, json={
            "comments": {
                "lnet/lnet/peer.c": [
                    {"line": 42, "message": "check the return", "unresolved": True},
                    {"line": 50, "message": "second", "unresolved": False},
                ],
            },
        })

        rest.post.assert_not_called()
        assert rest.put.call_count == 2
        first = rest.put.call_args_list[0]
        assert first[0][0] == DRAFTS_ENDPOINT
        assert first[1]["json"] == {
            "path": "lnet/lnet/peer.c",
            "message": "check the return",
            "line": 42,
            "unresolved": True,
        }
        assert result == {
            "gerrit_cli_mode": MODE_DRAFTS,
            "drafts_created": 2,
            "published": False,
        }

    def test_cover_message_becomes_patchset_level_draft(self, rest):
        gate = DraftModeRest(rest)
        gate.post(REVIEW_ENDPOINT, json={"message": "Looks good overall"})

        rest.put.assert_called_once()
        assert rest.put.call_args[1]["json"] == {
            "path": "/PATCHSET_LEVEL",
            "message": "Looks good overall",
            "unresolved": False,
        }

    def test_reply_keeps_thread_link(self, rest):
        gate = DraftModeRest(rest)
        gate.post(REVIEW_ENDPOINT, json={
            "comments": {
                "lnet/lnet/api-ni.c": [{
                    "in_reply_to": "abc123",
                    "message": "Done",
                    "unresolved": False,
                    "line": 7,
                }],
            },
        })

        assert rest.put.call_args[1]["json"] == {
            "path": "lnet/lnet/api-ni.c",
            "message": "Done",
            "line": 7,
            "in_reply_to": "abc123",
            "unresolved": False,
        }

    def test_range_and_side_survive(self, rest):
        gate = DraftModeRest(rest)
        comment_range = {
            "start_line": 4, "start_character": 0,
            "end_line": 6, "end_character": 9,
        }
        gate.post(REVIEW_ENDPOINT, json={
            "comments": {
                "f.c": [{"message": "m", "range": comment_range, "side": "PARENT"}],
            },
        })

        sent = rest.put.call_args[1]["json"]
        assert sent["range"] == comment_range
        assert sent["side"] == "PARENT"

    def test_tag_is_dropped(self, rest):
        gate = DraftModeRest(rest)
        gate.post(REVIEW_ENDPOINT, json={
            "message": "m",
            "tag": "autogenerated:ai-review",
        })

        assert "tag" not in rest.put.call_args[1]["json"]

    def test_vote_is_refused(self, rest):
        gate = DraftModeRest(rest)
        with pytest.raises(DraftModeError):
            gate.post(REVIEW_ENDPOINT, json={
                "message": "m",
                "labels": {"Code-Review": 1},
            })

        rest.post.assert_not_called()
        rest.put.assert_not_called()

    def test_caller_input_not_mutated(self, rest):
        gate = DraftModeRest(rest)
        review_input = {"message": "cover", "comments": {"f.c": [{"message": "m"}]}}
        gate.post(REVIEW_ENDPOINT, json=review_input)

        assert review_input == {
            "message": "cover",
            "comments": {"f.c": [{"message": "m"}]},
        }

    def test_empty_review_creates_nothing(self, rest):
        gate = DraftModeRest(rest)
        result = gate.post(REVIEW_ENDPOINT, json={})

        rest.put.assert_not_called()
        assert result["drafts_created"] == 0

    def test_revision_sha_endpoint_is_gated(self, rest):
        gate = DraftModeRest(rest)
        gate.post(
            "/changes/62796/revisions/9f2a1b/review",
            json={"comments": {"f.c": [{"message": "m"}]}},
        )

        assert rest.put.call_args[0][0] == "/changes/62796/revisions/9f2a1b/drafts"

    def test_notice_goes_to_stderr(self, rest, capsys):
        gate = DraftModeRest(rest)
        gate.post(REVIEW_ENDPOINT, json={"message": "m"})

        captured = capsys.readouterr()
        assert captured.out == ""
        assert MODE_ENV_VAR in captured.err
