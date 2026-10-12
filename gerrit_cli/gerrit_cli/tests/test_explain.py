"""explain and describe know every command the parser registers."""

import argparse
import json

import pytest

from gerrit_cli.cli import build_parser
from gerrit_cli.commands.meta import (
    COMMAND_ALIASES,
    COMMAND_EXPLANATIONS,
    cmd_describe,
    cmd_explain,
)
from gerrit_cli.describe import registered_commands

REGISTERED = registered_commands(build_parser())


class TestExplainCoversEveryCommand:

    def test_every_command_has_an_explanation(self):
        missing = sorted({canon for canon, _ in REGISTERED.values()}
                         - set(COMMAND_EXPLANATIONS))
        assert missing == []

    def test_every_alias_resolves(self):
        for name, (canon, _) in REGISTERED.items():
            if name != canon:
                assert COMMAND_ALIASES.get(name) == canon, name

    def test_no_explanation_for_a_command_that_does_not_exist(self):
        stale = sorted(set(COMMAND_EXPLANATIONS) - set(REGISTERED))
        assert stale == []

    def test_related_commands_exist(self):
        for name, info in COMMAND_EXPLANATIONS.items():
            for rel in info.get("related", []):
                assert rel in REGISTERED, (name, rel)

    @pytest.mark.parametrize("name", sorted(REGISTERED))
    def test_explain_runs(self, name, capsys):
        cmd_explain(argparse.Namespace(command_name=name))
        out = capsys.readouterr().out
        assert out.startswith(f"gc {REGISTERED[name][0]} - ")

    def test_explain_info(self, capsys):
        cmd_explain(argparse.Namespace(command_name="info"))
        out = capsys.readouterr().out
        assert "--include-system" in out

    def test_unknown_command_still_refused(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cmd_explain(argparse.Namespace(command_name="no-such-command"))
        assert exc.value.code == 1
        assert "Unknown command: no-such-command" in capsys.readouterr().err


class TestDescribeCoversEveryCommand:

    def _describe(self, capsys, command_name=None):
        with pytest.raises(SystemExit) as exc:
            cmd_describe(argparse.Namespace(pretty=False,
                                            command_name=command_name))
        assert exc.value.code == 0
        return json.loads(capsys.readouterr().out)

    def test_every_command_described(self, capsys):
        data = self._describe(capsys)
        described = {c["name"] for c in data["commands"]}
        canonical = {canon for canon, _ in REGISTERED.values()}
        assert sorted(canonical - described) == []
        assert len(data["commands"]) == len(described)

    def test_command_from_parser(self, capsys):
        data = self._describe(capsys, "info")
        assert data["usage"] == "gc info [--show-bots] [--pretty] url"
        args = {a["name"]: a for a in data["arguments"]}
        assert args["url"]["required"] is True
        assert args["--show-bots"]["type"] == "boolean"

    def test_alias(self, capsys):
        assert self._describe(capsys, "label")["name"] == "vote"
