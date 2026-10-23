"""``apiome login`` / ``apiome logout`` — browser-approved CLI sign-in (#5501).

``apiome login`` starts a login on apiome-rest (``POST /v1/cli/login``), shows a short code and
opens the approve page in the browser. The person signs in to Apiome there, checks the code and
approves for a workspace. Meanwhile the CLI polls ``POST /v1/cli/login/token``; once approved it
receives an API key for that workspace that lasts 14 days, and saves it — with the workspace — in
the user config file (``api_key``, ``tenant_id``), so every command that needs an API key works.

``apiome logout`` revokes that key on the server (``DELETE /v1/cli/login/key``) and removes it from
the config file. A permanent key copied from the API Keys page is left alone.

``APIOME_API_KEY`` in the environment still takes precedence over the saved key.
"""

from __future__ import annotations

import os
import platform
import time
import webbrowser
from typing import Any

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient
from apiome_cli.config import (
    API_KEY_ENV_VAR,
    load_settings,
    read_user_config_file,
    user_config_path,
    write_user_config_file,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.output import emit_json

#: Poll answers from apiome-rest (RFC 8628 error codes) in ``detail.error``.
_PENDING = "authorization_pending"
_SLOW_DOWN = "slow_down"
_DENIED = "access_denied"
_EXPIRED = "expired_token"

#: Seconds added to the poll interval on each ``slow_down`` (RFC 8628 §3.5).
_SLOW_DOWN_STEP = 5

#: Seams for tests.
_sleep = time.sleep
_monotonic = time.monotonic
_open_browser = webbrowser.open


def _client_name() -> str:
    """How this CLI names itself on the approve page, e.g. ``apiome-cli on build-box``."""
    host = platform.node().strip()
    return f"apiome-cli on {host}"[:255] if host else "apiome-cli"


def _poll_error(response: Any) -> str | None:
    """The RFC 8628 error code of a ``400`` poll answer, if it is one."""
    if response.status_code != 400:
        return None
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    return detail.get("error") if isinstance(detail, dict) else None


def _fail(message: str, code: int = EXIT_USAGE) -> None:
    """Print ``message`` on stderr and exit with ``code``."""
    typer.echo(message, err=True)
    raise typer.Exit(code)


def login(
    ctx: typer.Context,
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Print the approve link instead of opening a browser (for SSH sessions and containers).",
    ),
) -> None:
    """Sign the CLI in through the browser and save a 14-day API key.

    Approve the code in the browser, choose a workspace, and the key is saved to the config file.
    """
    settings = settings_from_context(ctx)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
        anonymous=True,
    )
    started = client.post(api_paths.cli_login(), json={"client_name": _client_name()}).json()
    user_code = started["user_code"]
    link = started["verification_uri_complete"]

    typer.echo(f"Your code: {user_code}", err=True)
    typer.echo(f"Approve this login at {link}", err=True)
    if not no_browser:
        try:
            opened = _open_browser(link)
        except Exception:  # noqa: BLE001 - no browser is not an error; the link is printed
            opened = False
        if not opened:
            typer.echo("Could not open a browser; open the link above yourself.", err=True)
    typer.echo("Waiting for approval… (Ctrl+C to cancel)", err=True)

    interval = max(1, int(started.get("interval", 5)))
    deadline = _monotonic() + int(started.get("expires_in", 600))
    issued: dict[str, Any] | None = None
    try:
        while _monotonic() < deadline:
            _sleep(interval)
            response = client.post_raw(api_paths.cli_login_token(), json={"device_code": started["device_code"]})
            if response.status_code == 200:
                issued = response.json()
                break
            error = _poll_error(response)
            if error == _PENDING:
                continue
            if error == _SLOW_DOWN:
                interval += _SLOW_DOWN_STEP
                continue
            if error == _DENIED:
                _fail("The login was denied in the browser. Nothing was saved.")
            if error == _EXPIRED:
                break
            if error is not None:
                _fail("The login can no longer be completed. Run `apiome login` again.")
            exit_on_api_error(response)
            _fail(f"Unexpected answer from Apiome (HTTP {response.status_code}).", EXIT_ERROR)
    except KeyboardInterrupt:
        _fail("Login cancelled. Nothing was saved.", 130)

    if issued is None:
        _fail("The login expired before it was approved. Run `apiome login` again.")

    stored = read_user_config_file()
    stored["base_url"] = settings.base_url_str
    stored["api_key"] = issued["api_key"]
    stored["tenant_id"] = issued["tenant_slug"]
    write_user_config_file(stored)

    if json_mode_from_context(ctx):
        emit_json(
            {
                "tenant_slug": issued["tenant_slug"],
                "tenant_name": issued["tenant_name"],
                "key_name": issued["key_name"],
                "key_prefix": issued["key_prefix"],
                "expires_at": issued["expires_at"],
                "config_path": str(user_config_path()),
            }
        )
    else:
        typer.echo(
            f"Signed in to {issued['tenant_name']} ({issued['tenant_slug']}). "
            f"The key expires {issued['expires_at']}; it is saved in {user_config_path()}."
        )
    if os.environ.get(API_KEY_ENV_VAR, "").strip():
        typer.echo(
            f"Note: {API_KEY_ENV_VAR} is set in your environment and is used instead of the saved key. "
            f"Unset it to use this login.",
            err=True,
        )


def logout(ctx: typer.Context) -> None:
    """Revoke the key `apiome login` saved and remove it from the config file.

    A key you saved yourself is kept; remove it with `apiome config unset api-key`.
    """
    settings = settings_from_context(ctx)
    stored = read_user_config_file()
    saved_key = str(stored.get("api_key") or "").strip()
    if not saved_key:
        typer.echo("Not signed in: no API key is saved in the config file.")
        return

    client = RestClient(
        load_settings(base_url=settings.base_url_str, api_key=saved_key),
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    response = client.delete_raw(api_paths.cli_login_key())
    if response.status_code == 409:
        _fail(
            "The saved API key was not created by `apiome login`, so it was not revoked. "
            "Revoke it on the API Keys page, or remove it here with `apiome config unset api-key`."
        )
    if response.status_code not in (204, 401):
        exit_on_api_error(response)
        _fail(f"Unexpected answer from Apiome (HTTP {response.status_code}).", EXIT_ERROR)

    stored.pop("api_key", None)
    write_user_config_file(stored)
    if response.status_code == 401:
        typer.echo("The saved key had already expired or been revoked; it was removed from the config file.")
    else:
        typer.echo("Signed out: the key was revoked and removed from the config file.")
