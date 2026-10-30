"""Private changes are left out unless the host opts in (GD_SHOW_PRIVATE).

The credentials can read the private changes of the board's user, but any
visitor can open the board, so by default no private change may reach a
bundle, snapshot or persisted watchlist."""

from types import SimpleNamespace

import pytest

from conftest import ME, mk_bundle, mk_change

from gerrit_dashboard.app import create_app
from gerrit_dashboard.classify import build_snapshot
from gerrit_dashboard.config import Config
from gerrit_dashboard.fetcher import GerritFetcher
from gerrit_dashboard.store import user_store


def private(**kw):
    c = mk_change(**kw)
    c["is_private"] = True
    return c


def fetcher(tmp_path, show_private=False):
    cfg = Config()
    cfg.data_dir = tmp_path
    cfg.show_private = show_private
    store = user_store(tmp_path, "mvef")
    f = GerritFetcher(cfg, store, target="mvef")
    f.whoami = lambda: dict(ME)
    f._client = lambda: SimpleNamespace(username="mvef")
    f.fetch_next_queues = lambda: {}
    f.enrich_threads = lambda *a, **k: {}
    return f, store


class TestConfig:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("GD_SHOW_PRIVATE", raising=False)
        assert Config.from_env().show_private is False

    def test_env_turns_it_on(self, monkeypatch):
        monkeypatch.setenv("GD_SHOW_PRIVATE", "1")
        assert Config.from_env().show_private is True


class TestFetch:
    def test_every_query_excludes_private_changes(self, tmp_path):
        f, _ = fetcher(tmp_path)
        queries = []
        f.query_all = lambda q, options=None: queries.append(q) or []
        f.fetch_bundle()
        assert queries
        for q in queries:
            assert q.endswith(" -is:private"), q

    def test_opted_in_queries_are_unfiltered(self, tmp_path):
        f, _ = fetcher(tmp_path, show_private=True)
        queries = []
        f.query_all = lambda q, options=None: queries.append(q) or []
        f.fetch_bundle()
        assert queries and not any("is:private" in q for q in queries)

    def test_project_and_private_clauses_combine(self, tmp_path):
        f, _ = fetcher(tmp_path)
        f.config.projects = ["fs/lustre-release"]
        assert f._scope_clause() == " project:fs/lustre-release -is:private"

    def test_reviewed_private_change_is_dropped(self, tmp_path):
        # Whatever the query returns, a private change never survives.
        f, _ = fetcher(tmp_path)
        f.query_all = lambda q, options=None: (
            [private(number=70231, owner={"_account_id": 117})]
            if q.startswith("reviewer:") else [])
        bundle = f.fetch_bundle()
        assert 70231 not in bundle["changes"] and 70231 not in bundle["roles"]

    def test_watched_private_change_reads_like_an_absent_one(self, tmp_path):
        outcomes = []
        for kind in ("private", "absent"):
            f, store = fetcher(tmp_path / kind)
            f.query_all = lambda q, options=None: []
            f.fetch_change_status = lambda n, kind=kind: (
                (private(number=n), "ok") if kind == "private" else (None, "missing"))
            store.watchlist_add("70231")
            bundle = f.fetch_bundle()
            outcomes.append((bundle["errors"], store.load_watchlist(),
                             70231 in bundle["changes"]))
        assert outcomes[0] == outcomes[1]
        assert outcomes[0][0] == ["watchlist change 70231 is not available here — removed"]

    @pytest.mark.parametrize("role_query", ["owner:", "reviewer:", "cc:"])
    def test_opted_in_keeps_private_changes_in_every_role(self, tmp_path, role_query):
        f, store = fetcher(tmp_path, show_private=True)
        f.query_all = lambda q, options=None: (
            [private(number=70231)] if q.startswith(role_query) and "wip" not in q else [])
        f.fetch_change_status = lambda n: (private(number=n), "ok")
        store.watchlist_add("70236")
        bundle = f.fetch_bundle()
        assert {70231, 70236} <= set(bundle["changes"])
        assert [e["number"] for e in store.load_watchlist()] == [70236]


class TestSnapshot:
    def test_loader_rejects_a_snapshot_built_under_the_other_setting(self, tmp_path):
        cfg = Config(); cfg.data_dir = tmp_path
        store = user_store(tmp_path, "mvef")
        b = mk_bundle([(mk_change(number=101), {"mine"})])

        cfg.show_private = True
        store.save_snapshot(build_snapshot(b, cfg))
        assert store.load_snapshot(show_private=True) is not None
        assert store.load_snapshot() is None

        cfg.show_private = False
        store.save_snapshot(build_snapshot(b, cfg))
        assert store.load_snapshot() is not None
        assert store.load_snapshot(show_private=True) is None

    @pytest.mark.parametrize("template", ["dashboard.html", "classic/dashboard.html"])
    def test_shown_private_change_is_marked(self, tmp_path, template):
        from flask import render_template
        cfg = Config(); cfg.data_dir = tmp_path; cfg.show_private = True
        snap = build_snapshot(mk_bundle([(private(number=1), {"review"}),
                                         (mk_change(number=2), {"mine"})]), cfg)
        app = create_app(cfg, start_refresher=False)
        with app.test_request_context():
            html = render_template(template, snapshot=snap, refreshing=False, error=None,
                                   form_error="", static_mode=True, gerrit_url="https://x",
                                   user="alex")
        assert html.count('title="Private change:') == 1
