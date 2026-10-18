"""An option between a command's positionals must not lose the last one.

`gc reply 15 --url URL "message"` failed with "unrecognized arguments":
argparse ended the positionals at --url, matched no message, and then had
nowhere to put it. `gc reply --url URL 15 "message"` worked.
"""

import pytest

from gerrit_cli.cli import build_parser


@pytest.mark.parametrize("argv, expected", [
    (["reply", "15", "--url", "68747", "the reply", "--dry-run"],
     {"thread_index": 15, "message": "the reply", "url": "68747", "dry_run": True}),
    (["reply", "--url", "68747", "15", "the reply"],
     {"thread_index": 15, "message": "the reply", "url": "68747"}),
    (["reply", "15", "--done", "--url", "68747"],
     {"thread_index": 15, "message": None, "done": True}),
    (["stage", "3", "--url", "68747", "the reply"],
     {"thread_index": 3, "message": "the reply", "url": "68747"}),
    (["done", "68747", "--pretty", "3", "Fixed"],
     {"url": "68747", "thread_index": 3, "message": "Fixed"}),
    (["ack", "68747", "3"],
     {"url": "68747", "thread_index": 3, "message": "Acknowledged"}),
    (["abandon", "68747", "--dry-run", "superseded"],
     {"url": "68747", "message": "superseded", "dry_run": True}),
    (["diff", "68747", "3", "--unified", "5", "4"],
     {"url": "68747", "patchset_a": 3, "patchset_b": 4}),
])
def test_positionals_may_sit_either_side_of_an_option(argv, expected):
    args = vars(build_parser().parse_args(argv))
    assert {key: args.get(key) for key in expected} == expected


def test_a_stray_argument_is_still_refused(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["reply", "15", "--url", "68747", "a", "b"])
    assert "unrecognized arguments: b" in capsys.readouterr().out


def test_commands_with_subcommands_parse_as_before():
    args = build_parser().parse_args(["staged", "show", "12345"])
    assert args.command == "staged"
