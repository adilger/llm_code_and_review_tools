"""release-priority: a Lustre release's priority changes, and what an
engineer can do to get them landed.

A release's priority changes are the open changes carrying its Gerrit
hashtag (2.18: 218_review_priority).  Each gets the status the Gerrit
Tracker and the public page at https://mulberrytree.us/release_priority/
give it.  The login is gerrit-cli's, from ~/.config/gerrit-cli/.env (or
GERRIT_URL, GERRIT_USER and GERRIT_PASS); it says who "me" is.  --user
picks another of its credential sets.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import click
from llm_tool_common.click_group import JsonErrorGroup
from llm_tool_common.config import (
    CredentialSetError,
    apply_credential_set,
    hoist_args,
    load_env_files,
)
from llm_tool_common.envelope import format_json, success_response
from llm_tool_common.errors import ErrorCode, ExitCode, ToolError
from llm_tool_common.update_check import maybe_check_for_updates

from . import gather as rg
from . import status as rs
from . import views

TOOL_NAME = "release-priority"
DEFAULT_RELEASE = "2.18"
DEFAULT_GERRIT = "https://review.whamcloud.com"

_FULL_ENVELOPE = False

_EXIT = {
    ErrorCode.AUTH_FAILED: ExitCode.AUTH_ERROR, ErrorCode.AUTH_MISSING: ExitCode.AUTH_ERROR,
    ErrorCode.NOT_FOUND: ExitCode.NOT_FOUND, ErrorCode.INVALID_INPUT: ExitCode.INVALID_INPUT,
    ErrorCode.CONNECTION_ERROR: ExitCode.NETWORK_ERROR,
}


def _fail(code: str, message: str, **details: Any) -> ToolError:
    return ToolError(code, message, details={k: v for k, v in details.items() if v is not None},
                     exit_code=_EXIT.get(code, ExitCode.GENERAL_ERROR))


def _emit(data: Any, command: str, next_actions: list[str] | None = None) -> None:
    click.echo(format_json(success_response(data, TOOL_NAME, command, next_actions=next_actions),
                           full_envelope=_FULL_ENVELOPE))


def gerrit_url() -> str:
    return (os.environ.get("GERRIT_URL") or DEFAULT_GERRIT).rstrip("/")


def client():
    from gerrit_cli.client import GerritCommentsClient, GerritConfigError
    try:
        return GerritCommentsClient(url=gerrit_url())
    except GerritConfigError as exc:
        raise _fail(ErrorCode.CONFIG_ERROR, str(exc)) from exc


def _gerrit_error(exc: Exception, what: str) -> ToolError:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 401:
        return _fail(ErrorCode.AUTH_FAILED, "Gerrit refused the login: check GERRIT_USER and "
                     "GERRIT_PASS (the HTTP password, from Gerrit's Settings > HTTP "
                     "Credentials).", http_status=status)
    if status == 404:
        return _fail(ErrorCode.NOT_FOUND, f"Gerrit has no {what}.", http_status=status)
    if status:
        return _fail(ErrorCode.API_ERROR, f"Gerrit answered HTTP {status} for {what}.",
                     http_status=status)
    return _fail(ErrorCode.CONNECTION_ERROR, f"Could not reach Gerrit for {what}: {exc}")


def identity(c, login: str | None) -> dict:
    """The account to show: the login's own, or LOGIN's (a username, email
    or account id)."""
    if login:
        try:
            a = c.rest.get(f"/accounts/{quote(login, safe='')}")
        except Exception as exc:
            raise _gerrit_error(exc, f"account {login!r}") from exc
    else:
        if not c.authenticated:
            raise _fail(ErrorCode.AUTH_MISSING, "No Gerrit login: set GERRIT_USER and "
                        "GERRIT_PASS, or configure gerrit-cli (~/.config/gerrit-cli/.env). "
                        "--as LOGIN shows someone else's view without one.")
        try:
            a = c.get_self_account()
        except Exception as exc:
            raise _gerrit_error(exc, "account for this login") from exc
    return {"id": a.get("_account_id"), "name": a.get("name") or a.get("username") or "",
            "username": a.get("username") or "", "email": a.get("email") or ""}


def _gather(release: str, hashtag: str | None, series: bool = True) -> tuple[dict, str]:
    tag = hashtag or rg.hashtag_for(release)
    try:
        return rg.gather(client(), tag, gerrit_url(), series=series), tag
    except ToolError:
        raise
    except Exception as exc:
        raise _gerrit_error(exc, f"changes tagged {tag}") from exc


class Group(JsonErrorGroup):
    """Global options work in any position."""

    tool_name = TOOL_NAME

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        return super().parse_args(
            ctx, hoist_args(args, flags=("--envelope",),
                            options=("--user", "-U", "--release", "-r", "--hashtag"))
        )


@click.group(cls=Group)
@click.version_option(package_name="release-priority", prog_name="release-priority")
@click.option("--envelope", is_flag=True, help="Include full response envelope (ok/data/meta wrapper)")
@click.option("--user", "-U", default=None,
              help="gerrit-cli credential set to use: a [section] alias or a GERRIT_USER "
                   "from ~/.config/gerrit-cli/.env")
@click.option("--release", "-r", default=DEFAULT_RELEASE, show_default=True,
              help="The release; its hashtag is the number without dots plus _review_priority.")
@click.option("--hashtag", default=None, help="Use this Gerrit hashtag instead of the release's.")
@click.pass_context
def main(ctx: click.Context, envelope: bool, user: str | None, release: str,
         hashtag: str | None) -> None:
    """A Lustre release's priority changes, and what you can do to land them.

    Output is JSON.  `me` is the place to start: your changes that need
    you, the reviews you owe, and the priority changes that need review.
    """
    maybe_check_for_updates()
    global _FULL_ENVELOPE
    _FULL_ENVELOPE = envelope
    try:
        load_env_files("gerrit-cli")
        if user:
            apply_credential_set("gerrit-cli", user)
    except (CredentialSetError, FileNotFoundError) as exc:
        raise _fail(ErrorCode.CONFIG_ERROR, str(exc)) from exc
    ctx.obj = {"release": release, "hashtag": hashtag}


@main.command()
@click.pass_obj
def whoami(obj: dict) -> None:
    """The Gerrit account your login is, and the release and hashtag in use."""
    me = identity(client(), None)
    tag = obj["hashtag"] or rg.hashtag_for(obj["release"])
    _emit({"you": me, "gerrit": gerrit_url(), "release": obj["release"], "hashtag": tag,
           "web_page": views.web_page(obj["release"])}, "whoami")


@main.command("me")
@click.option("--as", "login", default=None,
              help="Someone else's view: their Gerrit username, email or account id.")
@click.option("--master-next", "show_mn", is_flag=True,
              help="Also list the priority changes in master-next.")
@click.pass_obj
def me_cmd(obj: dict, login: str | None, show_mn: bool) -> None:
    """What is yours to do, and where you can help.

    your_move: your changes that need you.  your_changes_in_review: yours
    waiting on reviewers.  reviews_owed: changes you review that wait on
    your vote.  needs_review: the other changes that need review.
    """
    c = client()
    who = identity(c, login)
    got, tag = _gather(obj["release"], obj["hashtag"])
    data = views.me_view(got, who, obj["release"], tag, master_next=show_mn)
    nxt = [f"release-priority show {x['n']}" for x in (data["your_move"] + data["reviews_owed"])[:3]]
    _emit(data, "me", nxt + ["release-priority list --group review"])


@main.command("list")
@click.option("--group", "-g", "groups", multiple=True, type=click.Choice(rs.GROUP_KEYS),
              help="Only these groups (repeatable).")
@click.option("--owner", default=None, help="Only changes whose owner's name contains this, "
                                            "or whose username is this.")
@click.option("--no-series", is_flag=True, help="Skip reading series (faster; no Behind status).")
@click.pass_obj
def list_cmd(obj: dict, groups: tuple[str, ...], owner: str | None, no_series: bool) -> None:
    """Every open priority change, grouped as the web page groups them."""
    got, tag = _gather(obj["release"], obj["hashtag"], series=not no_series)
    _emit(views.listing(got, obj["release"], tag, groups=set(groups), owner=owner), "list",
          ["release-priority me"])


@main.command("master-next")
@click.pass_obj
def master_next_cmd(obj: dict) -> None:
    """The priority changes in master-next, and those ready to land."""
    got, tag = _gather(obj["release"], obj["hashtag"])
    _emit(views.master_next_view(got, obj["release"], tag), "master-next")


@main.command()
@click.argument("change")
@click.pass_obj
def show(obj: dict, change: str) -> None:
    """One priority change: its status, why, whose move, and what to do."""
    try:
        n = int(change.rstrip("/").rsplit("/", 1)[-1])
    except ValueError as exc:
        raise _fail(ErrorCode.INVALID_INPUT, f"Not a change number or URL: {change!r}") from exc
    got, tag = _gather(obj["release"], obj["hashtag"])
    found = next((x for x in got["changes"] if x["n"] == n), None)
    if not found:
        raise _fail(ErrorCode.NOT_FOUND, f"{n} is not an open change tagged {tag}.",
                    hashtag=tag)
    out = dict(views.record(found), **views.owner_action(found),
               hashtags=found["hashtags"], generated_at=got["generated_at"])
    _emit(out, "show")


if __name__ == "__main__":
    main()
