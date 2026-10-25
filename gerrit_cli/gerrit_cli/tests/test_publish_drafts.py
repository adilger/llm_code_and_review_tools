"""publish-drafts refuses in drafts mode, lists drafts in a dry run, and
checks the patchset before it publishes."""

import argparse
import json
from unittest.mock import patch

import pytest

from gerrit_cli.errors import ExitCode
from gerrit_cli.mode import MODE_DRAFTS, MODE_ENV_VAR, MODE_FULL

DRAFTS = {"lnet/lnet/peer.c": [{"id": "d1", "line": 12, "patch_set": 3,
                                "message": "Done", "unresolved": False}],
          "/PATCHSET_LEVEL": [{"id": "d2", "patch_set": 3,
                               "message": "Thanks"}]}


def _run(capsys, *, dry_run=False, expect=None, current=3, drafts=DRAFTS):
    from gerrit_cli.cli import cmd_publish_drafts
    args = argparse.Namespace(url="12345", dry_run=dry_run,
                              expect_patchset=expect, pretty=False)
    with patch('gerrit_cli.cli.GerritCommentsClient') as MockClient, \
         pytest.raises(SystemExit) as exc_info:
        MockClient.parse_gerrit_url.return_value = (
            "https://example.com", 12345)
        client = MockClient.return_value
        client.get_change.return_value = {"current_revision_number": current}
        client.get_drafts.return_value = drafts
        cmd_publish_drafts(args)
    return exc_info.value.code, json.loads(capsys.readouterr().out), client


def test_drafts_mode_refuses_and_publishes_nothing(capsys, monkeypatch):
    monkeypatch.setenv(MODE_ENV_VAR, MODE_DRAFTS)
    code, out, client = _run(capsys)
    assert code != ExitCode.SUCCESS
    assert "drafts mode publishes nothing" in out["message"]
    client.publish_drafts.assert_not_called()


def test_unset_mode_publishes(capsys, monkeypatch):
    monkeypatch.delenv(MODE_ENV_VAR, raising=False)
    code, _, client = _run(capsys)
    assert code == ExitCode.SUCCESS
    client.publish_drafts.assert_called_once()


def test_dry_run_lists_drafts_in_any_mode(capsys, monkeypatch):
    monkeypatch.setenv(MODE_ENV_VAR, MODE_DRAFTS)
    code, out, client = _run(capsys, dry_run=True)
    assert code == ExitCode.SUCCESS
    assert out["would_publish"] == 2
    assert out["mode_allows_publish"] is False
    assert {d["id"] for d in out["drafts"]} == {"d1", "d2"}
    client.publish_drafts.assert_not_called()


def test_full_mode_publishes(capsys, monkeypatch):
    monkeypatch.setenv(MODE_ENV_VAR, MODE_FULL)
    code, out, client = _run(capsys, expect=3)
    assert code == ExitCode.SUCCESS
    assert out["published"] is True and out["count"] == 2
    client.publish_drafts.assert_called_once_with(12345)


def test_wrong_patchset_refuses(capsys, monkeypatch):
    monkeypatch.setenv(MODE_ENV_VAR, MODE_FULL)
    code, out, client = _run(capsys, expect=2, current=3)
    assert code == ExitCode.INVALID_INPUT
    assert "patchset 3, not 2" in out["message"]
    client.publish_drafts.assert_not_called()


def test_no_drafts_publishes_nothing(capsys, monkeypatch):
    monkeypatch.setenv(MODE_ENV_VAR, MODE_FULL)
    code, out, client = _run(capsys, drafts={})
    assert code == ExitCode.SUCCESS and out["published"] is False
    client.publish_drafts.assert_not_called()


def test_client_posts_publish_all_revisions():
    from unittest.mock import MagicMock

    from gerrit_cli.client import GerritCommentsClient
    client = GerritCommentsClient.__new__(GerritCommentsClient)
    client.rest = MagicMock()
    client.publish_drafts(12345)
    client.rest.post.assert_called_once_with(
        "/changes/12345/revisions/current/review",
        json={"drafts": "PUBLISH_ALL_REVISIONS"})
