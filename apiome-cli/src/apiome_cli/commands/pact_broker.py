"""The ``pact-broker``-compatible commands of ``apiome pact`` — PFX-4.1 (#6938).

``publish``, ``check`` (PFX-8.4, #7301: a pre-publish comparison with several provider versions; no
``pact-broker`` equivalent), ``list-pacticipants``, ``describe-version``, ``can-i-deploy``, ``record-deployment``,
``record-release``, ``create-environment``, ``create-webhook``, ``verify``, and
``create-or-update-pacticipant`` / ``delete-pacticipant`` (PFX-8.10, #7307) and
``create-version-tag`` / ``delete-version`` / ``restore-version`` (PFX-8.11, #7308) take the flags of
the ``pact-broker`` CLI they replace (``-a``, ``-e``, ``-l``, ``-t``, ``-b``, ``-k``, ``-o``, …)
and print the same sentences, so a pipeline moves over by changing the command name. ``migrate``
(PFX-6.7, #6959) imports a whole Pact Broker or PactFlow workspace: the source is read by
:mod:`apiome_cli.client.pact_migration_source` and turned into import records by
:mod:`apiome_cli.pact_migration_plan`. They are registered on the ``pact`` group in :mod:`apiome_cli.commands.pact`, which also gives the
whole group ``pact-broker``'s exit codes: ``0`` success, ``1`` any failure.

Each command is a thin shell: request building lives in
:mod:`apiome_cli.client.pact_broker_requests`, the address and credential in
:mod:`apiome_cli.client.pact_broker_connection`, and the human output in
:mod:`apiome_cli.pact_broker_output`. The server enforces tenant isolation and the ``pacts``
permissions; a refusal (401 / 403 / 404 / 409 / 422) prints the server's message and exits 1.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

import typer

from apiome_cli.cli_context import insecure_from_context
from apiome_cli.client.errors import CliError, exit_on_api_error
from apiome_cli.client.pact_broker_connection import BrokerConnection, connect, segment
from apiome_cli.client.pact_broker_requests import (
    WEBHOOK_EVENTS,
    CanIDeployQuery,
    build_check_body,
    build_environment_body,
    build_publish_bodies,
    build_verify_body,
    build_webhook_body,
    collect_pact_paths,
    deployable,
    detect_version_properties,
    embedded_environments,
    parse_check_selectors,
    parse_context,
    parse_selectors,
    read_pact_file,
)
from apiome_cli.client.pact_migration_source import DEFAULT_MATRIX_LIMIT, SourceBroker, fetch_document, read_source
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.pact_broker_output import (
    can_i_deploy_lines,
    check_lines,
    environment_created_lines,
    native_version_document,
    pacticipant_deleted_lines,
    pacticipant_lines,
    pacticipant_saved_lines,
    publish_lines,
    recorded_lines,
    validate_output,
    verify_lines,
    version_deleted_lines,
    version_lines,
    version_restored_lines,
    version_tagged_lines,
    webhook_created_lines,
)
from apiome_cli.pact_migration_output import MigrationSummary, migration_document, migration_lines
from apiome_cli.pact_migration_plan import DEFAULT_BATCH_BYTES, DONE_OUTCOMES, KINDS, MigrationState, Plan, batches

# ---------------------------------------------------------------------------------------------
# Options shared by every command
# ---------------------------------------------------------------------------------------------

BROKER_BASE_URL = typer.Option(
    None,
    "--broker-base-url",
    "-b",
    help="Broker base URL, https://<api>/v1/tenants/<tenant>/pact-broker (overrides PACT_BROKER_BASE_URL).",
)
BROKER_TOKEN = typer.Option(
    None,
    "--broker-token",
    "-k",
    help="Workspace API key (overrides PACT_BROKER_TOKEN). Prefer the variable: argv is visible to others.",
)
OUTPUT = typer.Option("table", "--output", "-o", help="table, json or markdown.")

#: Page size for ``list-pacticipants`` (the route's maximum).
_PAGE_SIZE = 200


def _format(ctx: typer.Context, output: str) -> str:
    """The output format: ``json`` under the root ``--json``, else ``--output`` checked."""
    if json_mode_from_context(ctx):
        return "json"
    try:
        return validate_output(output)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--output") from exc


def _emit(fmt: str, payload: Any, lines: list[str]) -> None:
    """Print the response as JSON, or its lines."""
    if fmt == "json":
        emit_json(payload)
        return
    for line in lines:
        typer.echo(line)


def _bad(exc: ValueError, hint: str) -> typer.BadParameter:
    """A usage error from a request builder's :class:`ValueError`."""
    return typer.BadParameter(str(exc), param_hint=hint)


def _query(params: list[tuple[str, str]]) -> str:
    """``?a=1&b=2`` with ``[]`` left readable, or ``''`` without parameters."""
    return "?" + urlencode(params, safe="[]") if params else ""


def _environment_uuid(conn: BrokerConnection, name: str) -> str:
    """The UUID of the environment named ``name``, or a :class:`CliError` saying how to create it."""
    document = conn.client.get(conn.broker_path("/environments" + _query([("name", name)]))).json()
    for environment in embedded_environments(document):
        if environment.get("name") == name and environment.get("uuid"):
            return str(environment["uuid"])
    raise CliError(
        f"No environment named {name!r} in this workspace. Create it with: "
        f"apiome pact create-environment --name {name}",
        exit_code=EXIT_ERROR,
    )


# ---------------------------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------------------------


def publish(
    ctx: typer.Context,
    pacts: list[Path] = typer.Argument(..., help="Pact files, or directories of *.json pact files."),
    consumer_app_version: Optional[str] = typer.Option(
        None, "--consumer-app-version", "-a", help="The consumer build's version (a commit SHA is best)."
    ),
    branch: Optional[str] = typer.Option(None, "--branch", help="The branch the build came from."),
    auto_detect: bool = typer.Option(
        False,
        "--auto-detect-version-properties",
        "-r",
        help="Read the branch and build URL from the CI environment (GitHub, GitLab, Jenkins, …) or git.",
    ),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="Tag the consumer version (repeatable)."),
    tag_with_git_branch: bool = typer.Option(
        False, "--tag-with-git-branch", "-g", help="Also tag the version with the detected branch."
    ),
    build_url: Optional[str] = typer.Option(None, "--build-url", help="http(s) URL of the CI build."),
    merge: bool = typer.Option(False, "--merge", help="Not supported: refused with the reason."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Publish pacts for a consumer version (POST …/contracts/publish), as `pact-broker publish`.

    Reads every pact first and refuses the run before anything is sent when a file is not a pact.
    Sends one request per consumer (at most 100 pacts each), records the branch, tags and build URL,
    and prints the broker's notices — including the bi-directional comparisons a publish runs.
    Exits 1 on any refusal (409 when that version already published a different pact).
    """
    fmt = _format(ctx, output)
    if merge:
        raise typer.BadParameter(
            "Apiome stores a consumer version's pact as published and does not merge interactions; "
            "publish the complete pact (a different pact for the same version is refused with 409)",
            param_hint="--merge",
        )
    if auto_detect or tag_with_git_branch:
        detected = detect_version_properties(os.environ)
        branch = branch or detected.branch
        build_url = build_url or (detected.build_url if auto_detect else None)
        if tag_with_git_branch:
            if not detected.branch:
                raise typer.BadParameter("no branch could be detected from the CI environment or git", param_hint="-g")
            tag = [*(tag or []), detected.branch]
    if not consumer_app_version:
        raise typer.BadParameter("give the consumer version", param_hint="--consumer-app-version")
    try:
        files = [read_pact_file(path) for path in collect_pact_paths(pacts)]
        bodies = build_publish_bodies(
            files, consumer_app_version=consumer_app_version, branch=branch, tags=tag, build_url=build_url
        )
    except ValueError as exc:
        raise _bad(exc, "PACTS") from exc

    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    responses = [conn.client.post(conn.broker_path("/contracts/publish"), json=body).json() for body in bodies]
    _emit(fmt, responses[0] if len(responses) == 1 else responses, publish_lines(responses, fmt))


# ---------------------------------------------------------------------------------------------
# check (PFX-8.4, #7301)
# ---------------------------------------------------------------------------------------------


def check(
    ctx: typer.Context,
    pacts: list[Path] = typer.Argument(..., help="Pact files, or directories of *.json pact files."),
    against: list[str] = typer.Option(
        ...,
        "--against",
        help=(
            "A provider version to compare with (repeatable, at most 10): main, deployed:<environment>, "
            "version:<number> or draft:<revision>."
        ),
    ),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Check pacts against several provider versions before publishing (POST …/pacts/check). Publishes nothing.

    Each pact is compared with the provider contract of every version --against names: the newest
    on the provider's main branch (main), what is deployed to or released in an environment
    (deployed:production), a named version (version:2.7.0), or a revision of the provider's Apiome
    project as it stands (draft:latest). Prints one row per provider version with the verdict a
    publish would record, then every interaction that differs or is not in the spec, and every
    selector that named nothing. Exits 0 when every pact passes against every version and every
    selector named one; 1 otherwise, as pact-broker does.
    """
    fmt = _format(ctx, output)
    try:
        selectors = parse_check_selectors(against)
    except ValueError as exc:
        raise _bad(exc, "--against") from exc
    try:
        files = [read_pact_file(path) for path in collect_pact_paths(pacts)]
    except ValueError as exc:
        raise _bad(exc, "PACTS") from exc

    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    checks: list[dict[str, Any]] = []
    for pact in files:
        answer = conn.client.post(conn.broker_path("/pacts/check"), json=build_check_body(pact, selectors)).json()
        checks.append({"file": str(pact.path), **answer})
    success = all((check.get("summary") or {}).get("success") for check in checks)
    _emit(fmt, {"checks": checks, "success": success}, check_lines(checks, fmt))
    raise typer.Exit(EXIT_SUCCESS if success else EXIT_ERROR)


# ---------------------------------------------------------------------------------------------
# list-pacticipants / describe-version
# ---------------------------------------------------------------------------------------------


def list_pacticipants(
    ctx: typer.Context,
    label: Optional[str] = typer.Option(None, "--label", help="Only pacticipants with this label."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """List the workspace's pacticipants (GET /v1/tenants/{t}/pacticipants, every page).

    Prints name, handle, main branch, repository and labels. JSON output is
    `{"pacticipants": [...], "count": N}` over all pages.
    """
    fmt = _format(ctx, output)
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    records: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        params: list[tuple[str, str]] = [("limit", str(_PAGE_SIZE))]
        if label:
            params.append(("label", label))
        if cursor:
            params.append(("cursor", cursor))
        page = conn.client.get(conn.api_path("/pacticipants" + _query(params), command="list-pacticipants")).json()
        records += [item for item in page.get("pacticipants") or [] if isinstance(item, dict)]
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            break
    _emit(fmt, {"pacticipants": records, "count": len(records)}, pacticipant_lines(records, fmt))


def describe_version(
    ctx: typer.Context,
    pacticipant: str = typer.Option(..., "--pacticipant", "-a", help="The pacticipant's name or handle."),
    version: Optional[str] = typer.Option(None, "--version", "-e", help="The version number."),
    latest: bool = typer.Option(False, "--latest", "-l", help="The latest version (the default without -e)."),
    tag: Optional[str] = typer.Option(None, "--tag", help="With --latest: the latest version with this tag."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Describe a pacticipant version: number, branches, tags, build URL, creation time.

    With --version it reads GET …/pact-broker/pacticipants/{p}/versions/{v}; otherwise the latest
    recorded version (with --tag, the latest carrying that tag). Exits 1 when there is none.
    """
    fmt = _format(ctx, output)
    if version is not None and (latest or tag):
        raise typer.BadParameter("give --version, or --latest [--tag], not both", param_hint="--version")
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    if version is not None:
        path = conn.broker_path(f"/pacticipants/{segment(pacticipant)}/versions/{segment(version)}")
        document = conn.client.get(path).json()
    else:
        params = [("limit", "1")] + ([("tag", tag)] if tag else [])
        path = conn.api_path(
            f"/pacticipants/{segment(pacticipant)}/versions" + _query(params), command="describe-version --latest"
        )
        versions = [item for item in conn.client.get(path).json().get("versions") or [] if isinstance(item, dict)]
        if not versions:
            which = f" with tag {tag!r}" if tag else ""
            raise CliError(f"{pacticipant} has no version{which}", exit_code=EXIT_ERROR)
        document = native_version_document(versions[0])
    _emit(fmt, document, version_lines(document, pacticipant, fmt))


# ---------------------------------------------------------------------------------------------
# create-or-update-pacticipant / delete-pacticipant (PFX-8.10, #7307)
# ---------------------------------------------------------------------------------------------

#: The refusal code of a delete while a version is deployed or released.
_VERSION_IN_USE = "pacticipant-version-in-use"


def _refusal(response: Any) -> tuple[str, str]:
    """``(code, message)`` of a REST refusal; empty strings when the body carries neither."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return "", ""
    if isinstance(detail, dict):
        return str(detail.get("code") or ""), str(detail.get("message") or "")
    return "", str(detail or "")


def create_or_update_pacticipant(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="The pacticipant's name, as pacts use it."),
    display_name: Optional[str] = typer.Option(None, "--display-name", help="What people read, when it differs."),
    main_branch: Optional[str] = typer.Option(None, "--main-branch", help="The branch 'latest on main' reads."),
    repository_url: Optional[str] = typer.Option(None, "--repository-url", help="http(s) URL of its repository."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Create a pacticipant, or update the one with this name, as `pact-broker create-or-update-pacticipant`.

    Reads GET /v1/tenants/{t}/pacticipants/{name} (a name it had before a rename finds it too). When
    there is none it registers one (POST …/pacticipants); otherwise it sends only the flags given
    (PATCH …/pacticipants/{handle}) and never renames: rename from the pacticipant's Settings tab.
    Exits 1 on any refusal, with the server's reason.
    """
    fmt = _format(ctx, output)
    changes = {
        key: value
        for key, value in (
            ("display_name", display_name),
            ("main_branch", main_branch),
            ("repository_url", repository_url),
        )
        if value is not None
    }
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    command = "create-or-update-pacticipant"
    existing = conn.client.get_raw(conn.api_path(f"/pacticipants/{segment(name)}", command=command))
    if existing.status_code == 404:
        created = conn.client.post(conn.api_path("/pacticipants", command=command), json={"name": name, **changes})
        record, was_created = created.json(), True
    else:
        exit_on_api_error(existing)
        record, was_created = existing.json(), False
        if changes:
            path = conn.api_path(f"/pacticipants/{segment(str(record.get('slug') or name))}", command=command)
            updated = conn.client.patch_raw(path, json=changes)
            exit_on_api_error(updated)
            record = updated.json()
    _emit(fmt, record, pacticipant_saved_lines(record, created=was_created, changed=bool(changes), fmt=fmt))


def delete_pacticipant(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="The pacticipant's name or handle."),
    reason: Optional[str] = typer.Option(None, "--reason", help="Why; stored with the delete and audited."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Delete a pacticipant with its versions, pacts and results (DELETE /v1/tenants/{t}/pacticipants/{name}).

    The delete is soft: it can be undone from the Pacticipants page (or POST …/pacticipants/{name}/restore)
    until it is purged. Refused while one of its versions is deployed or released: record the
    undeployment first. Needs pacts:delete. Exits 1 on any refusal.
    """
    fmt = _format(ctx, output)
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    path = conn.api_path(f"/pacticipants/{segment(name)}", command="delete-pacticipant")
    response = conn.client.delete_raw(path, params={"reason": reason} if reason else None)
    if response.status_code == 409:
        code, message = _refusal(response)
        if code == _VERSION_IN_USE:
            # The REST message also names `force=true`, which this command deliberately does not offer.
            first = message.split(". Record")[0].rstrip(".")
            raise CliError(f"{first}. Record the undeployment first.", exit_code=EXIT_ERROR)
    exit_on_api_error(response)
    _emit(fmt, {"name": name, "deleted": True}, pacticipant_deleted_lines(name, fmt))


# ---------------------------------------------------------------------------------------------
# create-version-tag / delete-version / restore-version (PFX-8.11, #7308)
# ---------------------------------------------------------------------------------------------


def _version_path(conn: BrokerConnection, pacticipant: str, version: str, suffix: str, *, command: str) -> str:
    """``/v1/tenants/{t}/pacticipants/{p}/versions/{v}{suffix}``, refusing a number REST cannot address.

    Args:
        conn: The connection.
        pacticipant: The pacticipant's name or handle.
        version: The version number, exactly as recorded.
        suffix: What follows the version segment (``''``, ``/restore``, ``/tags/{tag}``).
        command: The command asking, named in a refusal.

    Returns:
        The path.

    Raises:
        typer.BadParameter: for an empty number, or one with a ``/`` (it is a path segment).
    """
    if not version.strip():
        raise typer.BadParameter("give the version number", param_hint="--version")
    if "/" in version:
        raise typer.BadParameter(
            "a version number with a '/' cannot be addressed: it is one path segment", param_hint="--version"
        )
    return conn.api_path(f"/pacticipants/{segment(pacticipant)}/versions/{segment(version)}{suffix}", command=command)


def create_version_tag(
    ctx: typer.Context,
    pacticipant: str = typer.Option(..., "--pacticipant", "-a", help="The pacticipant's name or handle."),
    version: str = typer.Option(..., "--version", "-e", help="The version number to tag."),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="The tag (repeatable)."),
    auto_create_version: bool = typer.Option(
        False, "--auto-create-version", help="Record the version first when it does not exist yet."
    ),
    tag_with_git_branch: bool = typer.Option(
        False, "--tag-with-git-branch", "-g", help="Also tag the version with the detected git branch."
    ),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Tag a pacticipant version (PUT /v1/tenants/{t}/pacticipants/{p}/versions/{v}/tags/{tag}), as `pact-broker create-version-tag`.

    Sends one request per tag; a tag the version already has changes nothing. Without
    --auto-create-version an unknown version is refused (404). Needs pacts:create. Exits 1 on any
    refusal, after naming the tags that were added before it.
    """
    fmt = _format(ctx, output)
    tags = [value for value in (tag or []) if value.strip()]
    if tag_with_git_branch:
        detected = detect_version_properties(os.environ)
        if not detected.branch:
            raise typer.BadParameter("no branch could be detected from the CI environment or git", param_hint="-g")
        tags.append(detected.branch)
    if not tags:
        raise typer.BadParameter("give at least one tag", param_hint="--tag")
    command = "create-version-tag"
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    base = _version_path(conn, pacticipant, version, "", command=command)
    if auto_create_version:
        exit_on_api_error(conn.client.put_raw(base, json={}))
    record: dict[str, Any] = {}
    added: list[str] = []
    for name in dict.fromkeys(tags):
        response = conn.client.put_raw(f"{base}/tags/{quote(name, safe='/')}")
        if response.status_code >= 400 and added:
            typer.echo(f"Tagged with {', '.join(added)} before the refusal.", err=True)
        exit_on_api_error(response)
        record = response.json()
        added.append(name)
    _emit(fmt, record, version_tagged_lines(pacticipant, version, added, fmt))


def delete_version(
    ctx: typer.Context,
    pacticipant: str = typer.Option(..., "--pacticipant", "-a", help="The pacticipant's name or handle."),
    version: str = typer.Option(..., "--version", "-e", help="The version number to delete."),
    reason: Optional[str] = typer.Option(None, "--reason", help="Why; stored with the delete and audited."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Delete a pacticipant version with its pacts and results (DELETE …/pacticipants/{p}/versions/{v}).

    The delete is soft: restore-version (or the Versions tab's Restore) brings the version, its
    pacts and results back until it is purged. Refused while the version is deployed or released:
    record the undeployment first. Needs pacts:delete. Exits 1 on any refusal.
    """
    fmt = _format(ctx, output)
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    path = _version_path(conn, pacticipant, version, "", command="delete-version")
    response = conn.client.delete_raw(path, params={"reason": reason} if reason else None)
    if response.status_code == 409:
        code, message = _refusal(response)
        if code == _VERSION_IN_USE:
            # The REST message also names `force=true`, which this command deliberately does not offer.
            first = message.split(". Record")[0].rstrip(".")
            raise CliError(f"{first}. Record the undeployment first.", exit_code=EXIT_ERROR)
    exit_on_api_error(response)
    payload = {"pacticipant": pacticipant, "version": version, "deleted": True}
    _emit(fmt, payload, version_deleted_lines(pacticipant, version, fmt))


def restore_version(
    ctx: typer.Context,
    pacticipant: str = typer.Option(..., "--pacticipant", "-a", help="The pacticipant's name or handle."),
    version: str = typer.Option(..., "--version", "-e", help="The deleted version's number."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Restore a deleted version with its pacts, results and deployments (POST …/versions/{v}/restore).

    Works until the version is purged. Refused (409) when the version is not deleted, or when a
    live version has taken the number since. Needs pacts:delete. Exits 1 on any refusal.
    """
    fmt = _format(ctx, output)
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    path = _version_path(conn, pacticipant, version, "/restore", command="restore-version")
    record = conn.client.post(path).json()
    _emit(fmt, record, version_restored_lines(pacticipant, record, fmt))


# ---------------------------------------------------------------------------------------------
# can-i-deploy
# ---------------------------------------------------------------------------------------------


def can_i_deploy(
    ctx: typer.Context,
    pacticipant: list[str] = typer.Option(..., "--pacticipant", "-a", help="The pacticipant being deployed."),
    version: Optional[str] = typer.Option(None, "--version", "-e", help="Its version."),
    latest: bool = typer.Option(False, "--latest", "-l", help="Its latest version (with --tag: the latest tagged)."),
    tag: Optional[str] = typer.Option(None, "--tag", help="With --latest: the tag of the version."),
    branch: Optional[str] = typer.Option(None, "--branch", help="The latest version from this branch."),
    main_branch: bool = typer.Option(False, "--main-branch", help="The latest version from its main branch."),
    to_environment: Optional[str] = typer.Option(
        None, "--to-environment", help="The environment it is deployed to."
    ),
    to: Optional[str] = typer.Option(None, "--to", help="The tag it is deployed to (legacy; prefer environments)."),
    ignore: Optional[list[str]] = typer.Option(
        None, "--ignore", help="Leave this pacticipant out of the verdict (repeatable)."
    ),
    retry_while_unknown: int = typer.Option(
        0, "--retry-while-unknown", min=0, help="Retry this many times while a verification result is missing."
    ),
    retry_interval: float = typer.Option(10, "--retry-interval", min=0, help="Seconds between retries."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the verdict but always exit 0."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Can this version be deployed? (GET …/matrix, as `pact-broker can-i-deploy` asks it.)

    Prints the matrix rows, pact-broker's "Computer says yes" or "Computer says no" verdict, the
    reason and the notices. Exits 0 when deployable, 1 when not or when a result is still missing after the
    retries; --dry-run always exits 0.
    """
    fmt = _format(ctx, output)
    if len(pacticipant) != 1:
        raise typer.BadParameter(
            "name one pacticipant; check several by running can-i-deploy once for each", param_hint="--pacticipant"
        )
    query = CanIDeployQuery(
        pacticipant=pacticipant[0],
        version=version,
        latest=latest,
        tag=tag,
        branch=branch,
        main_branch=main_branch,
        to_environment=to_environment,
        to=to,
        ignore=tuple(ignore or ()),
    )
    try:
        query.validate()
    except ValueError as exc:
        raise _bad(exc, "--version / --latest / --branch / --main-branch") from exc

    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    path = conn.broker_path("/matrix" + _query(query.matrix_params()))
    document = conn.client.get(path).json()
    retries = 0
    while deployable(document) is None and retries < retry_while_unknown:
        retries += 1
        time.sleep(retry_interval)
        document = conn.client.get(path).json()
    verdict = deployable(document)
    _emit(fmt, document, can_i_deploy_lines(document, fmt, dry_run=dry_run, retries=retries))
    raise typer.Exit(EXIT_SUCCESS if dry_run or verdict is True else EXIT_ERROR)


# ---------------------------------------------------------------------------------------------
# record-deployment / record-release
# ---------------------------------------------------------------------------------------------


def _record(
    ctx: typer.Context,
    *,
    kind: str,
    pacticipant: str,
    version: str,
    environment: str,
    application_instance: Optional[str],
    output: str,
    broker_base_url: Optional[str],
    broker_token: Optional[str],
) -> None:
    """Record a deployment or a release of a version to an environment (looked up by name)."""
    fmt = _format(ctx, output)
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    uuid = _environment_uuid(conn, environment)
    collection = "deployed-versions" if kind == "deployment" else "released-versions"
    path = conn.broker_path(
        f"/pacticipants/{segment(pacticipant)}/versions/{segment(version)}/{collection}/environment/{segment(uuid)}"
    )
    body = {"applicationInstance": application_instance} if application_instance else {}
    document = conn.client.post(path, json=body).json()
    lines = recorded_lines(
        kind,
        pacticipant=pacticipant,
        version=version,
        environment=environment,
        application_instance=application_instance,
    )
    _emit(fmt, document, lines)


def record_deployment(
    ctx: typer.Context,
    pacticipant: str = typer.Option(..., "--pacticipant", "-a", help="What was deployed."),
    version: str = typer.Option(..., "--version", "-e", help="Its version."),
    environment: str = typer.Option(..., "--environment", help="The environment's name."),
    application_instance: Optional[str] = typer.Option(
        None, "--application-instance", "--target", help="The instance deployed to (a region, a customer)."
    ),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Record that a version is deployed to an environment (POST …/deployed-versions/environment/{uuid}).

    The environment is looked up by name; an unknown name exits 1 with the command that creates it.
    A deployment replaces the version previously deployed to the same environment and instance.
    """
    _record(
        ctx,
        kind="deployment",
        pacticipant=pacticipant,
        version=version,
        environment=environment,
        application_instance=application_instance,
        output=output,
        broker_base_url=broker_base_url,
        broker_token=broker_token,
    )


def record_release(
    ctx: typer.Context,
    pacticipant: str = typer.Option(..., "--pacticipant", "-a", help="What was released."),
    version: str = typer.Option(..., "--version", "-e", help="Its version."),
    environment: str = typer.Option(..., "--environment", help="The environment's name."),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Record that a version is released to an environment (POST …/released-versions/environment/{uuid}).

    Unlike a deployment, a release keeps earlier released versions supported until their support
    ends. An unknown environment name exits 1 with the command that creates it.
    """
    _record(
        ctx,
        kind="release",
        pacticipant=pacticipant,
        version=version,
        environment=environment,
        application_instance=None,
        output=output,
        broker_base_url=broker_base_url,
        broker_token=broker_token,
    )


# ---------------------------------------------------------------------------------------------
# create-environment
# ---------------------------------------------------------------------------------------------


def create_environment(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="The name tooling uses: one word, no spaces."),
    display_name: Optional[str] = typer.Option(None, "--display-name", help="The name people read."),
    production: bool = typer.Option(False, "--production", help="It is a production environment."),
    contract_required: bool = typer.Option(
        False, "--contract-required", help="Apiome: can-i-deploy refuses a pacticipant that has no contract."
    ),
    contact_name: Optional[str] = typer.Option(None, "--contact-name", help="A contact for the environment."),
    contact_email_address: Optional[str] = typer.Option(
        None, "--contact-email-address", help="That contact's email address."
    ),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Create an environment (POST …/environments) and print its UUID.

    Exits 1 when the name is taken (409) or the caller may not create environments (403).
    """
    fmt = _format(ctx, output)
    try:
        body = build_environment_body(
            name=name,
            display_name=display_name,
            production=production,
            contract_required=contract_required,
            contact_name=contact_name,
            contact_email_address=contact_email_address,
        )
    except ValueError as exc:
        raise _bad(exc, "--name / --contact-*") from exc
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    document = conn.client.post(conn.broker_path("/environments"), json=body).json()
    _emit(fmt, document, environment_created_lines(document))


# ---------------------------------------------------------------------------------------------
# create-webhook
# ---------------------------------------------------------------------------------------------


def create_webhook(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="The URL the webhook calls."),
    request: str = typer.Option("POST", "--request", "-X", help="The method: POST, PUT or PATCH."),
    header: Optional[list[str]] = typer.Option(None, "--header", "-H", help="'Name: value' (repeatable)."),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="The body; @file reads it from a file."),
    user: Optional[str] = typer.Option(
        None, "--user", "-u", help="'username:password' for basic auth (stored sealed)."
    ),
    consumer: Optional[str] = typer.Option(None, "--consumer", help="Only pacts of this consumer."),
    provider: Optional[str] = typer.Option(None, "--provider", help="Only pacts of this provider."),
    description: Optional[str] = typer.Option(None, "--description", help="What the webhook is for."),
    contract_content_changed: bool = typer.Option(False, "--contract-content-changed"),
    contract_published: bool = typer.Option(False, "--contract-published"),
    contract_requiring_verification_published: bool = typer.Option(
        False, "--contract-requiring-verification-published"
    ),
    provider_verification_published: bool = typer.Option(False, "--provider-verification-published"),
    provider_verification_succeeded: bool = typer.Option(False, "--provider-verification-succeeded"),
    provider_verification_failed: bool = typer.Option(False, "--provider-verification-failed"),
    consumer_version_branch_created: bool = typer.Option(False, "--consumer-version-branch-created"),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Create a webhook (POST …/webhooks), with `pact-broker create-webhook`'s options.

    Choose at least one event flag (--contract-content-changed, --contract-published,
    --contract-requiring-verification-published, --provider-verification-published,
    --provider-verification-succeeded, --provider-verification-failed,
    --consumer-version-branch-created). The password is stored sealed and never printed. Exits 1
    when the broker refuses the webhook (a private host, an unknown pacticipant).
    """
    fmt = _format(ctx, output)
    chosen = dict(
        contract_content_changed=contract_content_changed,
        contract_published=contract_published,
        contract_requiring_verification_published=contract_requiring_verification_published,
        provider_verification_published=provider_verification_published,
        provider_verification_succeeded=provider_verification_succeeded,
        provider_verification_failed=provider_verification_failed,
        consumer_version_branch_created=consumer_version_branch_created,
    )
    try:
        body = build_webhook_body(
            url=url,
            method=request,
            headers=header or [],
            data=data,
            user=user,
            consumer=consumer,
            provider=provider,
            description=description,
            events=[name for name in WEBHOOK_EVENTS if chosen[name]],
        )
    except ValueError as exc:
        raise _bad(exc, "create-webhook") from exc
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    document = conn.client.post(conn.broker_path("/webhooks"), json=body).json()
    _emit(fmt, document, webhook_created_lines(document))


# ---------------------------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------------------------


def verify(
    ctx: typer.Context,
    provider: str = typer.Option(..., "--provider", help="The provider's name or handle."),
    provider_app_version: str = typer.Option(
        ..., "--provider-app-version", "-a", help="The provider build's version (a commit SHA is best)."
    ),
    target: str = typer.Option(..., "--target", help="The registered verification target to replay against."),
    branch: Optional[str] = typer.Option(None, "--branch", help="The provider build's branch."),
    build_url: Optional[str] = typer.Option(None, "--build-url", help="http(s) URL of the CI build."),
    consumer_version_selector: Optional[list[str]] = typer.Option(
        None, "--consumer-version-selector", help='A selector as JSON, e.g. \'{"mainBranch": true}\' (repeatable).'
    ),
    include_pending: bool = typer.Option(
        False, "--enable-pending", help="A pending pact's failure does not fail the run."
    ),
    include_wip_pacts_since: Optional[str] = typer.Option(
        None, "--include-wip-pacts-since", help="Also verify work-in-progress pacts published since this date."
    ),
    allow_mutating: bool = typer.Option(
        False, "--allow-mutating", help="Replay POST/PUT/PATCH/DELETE interactions (the target must allow them)."
    ),
    replay_without_state_setup: bool = typer.Option(
        False, "--replay-without-state-setup", help="Replay interactions whose provider state nothing sets up."
    ),
    provider_states_setup_url: Optional[str] = typer.Option(
        None,
        "--provider-states-setup-url",
        help="POST each provider state to this endpoint (a path on the target or an http(s) URL) instead of the registry.",
    ),
    skip_already_verified: bool = typer.Option(
        False,
        "--skip-already-verified",
        help="Skip pacts that already have a result for this provider version.",
    ),
    publish_results: bool = typer.Option(
        True, "--publish-verification-results/--no-publish-verification-results", help="Publish the results."
    ),
    context: Optional[list[str]] = typer.Option(
        None, "--context", help="Non-secret CI context KEY=VALUE stored with the evidence (repeatable)."
    ),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Verify a provider against its pacts with Apiome's hosted verifier (POST …/pact-verifier/…/verify).

    Selects the pacts the provider must honour, replays each interaction against the registered
    target and publishes a result per conclusive pact. Prints one row per pact and every interaction
    that could not be replayed, with its reason, every pact skipped as already verified, and why the
    target could not be reached. Exits 0 when the run succeeded, 1 otherwise (a failed pact, an
    incomplete run, a target that could not be reached, or no pacts selected). A production target
    never receives mutating requests: --allow-mutating against one is refused.
    """
    fmt = _format(ctx, output)
    try:
        body = build_verify_body(
            target=target,
            provider_app_version=provider_app_version,
            branch=branch,
            build_url=build_url,
            selectors=parse_selectors(consumer_version_selector or []),
            include_pending=include_pending,
            include_wip_pacts_since=include_wip_pacts_since,
            allow_mutating=allow_mutating,
            replay_without_state_setup=replay_without_state_setup,
            publish=publish_results,
            context=parse_context(context or []),
            provider_states_setup_url=provider_states_setup_url,
            skip_already_verified=skip_already_verified,
        )
    except ValueError as exc:
        raise _bad(exc, "--consumer-version-selector / --context / --provider-states-setup-url") from exc
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    path = conn.api_path(f"/pact-verifier/pacts/provider/{segment(provider)}/verify", command="verify")
    response = conn.client.post(path, json=body).json()
    _emit(fmt, response, verify_lines(response, fmt))
    raise typer.Exit(EXIT_SUCCESS if response.get("success") is True else EXIT_ERROR)


# ---------------------------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------------------------


#: Where ``migrate`` keeps its progress unless ``--state`` says otherwise.
DEFAULT_STATE_FILE = "apiome-pact-migrate.state.json"


def _ready(
    broker: SourceBroker,
    pending: list[tuple[str, dict[str, Any]]],
    to_fetch: dict[str, str],
    summary: MigrationSummary,
    plan: Plan,
) -> Any:
    """Yield the pending records of one kind, each pact or result document read just before it is sent.

    A document the source no longer returns is counted as refused, with the reason, and not sent.
    """
    for key, record in pending:
        if record["kind"] in ("pact", "verification") and key in to_fetch:
            problem = fetch_document(broker, record, to_fetch[key], plan)
            if problem:
                summary.refuse(record["kind"], key, "source-unreadable", problem)
                continue
        yield key, record


def migrate(
    ctx: typer.Context,
    source: Optional[str] = typer.Option(
        None,
        "--from",
        help="The source Pact Broker or PactFlow base URL, e.g. https://acme.pactflow.io.",
    ),
    token: Optional[str] = typer.Option(
        None,
        "--token",
        envvar="PACT_SOURCE_BROKER_TOKEN",
        help="A read token for the source (or PACT_SOURCE_BROKER_TOKEN; prefer the variable: argv is visible).",
    ),
    username: Optional[str] = typer.Option(
        None,
        "--username",
        envvar="PACT_SOURCE_BROKER_USERNAME",
        help="Basic-auth user of an open-source source broker.",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        envvar="PACT_SOURCE_BROKER_PASSWORD",
        help="Basic-auth password (prefer the variable).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Read the source and check every record against Apiome; write nothing.",
    ),
    state: Path = typer.Option(
        Path(DEFAULT_STATE_FILE),
        "--state",
        help="Where progress is kept, so a second run resumes.",
    ),
    restart: bool = typer.Option(
        False,
        "--restart",
        help="Ignore the progress kept in --state and send everything.",
    ),
    matrix_limit: int = typer.Option(
        DEFAULT_MATRIX_LIMIT,
        "--matrix-limit",
        min=1,
        help="Matrix rows read per integration (pacts and results).",
    ),
    batch_bytes: int = typer.Option(
        DEFAULT_BATCH_BYTES,
        "--batch-bytes",
        min=1024,
        help="About how many bytes of records one request carries.",
    ),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Migrate a Pact Broker or PactFlow workspace into Apiome (POST …/pact-migration/import).

    Reads the source through its REST API — pacticipants and labels, versions with branches and tags,
    pacts, verification results, environments, current deployments and releases, webhooks — and
    re-creates them in the workspace -b/-k (or PACT_BROKER_BASE_URL/TOKEN) names, keeping the source's
    timestamps. Importing again changes nothing, so a run can be repeated; progress is kept in --state,
    so a second run skips what the first imported. --dry-run checks every record and writes nothing.

    The report lists everything not portable (PactFlow secrets, which are never exported, are listed
    for re-entry; webhooks with redacted credentials are imported disabled) and every refused record
    with its reason. Exits 0 when every record was imported (or, with --dry-run, would be); 1 otherwise.
    """
    fmt = _format(ctx, output)
    if not source:
        raise typer.BadParameter(
            "give the source broker's base URL", param_hint="--from"
        )
    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    tenant = conn.tenant(command="migrate")
    plan = Plan()
    summary = MigrationSummary(dry_run=dry_run)
    route = conn.api_path(
        "/pact-migration/" + ("check" if dry_run else "import"), command="migrate"
    )

    with SourceBroker(
        source,
        token=token,
        username=username,
        password=password,
        verify=not insecure_from_context(ctx),
    ) as broker:
        try:
            progress = MigrationState.load(
                state, source=broker.base_url, target=tenant, restart=restart
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--state") from exc
        to_fetch = read_source(
            broker,
            plan,
            matrix_limit=matrix_limit,
            progress=lambda line: typer.echo(line + " …", err=True),
        )
        for kind in KINDS:
            queued = plan.records[kind]
            pending = [
                (key, record) for key, record in queued if key not in progress.done
            ]
            summary.skipped[kind] = len(queued) - len(pending)
            if pending:
                typer.echo(
                    f"{'Checking' if dry_run else 'Importing'} {len(pending)} {kind} record(s) …",
                    err=True,
                )
            for batch in batches(
                _ready(broker, pending, to_fetch, summary, plan), max_bytes=batch_bytes
            ):
                body = {
                    "source": broker.base_url,
                    "records": [record for _, record in batch],
                }
                answer = conn.client.post(route, json=body).json()
                results = answer.get("results") if isinstance(answer, dict) else None
                if not isinstance(results, list) or len(results) != len(batch):
                    raise CliError(
                        "Apiome's answer to an import batch did not list every record",
                        exit_code=EXIT_ERROR,
                    )
                for (key, record), result in zip(batch, results):
                    summary.add(kind, key, result)
                    if not dry_run and result.get("outcome") in DONE_OUTCOMES:
                        progress.done.add(key)
                    if kind in ("pact", "verification"):
                        record["content" if kind == "pact" else "result"] = (
                            None  # free the document
                        )
                if not dry_run:
                    progress.save()

    report = dict(
        source=broker.base_url,
        tenant=tenant,
        read_counts=plan.read_counts,
        findings=plan.findings,
        state_file=None if dry_run else str(state),
    )
    _emit(
        fmt,
        migration_document(summary, **report),
        migration_lines(summary, fmt=fmt, **report),
    )
    raise typer.Exit(EXIT_ERROR if summary.refused else EXIT_SUCCESS)


#: ``(command name, function)`` in the order ``pact-broker help`` lists them.
COMMANDS: tuple[tuple[str, Any], ...] = (
    ("publish", publish),
    ("check", check),
    ("list-pacticipants", list_pacticipants),
    ("create-or-update-pacticipant", create_or_update_pacticipant),
    ("delete-pacticipant", delete_pacticipant),
    ("describe-version", describe_version),
    ("create-version-tag", create_version_tag),
    ("delete-version", delete_version),
    ("restore-version", restore_version),
    ("can-i-deploy", can_i_deploy),
    ("record-deployment", record_deployment),
    ("record-release", record_release),
    ("create-environment", create_environment),
    ("create-webhook", create_webhook),
    ("verify", verify),
    ("migrate", migrate),
)
