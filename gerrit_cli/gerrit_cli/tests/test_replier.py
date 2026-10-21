"""Tests for the replier module."""

from unittest.mock import MagicMock, patch

from gerrit_cli.models import (
    Author,
    ChangeInfo,
    Comment,
    CommentThread,
    ExtractedComments,
)
from gerrit_cli.replier import CommentReplier, mark_done, reply_to_comment


class TestCommentReplier:
    """Tests for CommentReplier."""

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_reply_to_comment_success(self, mock_client_class):
        """Test successful reply to comment."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client_class.return_value = mock_client

        comment = Comment(
            id="comment1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix this",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )

        replier = CommentReplier()
        result = replier.reply_to_comment(
            change_number=123,
            comment=comment,
            message="Done",
            mark_resolved=True,
        )

        assert result.success is True
        assert result.comment_id == "comment1"
        assert result.message == "Done"
        assert result.marked_resolved is True
        assert result.error is None

        mock_client.post_review.assert_called_once_with(
            change_number=123,
            revision_id="abc123",
            comments={"test.py": [{
                "in_reply_to": "comment1",
                "message": "Done",
                "unresolved": False,
                "line": 10,
            }]},
        )

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_reply_to_comment_failure(self, mock_client_class):
        """Test failed reply to comment."""
        mock_client = MagicMock()
        mock_client.get_change_detail.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        comment = Comment(
            id="comment1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix this",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )

        replier = CommentReplier()
        result = replier.reply_to_comment(
            change_number=123,
            comment=comment,
            message="Done",
            mark_resolved=True,
        )

        assert result.success is False
        assert result.error == "API Error"

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_mark_done(self, mock_client_class):
        """Test marking comment as done."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client_class.return_value = mock_client

        comment = Comment(
            id="comment1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix this",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )

        replier = CommentReplier()
        result = replier.mark_done(change_number=123, comment=comment)

        assert result.success is True
        assert result.message == "Done"
        assert result.marked_resolved is True

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_mark_done_custom_message(self, mock_client_class):
        """Test marking comment as done with custom message."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client_class.return_value = mock_client

        comment = Comment(
            id="comment1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix this",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )

        replier = CommentReplier()
        result = replier.mark_done(
            change_number=123,
            comment=comment,
            message="Fixed in patchset 5",
        )

        assert result.message == "Fixed in patchset 5"

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_acknowledge(self, mock_client_class):
        """Test acknowledging a comment."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client_class.return_value = mock_client

        comment = Comment(
            id="comment1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Consider refactoring",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )

        replier = CommentReplier()
        result = replier.acknowledge(change_number=123, comment=comment)

        assert result.success is True
        assert result.message == "Acknowledged"
        assert result.marked_resolved is True

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_reply_to_thread_uses_last_comment(self, mock_client_class):
        """Test that reply_to_thread uses the last comment in the thread."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client_class.return_value = mock_client

        root = Comment(
            id="root",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix this",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )
        reply = Comment(
            id="reply1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Working on it",
            author=Author(name="Author"),
            unresolved=True,
            updated="2025-01-02",
            in_reply_to="root",
        )
        thread = CommentThread(root_comment=root, replies=[reply])

        replier = CommentReplier()
        replier.reply_to_thread(
            change_number=123,
            thread=thread,
            message="Done now",
            mark_resolved=True,
        )

        # Should reply to the last comment (reply1)
        mock_client.post_review.assert_called_once()
        [reply_input] = mock_client.post_review.call_args[1]["comments"]["test.py"]
        assert reply_input["in_reply_to"] == "reply1"

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_reply_to_thread_with_no_replies(self, mock_client_class):
        """Test reply_to_thread when thread has no replies."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client_class.return_value = mock_client

        root = Comment(
            id="root",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix this",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )
        thread = CommentThread(root_comment=root)

        replier = CommentReplier()
        replier.reply_to_thread(
            change_number=123,
            thread=thread,
            message="Done",
        )

        # Should reply to the root comment
        [reply_input] = mock_client.post_review.call_args[1]["comments"]["test.py"]
        assert reply_input["in_reply_to"] == "root"

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_batch_reply_success(self, mock_client_class):
        """Test batch reply with multiple comments."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client.post_review.return_value = {}
        mock_client_class.return_value = mock_client

        comment1 = Comment(
            id="c1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix 1",
            author=Author(name="R"),
            unresolved=True,
            updated="2025-01-01",
        )
        comment2 = Comment(
            id="c2",
            patch_set=1,
            file_path="other.py",
            line=20,
            message="Fix 2",
            author=Author(name="R"),
            unresolved=True,
            updated="2025-01-01",
        )

        replier = CommentReplier()
        results = replier.batch_reply(
            change_number=123,
            replies=[
                {"comment": comment1, "message": "Done 1", "mark_resolved": True},
                {"comment": comment2, "message": "Done 2", "mark_resolved": True},
            ],
        )

        assert len(results) == 2
        assert all(r.success for r in results)

        # Verify post_review was called with both comments
        call_args = mock_client.post_review.call_args
        comments = call_args[1]["comments"]
        assert "test.py" in comments
        assert "other.py" in comments

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_batch_reply_failure(self, mock_client_class):
        """Test batch reply failure."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client.post_review.side_effect = Exception("Batch failed")
        mock_client_class.return_value = mock_client

        comment = Comment(
            id="c1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix",
            author=Author(name="R"),
            unresolved=True,
            updated="2025-01-01",
        )

        replier = CommentReplier()
        results = replier.batch_reply(
            change_number=123,
            replies=[{"comment": comment, "message": "Done"}],
        )

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error == "Batch failed"

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_batch_reply_on_a_file_the_new_patchset_deleted(self, mock_client_class):
        """51164: PS9 deleted the file PS8's comment was on, and Gerrit
        refused the whole review posted on PS9."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "ps9sha",
            "revisions": {"ps8sha": {"_number": 8}, "ps9sha": {"_number": 9}},
        }
        mock_client_class.return_value = mock_client

        def comment(cid, path, line):
            return Comment(
                id=cid, patch_set=8, file_path=path, line=line, message="x",
                author=Author(name="R"), unresolved=True, updated="2026-10-02",
            )

        replier = CommentReplier()
        results = replier.batch_reply(
            change_number=51164,
            replies=[
                {"comment": comment("gone", "Documentation/man4/pinger.4", 3),
                 "message": "Removed in PS9.", "mark_resolved": True},
                {"comment": comment("kept", "lustre/kept.c", 10),
                 "message": "Done."},
                {"comment": comment("ps", "/PATCHSET_LEVEL", None),
                 "message": "Thanks."},
            ],
        )

        assert [r.comment_id for r in results] == ["gone", "kept", "ps"]
        assert all(r.success for r in results)
        posts = {
            c.kwargs["revision_id"]: c.kwargs["comments"]
            for c in mock_client.post_review.call_args_list
        }
        assert list(posts) == ["ps8sha"]
        assert sorted(posts["ps8sha"]) == [
            "/PATCHSET_LEVEL", "Documentation/man4/pinger.4", "lustre/kept.c",
        ]
        assert posts["ps8sha"]["Documentation/man4/pinger.4"][0]["unresolved"] is False

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_batch_reply_goes_on_each_parents_patchset(self, mock_client_class):
        """68672: replies to PS1 comments went on PS2, at PS1's line
        numbers, and the threads showed split across patchsets."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "ps3sha",
            "revisions": {
                "ps1sha": {"_number": 1},
                "ps2sha": {"_number": 2},
                "ps3sha": {"_number": 3},
            },
        }
        mock_client_class.return_value = mock_client
        span = {"start_line": 40, "start_character": 0,
                "end_line": 42, "end_character": 7}
        on_ps1 = Comment(
            id="a", patch_set=1, file_path="lustre/mdt/mdt_reint.c", line=42,
            message="x", author=Author(name="R"), unresolved=True,
            updated="2026-10-21", range=span,
        )
        on_ps2 = Comment(
            id="b", patch_set=2, file_path="lustre/mdt/mdt_reint.c", line=9,
            message="x", author=Author(name="R"), unresolved=True,
            updated="2026-10-21", side="PARENT",
        )

        results = CommentReplier().batch_reply(
            change_number=68672,
            replies=[
                {"comment": on_ps1, "message": "Done.", "mark_resolved": True},
                {"comment": on_ps2, "message": "Why?"},
            ],
        )

        assert all(r.success for r in results)
        posts = {
            c.kwargs["revision_id"]: c.kwargs["comments"]["lustre/mdt/mdt_reint.c"]
            for c in mock_client.post_review.call_args_list
        }
        assert posts == {
            "ps1sha": [{"in_reply_to": "a", "message": "Done.",
                        "unresolved": False, "line": 42, "range": span}],
            "ps2sha": [{"in_reply_to": "b", "message": "Why?",
                        "unresolved": True, "line": 9, "side": "PARENT"}],
        }

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_batch_reply_failure_carries_gerrits_reason(self, mock_client_class):
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {"current_revision": "abc"}
        error = Exception("400 Client Error: Bad Request")
        error.response = MagicMock(text="file x not found in revision 51164,9\n")
        mock_client.post_review.side_effect = error
        mock_client_class.return_value = mock_client
        comment = Comment(
            id="c1", patch_set=1, file_path="test.py", line=1, message="x",
            author=Author(name="R"), unresolved=True, updated="2026-10-02",
        )

        [result] = CommentReplier().batch_reply(
            change_number=1, replies=[{"comment": comment, "message": "y"}],
        )

        assert result.success is False
        assert result.error == (
            "400 Client Error: Bad Request: file x not found in revision 51164,9"
        )

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_reply_from_extracted(self, mock_client_class):
        """Test replying from extracted comments by index."""
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123"
        }
        mock_client_class.return_value = mock_client

        change_info = ChangeInfo(
            change_id="test~123",
            change_number=123,
            project="test",
            branch="master",
            subject="Test",
            status="NEW",
            current_revision="abc123",
            owner=Author(name="Owner"),
            url="https://example.com/123",
        )
        thread = CommentThread(
            root_comment=Comment(
                id="c1",
                patch_set=1,
                file_path="test.py",
                line=10,
                message="Fix",
                author=Author(name="R"),
                unresolved=True,
                updated="2025-01-01",
            )
        )
        extracted = ExtractedComments(
            change_info=change_info,
            threads=[thread],
            unresolved_count=1,
            total_count=1,
        )

        replier = CommentReplier()
        result = replier.reply_from_extracted(
            extracted=extracted,
            thread_index=0,
            message="Done",
            mark_resolved=True,
        )

        assert result.success is True

    @patch("gerrit_cli.replier.GerritCommentsClient")
    def test_reply_from_extracted_invalid_index(self, mock_client_class):
        """Test replying with invalid thread index."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        change_info = ChangeInfo(
            change_id="test~123",
            change_number=123,
            project="test",
            branch="master",
            subject="Test",
            status="NEW",
            current_revision="abc123",
            owner=Author(name="Owner"),
            url="https://example.com/123",
        )
        extracted = ExtractedComments(
            change_info=change_info,
            threads=[],
            unresolved_count=0,
            total_count=0,
        )

        replier = CommentReplier()
        result = replier.reply_from_extracted(
            extracted=extracted,
            thread_index=5,
            message="Done",
        )

        assert result.success is False
        assert "Invalid thread index" in result.error


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @patch("gerrit_cli.replier.CommentReplier")
    def test_reply_to_comment_function(self, mock_replier_class):
        """Test reply_to_comment convenience function."""
        mock_replier = MagicMock()
        mock_replier_class.return_value = mock_replier

        comment = Comment(
            id="c1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix",
            author=Author(name="R"),
            unresolved=True,
            updated="2025-01-01",
        )

        reply_to_comment(123, comment, "Thanks!", mark_resolved=False)

        mock_replier.reply_to_comment.assert_called_once_with(
            change_number=123,
            comment=comment,
            message="Thanks!",
            mark_resolved=False,
        )

    @patch("gerrit_cli.replier.CommentReplier")
    def test_mark_done_function(self, mock_replier_class):
        """Test mark_done convenience function."""
        mock_replier = MagicMock()
        mock_replier_class.return_value = mock_replier

        comment = Comment(
            id="c1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Fix",
            author=Author(name="R"),
            unresolved=True,
            updated="2025-01-01",
        )

        mark_done(123, comment, message="Fixed!")

        mock_replier.mark_done.assert_called_once_with(
            change_number=123,
            comment=comment,
            message="Fixed!",
        )


class TestPushStaged:
    """Tests for push_staged method."""

    @patch("gerrit_cli.replier.GerritCommentsClient")
    @patch("gerrit_cli.replier.StagingManager")
    def test_push_staged_no_operations(self, mock_staging_class, mock_client_class):
        """Test push_staged with no staged operations."""
        mock_staging = MagicMock()
        mock_staging.load_staged.return_value = None
        mock_staging_class.return_value = mock_staging

        replier = CommentReplier()
        success, msg, count = replier.push_staged(12345)

        assert success is False
        assert "No staged operations" in msg
        assert count == 0

    @patch("gerrit_cli.replier.GerritCommentsClient")
    @patch("gerrit_cli.replier.StagingManager")
    def test_push_staged_success_with_resolve(
        self, mock_staging_class, mock_client_class
    ):
        """Test push_staged correctly sets unresolved=False for resolved comments."""
        from gerrit_cli.staging import StagedOperation, StagedPatch

        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123",
            "revisions": {"abc123": {"_number": 5}},
        }
        mock_client_class.return_value = mock_client

        # Create staged operations - one resolved, one not
        staged = StagedPatch(
            change_number=12345,
            change_url="https://example.com/12345",
            patchset=5,
            operations=[
                StagedOperation(
                    thread_index=0,
                    file_path="test.c",
                    line=10,
                    message="Done",
                    resolve=True,  # Should set unresolved=False
                    comment_id="id1",
                ),
                StagedOperation(
                    thread_index=1,
                    file_path="test.c",
                    line=20,
                    message="Looking into this",
                    resolve=False,  # Should set unresolved=True
                    comment_id="id2",
                ),
            ],
        )

        mock_staging = MagicMock()
        mock_staging.load_staged.return_value = staged
        mock_staging_class.return_value = mock_staging

        replier = CommentReplier()
        success, msg, count = replier.push_staged(12345)

        assert success is True
        assert count == 2

        # Verify post_review was called with correct unresolved flags
        mock_client.post_review.assert_called_once()
        call_args = mock_client.post_review.call_args
        comments = call_args.kwargs.get("comments") or call_args[1].get("comments")

        # Both comments are in test.c
        assert "test.c" in comments
        test_comments = comments["test.c"]
        assert len(test_comments) == 2

        # First comment should be resolved (unresolved=False)
        resolved_comment = next(c for c in test_comments if c["message"] == "Done")
        assert resolved_comment["unresolved"] is False

        # Second comment should not be resolved (unresolved=True)
        unresolved_comment = next(
            c for c in test_comments if c["message"] == "Looking into this"
        )
        assert unresolved_comment["unresolved"] is True

    @patch("gerrit_cli.replier.GerritCommentsClient")
    @patch("gerrit_cli.replier.StagingManager")
    def test_push_staged_dry_run(self, mock_staging_class, mock_client_class):
        """Test push_staged dry_run mode."""
        from gerrit_cli.staging import StagedOperation, StagedPatch

        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123",
            "revisions": {"abc123": {"_number": 5}},
        }
        mock_client_class.return_value = mock_client

        staged = StagedPatch(
            change_number=12345,
            change_url="https://example.com/12345",
            patchset=5,
            operations=[
                StagedOperation(
                    thread_index=0,
                    file_path="test.c",
                    line=10,
                    message="Done",
                    resolve=True,
                    comment_id="id1",
                ),
            ],
        )

        mock_staging = MagicMock()
        mock_staging.load_staged.return_value = staged
        mock_staging_class.return_value = mock_staging

        replier = CommentReplier()
        success, msg, count = replier.push_staged(12345, dry_run=True)

        assert success is True
        assert "Would push" in msg
        assert "RESOLVE" in msg  # Should indicate resolve action
        # Should NOT actually call post_review in dry run
        mock_client.post_review.assert_not_called()

    @patch("gerrit_cli.replier.GerritCommentsClient")
    @patch("gerrit_cli.replier.StagingManager")
    def test_push_staged_clears_after_success(
        self, mock_staging_class, mock_client_class
    ):
        """Test push_staged clears staged operations after success."""
        from gerrit_cli.staging import StagedOperation, StagedPatch

        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123",
            "revisions": {"abc123": {"_number": 5}},
        }
        mock_client_class.return_value = mock_client

        staged = StagedPatch(
            change_number=12345,
            change_url="https://example.com/12345",
            patchset=5,
            operations=[
                StagedOperation(
                    thread_index=0,
                    file_path="test.c",
                    line=10,
                    message="Done",
                    resolve=True,
                    comment_id="id1",
                ),
            ],
        )

        mock_staging = MagicMock()
        mock_staging.load_staged.return_value = staged
        mock_staging_class.return_value = mock_staging

        replier = CommentReplier()
        success, msg, count = replier.push_staged(12345)

        assert success is True
        mock_staging.clear_staged.assert_called_once_with(12345)

    @patch("gerrit_cli.replier.GerritCommentsClient")
    @patch("gerrit_cli.replier.StagingManager")
    def test_push_staged_api_error(self, mock_staging_class, mock_client_class):
        """Test push_staged handles API errors."""
        from gerrit_cli.staging import StagedOperation, StagedPatch

        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "abc123",
            "revisions": {"abc123": {"_number": 5}},
        }
        mock_client.post_review.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        staged = StagedPatch(
            change_number=12345,
            change_url="https://example.com/12345",
            patchset=5,
            operations=[
                StagedOperation(
                    thread_index=0,
                    file_path="test.c",
                    line=10,
                    message="Done",
                    resolve=True,
                    comment_id="id1",
                ),
            ],
        )

        mock_staging = MagicMock()
        mock_staging.load_staged.return_value = staged
        mock_staging_class.return_value = mock_staging

        replier = CommentReplier()
        success, msg, count = replier.push_staged(12345)

        assert success is False
        assert "Error" in msg
        # Should NOT clear staged operations on failure
        mock_staging.clear_staged.assert_not_called()

    @patch("gerrit_cli.replier.GerritCommentsClient")
    @patch("gerrit_cli.replier.StagingManager")
    def test_push_staged_replies_on_each_parents_patchset(
        self, mock_staging_class, mock_client_class
    ):
        """A reply staged on PS2 and pushed after PS3 goes on PS2, at the
        parent's line and range; one the change no longer has goes on PS3.
        When the second review fails, only its replies stay staged."""
        from gerrit_cli.staging import StagedOperation, StagedPatch

        span = {"start_line": 8, "start_character": 0,
                "end_line": 10, "end_character": 3}
        mock_client = MagicMock()
        mock_client.get_change_detail.return_value = {
            "current_revision": "ps3sha",
            "revisions": {"ps2sha": {"_number": 2}, "ps3sha": {"_number": 3}},
        }
        mock_client.get_comments.return_value = {
            "test.c": [{"id": "id1", "patch_set": 2, "line": 10, "range": span}],
        }
        mock_client.post_review.side_effect = [{}, Exception("API Error")]
        mock_client_class.return_value = mock_client

        first = StagedOperation(
            thread_index=0, file_path="test.c", line=10, message="Done",
            resolve=True, comment_id="id1",
        )
        second = StagedOperation(
            thread_index=1, file_path="test.c", line=20, message="Why?",
            resolve=False, comment_id="gone",
        )
        staged = StagedPatch(
            change_number=12345, change_url="https://example.com/12345",
            patchset=2, operations=[first, second],
        )
        mock_staging = MagicMock()
        mock_staging.load_staged.return_value = staged
        mock_staging_class.return_value = mock_staging

        success, msg, count = CommentReplier().push_staged(12345)

        posts = [
            (c.kwargs["revision_id"], c.kwargs["comments"])
            for c in mock_client.post_review.call_args_list
        ]
        assert posts == [
            ("ps2sha", {"test.c": [{"in_reply_to": "id1", "message": "Done",
                                    "unresolved": False, "line": 10,
                                    "range": span}]}),
            ("ps3sha", {"test.c": [{"in_reply_to": "gone", "message": "Why?",
                                    "unresolved": True, "line": 20}]}),
        ]
        assert success is False
        assert "1 of 2 were posted" in msg
        mock_staging.clear_staged.assert_not_called()
        [saved] = mock_staging.save_staged.call_args[0]
        assert saved.operations == [second]
