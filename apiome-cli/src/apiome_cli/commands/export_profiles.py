"""``apiome export profiles …``, ``export deliver`` and ``export deliveries`` (MFX-38.4).

A delivery profile saves a destination for finished exports — a git repository, a webhook or an
S3-compatible bucket — once per workspace, by name. ``export <format> … --deliver PROFILE`` delivers a
new export with it on completion; ``export deliver JOB --profile PROFILE`` delivers a finished one;
``export deliveries JOB`` lists a job's deliveries across every channel.

A webhook profile's signing secret is read from an environment variable (``--secret-env``), never from
the command line, so it never lands in shell history or a process list.
"""

from __future__ import annotations

import os
from typing import Any

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import export_delivery_profiles as profiles_api
from apiome_cli.client.browse_scope import resolve_tenant_slug
from apiome_cli.client.http import RestClient
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import ListColumn, emit_json, emit_list_table
from apiome_cli.terminal import confirm_action

app = typer.Typer(
    name="profiles",
    help="List, create, change and delete the workspace's export delivery profiles (git, webhook, "
    "object storage).",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_CHANNEL_HELP = "git, webhook or object_storage."

_PROFILE_COLUMNS: list[ListColumn] = [
    ("Name", "name", None),
    ("Channel", "channel", None),
    ("Destination", "destination", lambda value: _destination_summary(value)),
    ("Credential", "credentialRef", lambda value: _credential_summary(value)),
    ("ID", "id", None),
]

_DELIVERY_COLUMNS: list[ListColumn] = [
    ("Started", "startedAt", None),
    ("Channel", "channel", None),
    ("Outcome", "outcome", None),
    ("Status", "status", None),
    ("Profile", "profileName", None),
    ("Destination", "destination", None),
    ("Attempts", "attemptCount", None),
    ("Error", "errorCode", None),
]


@app.callback(invoke_without_command=True)
def profiles_group(ctx: typer.Context) -> None:
    """Export delivery profile commands."""
    group_callback_without_subcommand(ctx)


def _client(ctx: typer.Context) -> tuple[RestClient, str]:
    """An authenticated client and the tenant slug."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, timeout=timeout_from_context(ctx), verify=not insecure_from_context(ctx))
    return client, resolve_tenant_slug(settings, client, tenant_override=None)


def _destination_summary(destination: Any) -> str:
    """One cell for a profile's destination."""
    if not isinstance(destination, dict):
        return ""
    if "repositoryId" in destination:
        return f"{destination.get('repositoryId')}:{destination.get('targetPath') or '/'} ({destination.get('mode')})"
    if "url" in destination:
        return str(destination.get("url"))
    prefix = destination.get("prefix")
    return f"{destination.get('bucket')}/{prefix}" if prefix else str(destination.get("bucket"))


def _credential_summary(ref: Any) -> str:
    """One cell for a profile's credential reference."""
    if not isinstance(ref, dict):
        return ""
    return str(ref.get("kind")) + (f" {ref['id']}" if ref.get("id") else "")


def _read_secret(env_name: str | None) -> str | None:
    """The webhook secret from the named environment variable (``None`` when no name was given)."""
    if env_name is None:
        return None
    secret = os.environ.get(env_name.strip())
    if not secret:
        typer.echo(f"Environment variable {env_name} is not set; export the webhook secret into it.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return secret


def _emit_profile(ctx: typer.Context, profile: dict[str, Any], verb: str) -> None:
    """Print a profile: JSON in ``--json`` mode, else one confirmation line."""
    if json_mode_from_context(ctx):
        emit_json(profile)
        return
    typer.echo(f"{verb} {profile.get('channel')} profile {profile.get('name')!r} "
               f"({profile.get('id')}): {_destination_summary(profile.get('destination'))}")


def emit_deliveries(ctx: typer.Context, rows: list[dict[str, Any]]) -> None:
    """Print delivery attempts as JSON or a table."""
    if json_mode_from_context(ctx):
        emit_json({"deliveries": rows})
        return
    emit_list_table(rows, _DELIVERY_COLUMNS, empty_message="No deliveries.", min_width=160)


@app.command("list", help="List the workspace's delivery profiles.")
def list_profiles(
    ctx: typer.Context,
    channel: str | None = typer.Option(None, "--channel", help=f"Only one channel: {_CHANNEL_HELP}"),
) -> None:
    """List delivery profiles."""
    client, tenant = _client(ctx)
    rows = profiles_api.list_profiles(client, tenant, channel=channel)
    if json_mode_from_context(ctx):
        emit_json({"profiles": rows})
        return
    emit_list_table(rows, _PROFILE_COLUMNS, empty_message="No delivery profiles.", min_width=160)


@app.command("show", help="Show one delivery profile (by name or id). Never shows a secret.")
def show_profile(ctx: typer.Context, profile: str = typer.Argument(..., help="Profile name or id.")) -> None:
    """Show one delivery profile."""
    client, tenant = _client(ctx)
    row = profiles_api.get_profile(client, tenant, profiles_api.resolve_profile_id(client, tenant, profile))
    if json_mode_from_context(ctx):
        emit_json(row)
        return
    for label, value in (("Name", row.get("name")), ("ID", row.get("id")), ("Channel", row.get("channel")),
                         ("Description", row.get("description")),
                         ("Destination", _destination_summary(row.get("destination"))),
                         ("Credential", _credential_summary(row.get("credentialRef"))),
                         ("Updated", row.get("updatedAt"))):
        if value:
            typer.echo(f"{label}: {value}")


@app.command(
    "create",
    help="Create a delivery profile. git: --repository [--path --base-branch --mode]. webhook: --url "
    "--secret-env VAR [--artifact]. object_storage: --credential --bucket [--prefix --partitioning].",
)
def create_profile(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="A name unique in the workspace."),
    channel: str = typer.Option(..., "--channel", help=_CHANNEL_HELP),
    description: str | None = typer.Option(None, "--description", help="What the profile is for."),
    repository: str | None = typer.Option(None, "--repository", help="git: the registered repository id."),
    path: str | None = typer.Option(None, "--path", help="git: the directory the bundle is written under."),
    base_branch: str | None = typer.Option(None, "--base-branch", help="git: the base branch (default: the "
                                           "repository's default)."),
    mode: str | None = typer.Option(None, "--mode", help="git: pr (default) or commit."),
    url: str | None = typer.Option(None, "--url", help="webhook: the receiver URL."),
    secret_env: str | None = typer.Option(None, "--secret-env", metavar="VAR",
                                          help="webhook: the environment variable holding the signing secret."),
    artifact: str | None = typer.Option(None, "--artifact", help="webhook: auto (default) or fetch."),
    credential: str | None = typer.Option(None, "--credential", help="object_storage: the storage credential id."),
    bucket: str | None = typer.Option(None, "--bucket", help="object_storage: the bucket."),
    prefix: str | None = typer.Option(None, "--prefix", help="object_storage: the key prefix."),
    partitioning: str | None = typer.Option(None, "--partitioning", metavar="PART,…",
                                            help="object_storage: artifact,version,target in order ('' for none)."),
) -> None:
    """Create one delivery profile."""
    block = profiles_api.build_destination(
        channel, repository=repository, path=path, base_branch=base_branch, mode=mode, url=url,
        secret=_read_secret(secret_env), artifact=artifact, credential=credential, bucket=bucket, prefix=prefix,
        partitioning=partitioning,
    )
    body: dict[str, Any] = {"name": name, "channel": channel, **(block or {})}
    if description is not None:
        body["description"] = description
    client, tenant = _client(ctx)
    _emit_profile(ctx, profiles_api.create_profile(client, tenant, body), "Created")


@app.command(
    "update",
    help="Change a profile's name, description or destination. Destination flags replace the whole "
    "destination; the channel never changes. A webhook keeps its secret unless --secret-env is given.",
)
def update_profile(
    ctx: typer.Context,
    profile: str = typer.Argument(..., help="Profile name or id."),
    name: str | None = typer.Option(None, "--name", help="A new name."),
    description: str | None = typer.Option(None, "--description", help="A new description ('' clears it)."),
    repository: str | None = typer.Option(None, "--repository"),
    path: str | None = typer.Option(None, "--path"),
    base_branch: str | None = typer.Option(None, "--base-branch"),
    mode: str | None = typer.Option(None, "--mode"),
    url: str | None = typer.Option(None, "--url"),
    secret_env: str | None = typer.Option(None, "--secret-env", metavar="VAR"),
    artifact: str | None = typer.Option(None, "--artifact"),
    credential: str | None = typer.Option(None, "--credential"),
    bucket: str | None = typer.Option(None, "--bucket"),
    prefix: str | None = typer.Option(None, "--prefix"),
    partitioning: str | None = typer.Option(None, "--partitioning", metavar="PART,…"),
) -> None:
    """Change one delivery profile."""
    client, tenant = _client(ctx)
    profile_id = profiles_api.resolve_profile_id(client, tenant, profile)
    current = profiles_api.get_profile(client, tenant, profile_id)
    secret = _read_secret(secret_env)
    block = profiles_api.build_destination(
        str(current.get("channel")), repository=repository, path=path, base_branch=base_branch, mode=mode,
        url=url, secret=secret, artifact=artifact, credential=credential, bucket=bucket, prefix=prefix,
        partitioning=partitioning, require=False,
    )
    if block and current.get("channel") == "webhook" and url is None:
        typer.echo("Give --url with the other webhook flags: a destination is replaced whole.", err=True)
        raise typer.Exit(EXIT_USAGE)
    body: dict[str, Any] = {**(block or {})}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if not body:
        typer.echo("Nothing to change: give --name, --description or destination flags.", err=True)
        raise typer.Exit(EXIT_USAGE)
    _emit_profile(ctx, profiles_api.update_profile(client, tenant, profile_id, body), "Updated")


@app.command("delete", help="Delete a delivery profile. Its past deliveries keep their record.")
def delete_profile(
    ctx: typer.Context,
    profile: str = typer.Argument(..., help="Profile name or id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Delete one delivery profile."""
    client, tenant = _client(ctx)
    profile_id = profiles_api.resolve_profile_id(client, tenant, profile)
    confirm_action(f"Delete delivery profile {profile!r}?", skip=yes)
    profiles_api.delete_profile(client, tenant, profile_id)
    if json_mode_from_context(ctx):
        emit_json({"deleted": profile_id})
    else:
        typer.echo(f"Deleted delivery profile {profile!r}.")


@app.command("deliveries", help="List every delivery made with a profile, across export jobs.")
def list_profile_deliveries(ctx: typer.Context, profile: str = typer.Argument(..., help="Profile name or id.")) -> None:
    """A profile's delivery trail."""
    client, tenant = _client(ctx)
    emit_deliveries(ctx, profiles_api.profile_deliveries(client, tenant,
                                                         profiles_api.resolve_profile_id(client, tenant, profile)))


def deliver(
    ctx: typer.Context,
    job_id: str = typer.Argument(..., help="A completed export job's id."),
    profile: list[str] = typer.Option(..., "--profile", help="Profile name or id (repeatable)."),
) -> None:
    """Deliver a completed export job with one or more delivery profiles; exit 1 when any failed."""
    client, tenant = _client(ctx)
    ids = [profiles_api.resolve_profile_id(client, tenant, ref) for ref in profile]
    attempts = [profiles_api.deliver_job(client, tenant, job_id, profile_id) for profile_id in ids]
    if json_mode_from_context(ctx):
        emit_json({"deliveries": attempts})
    else:
        for attempt in attempts:
            line = (f"{attempt.get('outcome')}: {attempt.get('channel')} delivery with "
                    f"{attempt.get('profileName')!r} to {attempt.get('destination')} ({attempt.get('status')})")
            if attempt.get("errorCode"):
                line += f" — {attempt.get('errorCode')}: {attempt.get('errorMessage')}"
            typer.echo(line)
    if any(attempt.get("outcome") == "failed" for attempt in attempts):
        raise typer.Exit(EXIT_ERROR)


def deliveries(ctx: typer.Context, job_id: str = typer.Argument(..., help="An export job's id.")) -> None:
    """List every delivery of an export job, across git, webhook and object storage."""
    client, tenant = _client(ctx)
    emit_deliveries(ctx, profiles_api.job_deliveries(client, tenant, job_id))
