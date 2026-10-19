"""Tests for tracked hashtags and topics: hashtag/topic mode
(resolve_search_anchor, cmd_graph) and stats.focus."""

import argparse
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from gerrit_cli.graph.build import (
    BuildContext,
    _assemble_payload,
    _make_edge,
    resolve_search_anchor,
)
from gerrit_cli.graph.nodes import _make_node


class _Rest:
    """/changes/?q= answers `search`; /related answers per change."""

    def __init__(self, search: list[dict[str, Any]], related: dict[int, list[int]]):
        self.search, self.related = search, related
        self.calls: list[str] = []

    def get(self, path: str):
        self.calls.append(path)
        if "/related" in path:
            cn = int(path.split("/changes/")[1].split("/")[0])
            return {"changes": [{"_change_number": c, "status": "NEW"}
                                for c in self.related.get(cn, [])]}
        return self.search


def _ch(cn, status="NEW", hashtags=(), topic="", updated="2026-10-01", branch="master"):
    return {"_number": cn, "status": status, "hashtags": list(hashtags), "topic": topic,
            "updated": updated, "submitted": updated, "branch": branch}


class TestResolveSearchAnchor:
    def test_the_change_among_most_tagged_and_fewest_others(self):
        tag = ["prio"]
        search = [_ch(1, hashtags=tag, updated="2026-10-09"),
                  _ch(2, hashtags=tag), _ch(3, hashtags=tag), _ch(4, hashtags=tag)]
        rest = _Rest(search, {
            # 1: newest, but one tagged change among many others
            1: [1, 100, 101, 102, 103, 104],
            # 2 and 3: two tagged each, 3 with fewer others
            2: [2, 3, 200, 201],
            3: [2, 3, 300],
        })
        assert resolve_search_anchor(SimpleNamespace(rest=rest), "hashtag", "prio") == 3
        assert 'hashtag:"prio" branch:master' in rest.calls[0].replace("%22", '"')

    def test_every_candidate_is_probed(self):
        """Ticket mode probes the 8 newest; the tagged cluster can be
        anywhere."""
        search = [_ch(c, hashtags=["prio"], updated=f"2026-10-{30 - c:02d}") for c in range(1, 13)]
        rest = _Rest(search, {12: [12, 11, 10]})
        assert resolve_search_anchor(SimpleNamespace(rest=rest), "hashtag", "prio") == 12

    def test_topic(self):
        search = [_ch(1, topic="ec2"), _ch(2, topic="ec2-other"), _ch(3, topic="ec2")]
        rest = _Rest(search, {1: [1], 3: [1, 3]})
        assert resolve_search_anchor(SimpleNamespace(rest=rest), "topic", "ec2") == 3

    def test_results_are_rechecked(self):
        """The query is trusted for neither the branch nor the tag."""
        search = [_ch(1, hashtags=["prio"], branch="b2_15"), _ch(2, hashtags=["other"]),
                  _ch(3, hashtags=["prio"])]
        rest = _Rest(search, {1: [1, 3, 5, 6], 2: [2, 3, 7]})
        assert resolve_search_anchor(SimpleNamespace(rest=rest), "hashtag", "prio") == 3

    def test_nothing_in_flight_takes_the_newest_merged(self):
        search = [_ch(1, "MERGED", ["prio"], updated="2026-09-01"),
                  _ch(2, "MERGED", ["prio"], updated="2026-10-01"),
                  _ch(3, "ABANDONED", ["prio"], updated="2026-10-05")]
        rest = _Rest(search, {})
        assert resolve_search_anchor(SimpleNamespace(rest=rest), "hashtag", "prio") == 2

    def test_no_change_carries_it(self):
        rest = _Rest([_ch(1, hashtags=["other"])], {})
        with pytest.raises(ValueError, match="hashtag prio"):
            resolve_search_anchor(SimpleNamespace(rest=rest), "hashtag", "prio")


class TestCmdGraphModes:
    def _run(self, url, **extra):
        from gerrit_cli.cli import cmd_graph
        args = argparse.Namespace(url=url, pretty=False, no_open=True, output="/dev/null",
                                  include_hashtag="", include_topic="", ticket="",
                                  name=None, branch=None, skip_topic=False,
                                  skip_hashtag=False)
        for k, v in extra.items():
            setattr(args, k, v)
        with patch('gerrit_cli.cli.GerritCommentsClient') as client, \
             patch('gerrit_cli.graph.resolve_search_anchor', return_value=42) as resolve, \
             patch('gerrit_cli.graph.build_graph', return_value={
                 "stats": {}, "anchor": 42, "merged_trunk": [7, 8]}) as build, \
             patch('gerrit_cli.graph.generate_html', return_value="") as html, \
             patch('gerrit_cli.graph.save_and_open', return_value="/dev/null"):
            client.return_value.url = "https://gerrit.invalid/"
            client.parse_gerrit_url.return_value = ("https://gerrit.invalid", 61965)
            cmd_graph(args)
        self.anchor = html.call_args.args[0]["anchor"]
        return resolve, build.call_args

    @pytest.mark.parametrize("url", ["hashtag:218_review_priority", "#218_review_priority"])
    def test_hashtag_mode(self, url):
        resolve, call = self._run(url)
        assert resolve.call_args.args[1:] == ("hashtag", "218_review_priority")
        assert call.args[1] == 42
        kw = call.kwargs
        assert kw["extra_hashtags"] == ["218_review_priority"] and kw["extra_topics"] == []
        # the anchor's other hashtags and topic would pull in its other series
        assert kw["include_hashtag"] is False and kw["include_topic"] is False
        assert kw["name"] == "#218_review_priority"
        assert kw["focus_on_by_default"] is True
        # the page centres on the oldest merged change, not the picked one
        assert self.anchor == 7

    def test_topic_mode_keeps_extras_and_name(self):
        resolve, call = self._run("topic:ec2", include_hashtag="pt_ecro,ec2x",
                                  name="EC", branch="b2_15")
        assert resolve.call_args.args[1:] == ("topic", "ec2")
        assert resolve.call_args.kwargs["branch"] == "b2_15"
        kw = call.kwargs
        assert kw["extra_topics"] == ["ec2"] and kw["extra_hashtags"] == ["pt_ecro", "ec2x"]
        assert kw["name"] == "EC"

    def test_ticket_mode_with_hashtags_opens_on_all_changes(self):
        with patch('gerrit_cli.graph.resolve_ticket_anchor', return_value=42) as ticket:
            resolve, call = self._run("LU-18222", include_hashtag="prio", include_topic="ec2")
        assert ticket.call_count == 1 and resolve.call_count == 0
        kw = call.kwargs
        assert kw["extra_hashtags"] == ["prio"] and kw["extra_topics"] == ["ec2"]
        assert kw["focus_on_by_default"] is False
        assert self.anchor == 42

    def test_a_hashtag_no_change_carries_is_an_error(self, capsys):
        from gerrit_cli.cli import cmd_graph
        args = argparse.Namespace(url="hashtag:nobody", pretty=False, no_open=True,
                                  output="/dev/null", include_hashtag="", include_topic="",
                                  ticket="", name=None, branch=None, skip_topic=False,
                                  skip_hashtag=False)
        with patch('gerrit_cli.cli.GerritCommentsClient'), \
             patch('gerrit_cli.graph.resolve_search_anchor',
                   side_effect=ValueError("no changes on branch master with hashtag nobody")), \
             patch('gerrit_cli.graph.build_graph') as build, \
             pytest.raises(SystemExit) as exc:
            cmd_graph(args)
        assert exc.value.code != 0 and build.call_count == 0
        assert "with hashtag nobody" in json.loads(capsys.readouterr().out)["message"]

    def test_a_change_number_is_not_a_mode(self):
        resolve, call = self._run("61965", include_hashtag="pt_ecro")
        assert resolve.call_count == 0
        kw = call.kwargs
        assert kw["include_hashtag"] is True and kw["extra_hashtags"] == ["pt_ecro"]
        assert kw["focus_on_by_default"] is False
        assert self.anchor == 42


def _ctx(extra_hashtags=(), extra_topics=()):
    ctx = BuildContext(
        client=SimpleNamespace(rest=_Rest([], {})), change_number=1,
        base_url="https://gerrit.invalid", progress=False, fetch_details=False,
        fetch_comments=False, include_topic=True, include_hashtag=True,
        extra_topics=list(extra_topics), extra_hashtags=list(extra_hashtags),
        extra_tickets=[],
    )
    specs = [
        (1, "NEW", ["prio", "pt_ecro"], ""),   # anchor, tracked
        (2, "NEW", [], "ec2"),                 # in its series, untracked unless topic ec2
        (3, "MERGED", ["prio"], ""),
        (4, "ABANDONED", ["prio"], ""),
        (5, "NEW", ["other"], ""),
        (6, "NEW", ["prio"], ""),              # unrelated parent: counted nowhere
    ]
    for cn, status, hashtags, topic in specs:
        n = _make_node(cn, f"LU-1 change {cn}", status, 1, "A", ctx.base_url,
                       topic=topic, hashtags=hashtags)
        n["current_commit"] = f"c{cn}"
        n["created"] = "2026-01-01 00:00:00.000000000"
        if status == "MERGED":
            n["submitted"] = "2026-02-01 00:00:00.000000000"
        ctx.nodes[cn] = n
    ctx.nodes[6]["unrelated_parent"] = True
    ctx.edges += [_make_edge(1, 1, 1, 2, 1, 1), _make_edge(1, 1, 1, 5, 1, 1),
                  _make_edge(6, 1, 1, 1, 1, 1)]
    return ctx


class TestFocusStats:
    def test_counts_the_changes_carrying_what_was_asked_for(self):
        stats = _assemble_payload(_ctx(extra_hashtags=["prio"]))["stats"]
        focus = stats["focus"]
        assert focus["hashtags"] == ["prio"] and focus["topics"] == []
        assert focus["on_by_default"] is False
        assert focus["node_count"] == 3
        assert focus["status_counts"] == {"NEW": 1, "MERGED": 1, "ABANDONED": 1}
        s = focus["summary"]
        assert (s["patches"], s["open"], s["merged"], s["abandoned"]) == (3, 1, 1, 1)
        # the whole graph is counted as before
        assert stats["status_counts"] == {"NEW": 3, "MERGED": 1, "ABANDONED": 1}
        assert stats["summary"]["patches"] == 5

    def test_on_by_default_is_recorded(self):
        ctx = _ctx(extra_hashtags=["prio"])
        ctx.focus_on_by_default = True
        assert _assemble_payload(ctx)["stats"]["focus"]["on_by_default"] is True

    def test_hashtags_and_topics_add_up(self):
        focus = _assemble_payload(_ctx(["prio"], ["ec2"]))["stats"]["focus"]
        assert focus["topics"] == ["ec2"] and focus["node_count"] == 4

    def test_asked_but_carried_by_none(self):
        """Zeros and the nulls stats.summary already has for nothing
        merged or open."""
        focus = _assemble_payload(_ctx(extra_hashtags=["nobody"]))["stats"]["focus"]
        assert (focus["node_count"], focus["status_counts"]) == (0, {})
        s = focus["summary"]
        assert (s["patches"], s["oldest_open"], s["time_to_merge"]["median"]) == (0, None, None)

    def test_nothing_asked_for_means_no_focus(self):
        """The anchor's own hashtags are expanded but not tracked."""
        stats = _assemble_payload(_ctx())["stats"]
        assert "focus" not in stats
