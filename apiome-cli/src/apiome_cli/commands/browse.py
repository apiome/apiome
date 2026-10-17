"""``apiome browse open`` — open a published spec's page in the browse app (CLI 9.9, #3252).

The mirror of ``gh repo view --web``: one command from a terminal to the rendered spec page
(outline, diffs, lint). URL building and browse-host resolution live in
:mod:`apiome_cli.browse_url`; this module owns the flags and launching the browser.
"""

from __future__ import annotations

import os
import webbrowser
from typing import Optional

import typer

from apiome_cli import config as config_module
from apiome_cli.browse_url import BROWSE_URL_ENV, BrowseUrlError, build_browse_url, resolve_browse_base
from apiome_cli.cli_context import json_mode_from_context, settings_from_context
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json

app = typer.Typer(
    name="browse",
    help="Open published projects and versions in the browse app.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def browse_group(ctx: typer.Context) -> None:
    """Browse command group."""
    group_callback_without_subcommand(ctx)


def _launch(url: str, browser: str | None) -> bool:
    """Open *url* in the named browser, or the default one; return whether it launched.

    Raises:
        webbrowser.Error: When *browser* is not a browser :mod:`webbrowser` knows.
    """
    controller = webbrowser.get(browser) if browser else webbrowser.get()
    return bool(controller.open(url))


@app.command("open")
def browse_open(
    ctx: typer.Context,
    target: str = typer.Argument(
        ...,
        metavar="PATH",
        help=(
            "tenant, tenant/project, tenant/project/version, or a longer path such as "
            "'tenant/project/compare?v1=2.0.0&v2=2.1.0'. Start with / for a path from the "
            "browse root."
        ),
    ),
    print_url: bool = typer.Option(
        False, "--print-url", help="Print the URL instead of opening it (works without a display)."
    ),
    browser: Optional[str] = typer.Option(
        None, "--browser", help="Browser to use instead of the default (e.g. firefox, chrome, safari)."
    ),
) -> None:
    """Open a tenant, project or version page of the browse app in a web browser.

    The browse app's address is APIOME_BROWSE_URL, else url in the [browse] section of the
    config file, else derived from --base-url: an api. host becomes browse., and a local API
    maps to the browse dev server on port 3001.

    Exit codes: 0 opened (or printed); 2 bad PATH, no browse address, or an unknown --browser;
    1 the browser could not be launched (use --print-url).
    """
    settings = settings_from_context(ctx)
    try:
        base = resolve_browse_base(
            env_value=os.environ.get(BROWSE_URL_ENV),
            config_path=config_module.user_config_path(),
            api_base_url=settings.base_url_str,
        )
        url = build_browse_url(base, target)
    except BrowseUrlError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    if print_url:
        if json_mode_from_context(ctx):
            emit_json({"url": url, "opened": False})
        else:
            typer.echo(url)
        return

    try:
        opened = _launch(url, browser)
    except webbrowser.Error as exc:
        typer.echo(f"Unknown browser {browser!r}: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if not opened:
        typer.echo(f"Could not open a browser for {url}. Use --print-url to print it instead.", err=True)
        raise typer.Exit(EXIT_ERROR)
    if json_mode_from_context(ctx):
        emit_json({"url": url, "opened": True})
    else:
        typer.echo(f"→ Opening {url} …")
