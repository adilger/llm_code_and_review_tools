"""Read-only configuration and account diagnostics; never print credentials."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import requests
from llm_tool_common.config import resolve_env_file

from ..client import GerritCommentsClient, GerritConfigError
from ..envelope import error_response_from_dict
from ..errors import ErrorCode
from ._helpers import output_success, output_result


def connection_check(offline=False):
    default = Path.home() / ".config" / "gerrit-cli" / ".env"
    try:
        config_file = resolve_env_file("gerrit-cli") or default
    except FileNotFoundError:
        config_file = Path(os.environ["GERRIT_CLI_ENV_FILE"])
    data = {"config_file": str(config_file.absolute()),
            "config_exists": config_file.is_file(), "authenticated": False}

    def result(status, message, code):
        return {**data, "status": status, "message": message}, code

    # The caller can open the correct file even before credentials exist.
    if offline:
        return result("unchecked", "Configuration location only; no network request made.", 0)
    try:
        client = GerritCommentsClient()
    except GerritConfigError:
        return result("unconfigured", "Set GERRIT_URL, GERRIT_USER and GERRIT_PASS in the Gerrit CLI configuration.", 2)
    try:
        parts = urlsplit(client.url)
    except ValueError:
        return result("unconfigured", "GERRIT_URL is not a valid server URL.", 4)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        return result("unconfigured", "GERRIT_URL must be an HTTP(S) server URL without credentials, query or fragment.", 4)
    if not client.authenticated:
        return result("unconfigured", "Set GERRIT_USER and GERRIT_PASS (Gerrit HTTP password).", 2)
    try:
        client.rest.kwargs["timeout"] = 10
        account = client.rest.get("/accounts/self")
        if not isinstance(account, dict) or not isinstance(account.get("_account_id"), int):
            return result("error", "Gerrit returned an unexpected account response.", 1)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (401, 403):
            return result("disconnected", "Gerrit rejected authentication. Check the username and HTTP password.", 2)
        return result("error", "Gerrit could not complete the account check.", 1)
    except (requests.ConnectionError, requests.Timeout):
        return result("unavailable", "Cannot reach Gerrit. Check the server address, network or VPN, then retry.", 5)
    except Exception:
        # Exception messages may include URLs, response bodies or credentials.
        return result("error", "Could not check the Gerrit account. Check the CLI installation and configuration.", 1)
    data["authenticated"] = True
    return result("connected", "Authentication verified. Publishing permissions depend on the target project.", 0)


def cmd_check(args):
    data, code = connection_check(offline=args.offline)
    if code:
        error_code = {2: ErrorCode.AUTH_FAILED, 4: ErrorCode.INVALID_INPUT,
                      5: ErrorCode.CONNECTION_ERROR}.get(code, ErrorCode.API_ERROR)
        output_result(error_response_from_dict(error_code, data["message"], "check", details=data), False)
        raise SystemExit(code)
    output_success(data, "check", False)
