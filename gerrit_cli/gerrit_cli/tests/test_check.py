"""Account diagnostics never publish or reveal authentication material."""

import json
from unittest.mock import MagicMock

import pytest
import requests

from gerrit_cli.commands import check
from gerrit_cli.cli import build_parser


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(check, "resolve_env_file", lambda _: tmp_path / "custom.env")
    value = MagicMock(url="https://review.example.test", authenticated=True)
    value.rest.kwargs = {}
    value.rest.get.return_value = {"_account_id": 123, "name": "private name", "email": "private@example.test"}
    monkeypatch.setattr(check, "GerritCommentsClient", lambda: value)
    return value


def test_read_only_authenticated_check(client):
    data, code = check.connection_check()
    assert code == 0 and data["authenticated"] and data["status"] == "connected"
    client.rest.get.assert_called_once_with("/accounts/self")
    client.rest.post.assert_not_called()
    assert "private name" not in json.dumps(data)
    assert "private@example.test" not in json.dumps(data)
    assert client.rest.kwargs["timeout"] == 10


def test_offline_and_missing_credentials_do_not_contact_server(client):
    data, code = check.connection_check(offline=True)
    assert code == 0 and data["status"] == "unchecked"
    client.authenticated = False
    data, code = check.connection_check()
    assert code == 2 and data["status"] == "unconfigured"
    client.rest.get.assert_not_called()


@pytest.mark.parametrize("failure,status,code", [
    (requests.Timeout("secret timeout"), "unavailable", 5),
    (requests.ConnectionError("secret connection"), "unavailable", 5),
    (ValueError("secret HTML"), "error", 1),
])
def test_failures_are_sanitized(client, failure, status, code):
    client.rest.get.side_effect = failure
    data, actual = check.connection_check()
    assert actual == code and data["status"] == status
    assert "secret" not in json.dumps(data)


@pytest.mark.parametrize("http_code", [401, 403, 500])
def test_http_failure(client, http_code):
    response = requests.Response()
    response.status_code = http_code
    client.rest.get.side_effect = requests.HTTPError("secret response", response=response)
    data, code = check.connection_check()
    assert code == (2 if http_code in (401, 403) else 1)
    assert not data["authenticated"] and "secret" not in json.dumps(data)


def test_missing_explicit_config_keeps_its_path(monkeypatch, tmp_path):
    target = tmp_path / "missing.env"
    monkeypatch.setenv("GERRIT_CLI_ENV_FILE", str(target))
    monkeypatch.setattr(check, "resolve_env_file", lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    data, code = check.connection_check(offline=True)
    assert data["config_file"] == str(target) and not data["config_exists"]


def test_cli_failure_obeys_error_envelope(client, monkeypatch, capsys):
    from gerrit_cli import cli
    client.authenticated = False
    for envelope in (False, True):
        monkeypatch.setattr(cli, "FULL_ENVELOPE", envelope)
        args = build_parser().parse_args(["check"])
        with pytest.raises(SystemExit) as exc:
            args.func(args)
        assert exc.value.code == 2
        payload = json.loads(capsys.readouterr().out)
        diagnostic = payload["error"] if envelope else payload
        assert diagnostic["details"]["status"] == "unconfigured"
        if envelope:
            assert payload["ok"] is False


def test_url_credentials_rejected(client):
    client.url = "https://user:secret@review.example.test"
    data, code = check.connection_check()
    assert code == 4 and "secret" not in json.dumps(data)
    client.rest.get.assert_not_called()
