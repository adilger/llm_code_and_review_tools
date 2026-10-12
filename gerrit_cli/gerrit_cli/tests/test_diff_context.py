"""Compact diffs: Gerrit ignores ?context=, so review and diff cut it."""

from unittest.mock import MagicMock, patch

from gerrit_cli.reviewer import CodeReviewer, FileChange, content_to_hunks


def _ctx(start, n):
    return [f"l{i}" for i in range(start, start + n)]


# A 1000 line file with one line changed at 101 and one at 501, as the
# Whamcloud Gerrit returns it whatever context was asked for.
WHOLE_FILE = [
    {"ab": _ctx(1, 100)},
    {"a": ["old101"], "b": ["new101"]},
    {"ab": _ctx(102, 399)},
    {"a": ["old501"], "b": ["new501"]},
    {"ab": _ctx(502, 499)},
]


class TestContentToHunks:

    def test_default_context_is_three_lines(self):
        hunks = content_to_hunks(WHOLE_FILE, 3)
        assert len(hunks) == 2
        first, second = hunks
        assert (first.old_start, first.old_count) == (98, 7)
        assert (first.new_start, first.new_count) == (98, 7)
        assert [ln.content for ln in first.lines] == [
            "l98", "l99", "l100", "old101", "new101",
            "l102", "l103", "l104"]
        assert (second.old_start, second.old_count) == (498, 7)
        assert [ln.content for ln in second.lines][-3:] == [
            "l502", "l503", "l504"]

    def test_line_numbers_follow_the_file(self):
        hunks = content_to_hunks(WHOLE_FILE, 3)
        added = [ln for h in hunks for ln in h.lines if ln.type == "added"]
        assert [ln.line_number_new for ln in added] == [101, 501]
        tail = hunks[1].lines[-1]
        assert (tail.line_number_old, tail.line_number_new) == (504, 504)

    def test_none_keeps_the_whole_file(self):
        hunks = content_to_hunks(WHOLE_FILE, None)
        assert len(hunks) == 1
        assert hunks[0].old_count == 1000

    def test_zero_is_changes_only(self):
        hunks = content_to_hunks(WHOLE_FILE, 0)
        assert [[ln.type for ln in h.lines] for h in hunks] == [
            ["deleted", "added"], ["deleted", "added"]]
        assert hunks[1].old_start == 501

    def test_close_changes_share_a_hunk(self):
        content = [
            {"ab": _ctx(1, 10)},
            {"b": ["new"]},
            {"ab": _ctx(11, 6)},
            {"a": ["gone"]},
            {"ab": _ctx(18, 10)},
        ]
        hunks = content_to_hunks(content, 3)
        assert len(hunks) == 1
        assert hunks[0].old_start == 8
        assert sum(ln.type == "context" for ln in hunks[0].lines) == 12

    def test_server_skip_sections(self):
        content = [
            {"skip": 50},
            {"ab": _ctx(51, 3)},
            {"b": ["new"]},
            {"ab": _ctx(54, 3)},
            {"skip": 40},
        ]
        hunks = content_to_hunks(content, 3)
        assert len(hunks) == 1
        assert hunks[0].old_start == 51
        assert hunks[0].new_count == 7

    def test_unchanged_file_has_no_hunks(self):
        assert content_to_hunks([{"ab": _ctx(1, 5)}], 3) == []


class TestReviewCompactByDefault:

    @patch("gerrit_cli.reviewer.GerritCommentsClient")
    def test_review_data_cuts_context(self, mock_client_class):
        client = MagicMock()
        client.format_change_url.return_value = "https://example.com/123"
        client.rest.get.side_effect = [
            {"id": "x", "current_revision": "abc",
             "revisions": {"abc": {"commit": {"message": "m",
                                              "parents": []}}}},
            {"big.sh": {"status": "M", "lines_inserted": 2,
                        "lines_deleted": 2}},
            {"content": WHOLE_FILE},
        ]
        mock_client_class.return_value = client
        mock_client_class.parse_gerrit_url.return_value = (
            client.url, 123)

        data = CodeReviewer().get_review_data("https://example.com/123")

        diff = data.files[0].to_dict()["diff"]
        assert diff.count("\n@@ ") == 2
        assert "l50" not in diff.split("\n")
        assert "new_content" not in data.files[0].to_dict()

    @patch("gerrit_cli.reviewer.GerritCommentsClient")
    def test_base_patchset_reaches_gerrit(self, mock_client_class):
        client = MagicMock()
        client.rest.get.side_effect = [
            {"id": "x", "current_revision": "abc", "revisions": {}},
            {"f.c": {"status": "M"}},
            {"content": []},
        ]
        mock_client_class.return_value = client
        mock_client_class.parse_gerrit_url.return_value = (
            client.url, 123)

        CodeReviewer().get_review_data("https://example.com/123", base=2)

        urls = [c.args[0] for c in client.rest.get.call_args_list]
        assert urls[1].endswith("/files?base=2")
        assert urls[2].endswith("/diff?base=2")

    def test_new_content_kept_when_fetched(self):
        fc = FileChange(path="a", status="M", old_path=None, lines_added=0,
                        lines_deleted=0, size_delta=0, new_content="x")
        assert fc.to_dict()["new_content"] == "x"
