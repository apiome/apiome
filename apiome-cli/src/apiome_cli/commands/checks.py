"""The API change check suite from the command line — GNC-3.1 (#4740).

``apiome checks run --project pets --version 2.0.0 --commit $GITHUB_SHA`` evaluates the suite on
the server — lint, breaking changes, consumers, contract tests, SDK generation — records the one
verdict, reports it on the pull request when the version is bound to a repository ref, and exits
with the verdict: ``0`` pass or skipped, ``7`` failed, ``8`` pending. ``apiome checks show`` reads
the latest evaluation (or one by ``--run``) without evaluating anything.

Everything is decided server-side; this command shapes the request and renders the answer.
"""

from __future__ import annotations

from typing import Any, Optional

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.check_suite import (
    FORMATS,
    build_run_request,
    exit_code_for_state,
    format_text,
)
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context

app = typer.Typer(
    name="checks",
    help="Run and read the API change check suite (one verdict for a pull request).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def checks_group(ctx: typer.Context) -> None:
    """API change check suite command group."""
    group_callback_without_subcommand(ctx)


def _format(ctx: typer.Context, output_format: str) -> str:
    """Resolve the output format, letting the global ``--json`` win.

    :param ctx: The typer context.
    :param output_format: The ``--format`` value.
    :returns: One of :data:`FORMATS`.
    """
    fmt = (output_format or "text").strip().lower()
    if json_mode_from_context(ctx):
        return "json"
    if fmt not in FORMATS:
        raise typer.BadParameter("must be one of text, json, md", param_hint="--format")
    return fmt


def _emit(payload: dict[str, Any], *, fmt: str, subject: str) -> None:
    """Print an evaluation in the chosen format, and warn on stderr when it is stale.

    :param payload: The ``CheckSuiteRunDetail`` JSON.
    :param fmt: ``text``, ``json`` or ``md``.
    :param subject: How to name the version in text output.
    """
    if fmt == "json":
        emit_json(payload)
    elif fmt == "md":
        summary = str((payload.get("run") or {}).get("summary") or "")
        typer.echo(summary, nl=not summary.endswith("\n"))
    else:
        for line in format_text(payload, subject=subject):
            typer.echo(line)
    if payload.get("stale") and fmt != "text":
        typer.echo(
            "warning: this evaluation is stale — the draft or the policy has changed since.",
            err=True,
        )


@app.command("run")
def run_checks(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project slug or UUID."),
    version: str = typer.Option(..., "--version", help="Version label or revision UUID."),
    commit: Optional[str] = typer.Option(
        None,
        "--commit",
        help=(
            "Commit to report against (e.g. $GITHUB_SHA). Defaults to the commit the draft is "
            "synchronized with; only a version bound to a repository ref takes one."
        ),
    ),
    pr: Optional[int] = typer.Option(
        None, "--pr", min=1, help="Pull request number the commit belongs to."
    ),
    publish: bool = typer.Option(
        True,
        "--publish/--no-publish",
        help="Report the verdict on the pull request (on by default).",
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output: text (default), json (the API response), or md (the pull-request summary).",
    ),
) -> None:
    """Evaluate the API change check suite for a version (POST …/check-suite).

    Re-running over unchanged inputs returns the same evaluation — the same evidence ids — and
    does not report to the provider again. Exit codes: 0 pass or skipped, 7 failed, 8 pending,
    1 unreachable, 2 rejected (auth, unknown project/version/commit).
    """
    fmt = _format(ctx, output_format)
    client, tenant_slug = tenant_scoped_client(ctx)
    payload = client.post(
        api_paths.check_suite(tenant_slug, project, version),
        json=build_run_request(commit_sha=commit, pr_number=pr, publish=publish),
    ).json()
    _emit(payload, fmt=fmt, subject=f"{project}@{version}")
    raise typer.Exit(exit_code_for_state((payload.get("run") or {}).get("state")))


@app.command("show")
def show_checks(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project slug or UUID."),
    version: Optional[str] = typer.Option(
        None, "--version", help="Version label or revision UUID (the latest evaluation of it)."
    ),
    run: Optional[str] = typer.Option(
        None, "--run", help="One evaluation by id — the drill-down a pull request links to."
    ),
    commit: Optional[str] = typer.Option(
        None, "--commit", help="Only the latest evaluation at this commit (with --version)."
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        help="Output: text (default), json (the API response), or md (the pull-request summary).",
    ),
) -> None:
    """Read an API change check suite evaluation without evaluating anything.

    Exits with the evaluation's verdict, like ``checks run``. A stale evaluation (the draft or the
    policy moved since) is reported on stderr — run the suite again for a current answer.
    """
    if bool(version) == bool(run):
        raise typer.BadParameter("give exactly one of --version or --run", param_hint="--version")
    if run and commit:
        raise typer.BadParameter("--commit narrows --version, not --run", param_hint="--commit")
    fmt = _format(ctx, output_format)
    client, tenant_slug = tenant_scoped_client(ctx)
    if run:
        path = api_paths.check_suite_run(tenant_slug, project, run)
        subject = f"{project} evaluation {run}"
    else:
        path = api_paths.check_suite(tenant_slug, project, str(version))
        if commit:
            path = f"{path}?commit_sha={commit.strip()}"
        subject = f"{project}@{version}"
    payload = client.get(path).json()
    _emit(payload, fmt=fmt, subject=subject)
    raise typer.Exit(exit_code_for_state((payload.get("run") or {}).get("state")))
