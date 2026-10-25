"""Operating mode gate for gerrit-cli.

The GERRIT_CLI_MODE environment variable selects how the tool writes to
Gerrit:

    full    - every operation is published immediately (the default)
    drafts  - review comments become draft comments, visible only to the
              authenticated user until they publish them in the web UI

An unset or empty variable means "full". Any other value except "full"
means "drafts", so a misspelled request for drafts never publishes.

Draft mode rewrites the ReviewInput POST
(/changes/N/revisions/R/review) into one CommentInput PUT per comment
(/changes/N/revisions/R/drafts). Gerrit has no draft form of a label
vote, so a review that carries labels is refused instead.
"""

import copy
import os
import re
import sys
from typing import Any, Optional

MODE_ENV_VAR = "GERRIT_CLI_MODE"
MODE_FULL = "full"
MODE_DRAFTS = "drafts"

# Gerrit pseudo-file for a comment that belongs to the patchset as a
# whole rather than to a file. Used to carry the cover message, which
# has no draft form of its own.
PATCHSET_LEVEL = "/PATCHSET_LEVEL"

_REVIEW_ENDPOINT = re.compile(r"^(/changes/[^/]+/revisions/[^/]+)/review/?$")

# CommentInput fields that survive the ReviewInput -> draft rewrite.
# Everything else (notably "tag") is rejected on draft comments.
_COMMENT_FIELDS = (
    "line",
    "range",
    "side",
    "parent",
    "in_reply_to",
    "unresolved",
)


class DraftModeError(Exception):
    """Raised when an operation has no draft equivalent."""
    pass


def get_mode() -> str:
    """Return the active mode, either "full" or "drafts".

    Return: MODE_FULL when GERRIT_CLI_MODE is unset, empty or "full"
            (case-insensitive); MODE_DRAFTS otherwise.
    """
    value = (os.environ.get(MODE_ENV_VAR) or "").strip().lower()
    return MODE_FULL if value in ("", MODE_FULL) else MODE_DRAFTS


def is_drafts_mode() -> bool:
    """Return True when comments must be written as drafts."""
    return get_mode() == MODE_DRAFTS


def result_fields() -> dict[str, Any]:
    """Return the mode fields that write commands add to their output.

    Return: {"gerrit_cli_mode": <mode>, "published": <bool>}; in drafts
            mode "published" is False because the comments wait in the
            user's Gerrit draft buffer.
    """
    mode = get_mode()
    return {"gerrit_cli_mode": mode, "published": mode == MODE_FULL}


def _notify(message: str) -> None:
    """Write a mode notice to stderr, keeping stdout pure JSON."""
    print(f"[{MODE_ENV_VAR}={MODE_DRAFTS}] {message}", file=sys.stderr)


def _to_comment_inputs(
    review_input: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten a ReviewInput into a list of Gerrit CommentInput dicts.

    The cover message becomes a patchset-level comment, since Gerrit
    publishes review messages immediately and has no draft form.

    Args:
        review_input: The ReviewInput body of a /review POST.

    Return: One CommentInput per comment, cover message first.
    """
    comments = copy.deepcopy(review_input.get("comments") or {})
    message = review_input.get("message")

    if message:
        comments.setdefault(PATCHSET_LEVEL, []).insert(
            0, {"message": message, "unresolved": False}
        )

    inputs = []
    for path, path_comments in comments.items():
        for comment in path_comments:
            comment_input: dict[str, Any] = {
                "path": path,
                "message": comment.get("message", ""),
            }
            for field in _COMMENT_FIELDS:
                if comment.get(field) is not None:
                    comment_input[field] = comment[field]
            inputs.append(comment_input)

    return inputs


class DraftModeRest:
    """REST wrapper that turns published reviews into draft comments.

    Wraps a pygerrit2 GerritRestAPI. Every call except a POST to a
    /review endpoint is passed through unchanged.
    """

    def __init__(self, rest: Any):
        self._rest = rest

    def __getattr__(self, name: str) -> Any:
        return getattr(self._rest, name)

    def post(self, endpoint: str, **kwargs: Any) -> Any:
        """POST to Gerrit, rewriting a review into drafts.

        Args:
            endpoint: REST endpoint path.
            **kwargs: Passed through to the wrapped API; "json" holds
                the ReviewInput for a review POST.

        Return: The wrapped API response, or a summary dict describing
                the drafts created.

        Raises:
            DraftModeError: The review carries a label vote.
        """
        match = _REVIEW_ENDPOINT.match(endpoint)
        if not match:
            return self._rest.post(endpoint, **kwargs)

        review_input = kwargs.get("json") or {}

        if review_input.get("labels"):
            raise DraftModeError(
                f"Votes cannot be drafted. {MODE_ENV_VAR}={MODE_DRAFTS} "
                f"allows draft comments only. Post the review without a "
                f"vote, or have the account owner run this with "
                f"{MODE_ENV_VAR}={MODE_FULL}."
            )

        drafts_endpoint = f"{match.group(1)}/drafts"
        comment_inputs = _to_comment_inputs(review_input)

        created = 0
        for comment_input in comment_inputs:
            self._rest.put(drafts_endpoint, json=comment_input)
            created += 1

        _notify(
            f"created {created} draft comment(s); nothing is published. "
            f"Review and publish them in the Gerrit web UI."
        )

        return {
            "gerrit_cli_mode": MODE_DRAFTS,
            "drafts_created": created,
            "published": False,
        }


def wrap_rest(rest: Any, mode: Optional[str] = None) -> Any:
    """Return rest, wrapped by the draft gate when drafts mode is on.

    Args:
        rest: A pygerrit2 GerritRestAPI instance.
        mode: Mode override; the environment is read when omitted.

    Return: The original object in full mode, a DraftModeRest otherwise.
    """
    active = mode or get_mode()
    return rest if active == MODE_FULL else DraftModeRest(rest)
